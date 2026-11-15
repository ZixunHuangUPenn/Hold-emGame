"""ICM (Malmuth-Harville): turn chip stacks into expected points.

Each remaining finishing place goes to a player with probability proportional
to their stack among those not yet placed. Used two ways:
  - the dealer, when a table hits the 200-hand cap: the open places' points are
    split by icm(stacks, points[:alive])
  - the bots, to price risk: busting costs more points than doubling up earns

API
  icm(stacks, prizes)            -> expected prize per player (prizes[0] = 1st).
                                    Players with 0 chips get the lowest prizes.
  icm_one(stacks, prizes, i)     -> the same for player i only (about 2x faster)
  place_probs(stacks)            -> P[i][k]: chance player i finishes in place k+1
  allin_spot(behind, prizes, hero, villain, hero_in, villain_in, pot_extra) -> AllIn:
      points for fold / call-and-win / call-and-lose, the equity hero needs to
      call (ICM) next to the pot-odds equity (chip EV), and the bubble factor

Exact, O(2^n * n). Measured in CPython: see `python -m engine.icm`.
"""
from dataclasses import dataclass

_POP = [bin(m).count("1") for m in range(1 << 10)]


def _split_alive(stacks, prizes):
    n = len(stacks)
    prizes = list(prizes)[:n] + [0.0] * max(0, n - len(prizes))
    live = [i for i in range(n) if stacks[i] > 0]
    dead = [i for i in range(n) if stacks[i] <= 0]
    return n, prizes, live, dead


def _dead_share(prizes, n_live, n_dead):
    low = prizes[n_live:n_live + n_dead]
    return sum(low) / n_dead if n_dead else 0.0


def _ev_all(st, prizes):
    """Exact EV for every player; st all > 0."""
    n = len(st)
    size = 1 << n
    total = float(sum(st))
    prob = [0.0] * size
    used = [0.0] * size
    prob[0] = 1.0
    ev = [0.0] * n
    bits = [(1 << i, i, st[i]) for i in range(n)]
    pop = _POP if n <= 10 else [bin(m).count("1") for m in range(size)]
    for mask in range(size - 1):           # every subset comes before its supersets
        pm = prob[mask]
        if pm == 0.0:
            continue
        um = used[mask]
        f = pm / (total - um)
        pk = prizes[pop[mask]]
        for b, i, s in bits:
            if mask & b:
                continue
            p = f * s
            ev[i] += p * pk
            m2 = mask | b
            if prob[m2] == 0.0:
                used[m2] = um + s
            prob[m2] += p
    return ev


def _ev_one(st, prizes, h):
    """Exact EV for player h only: walk subsets of the *other* players that finish
    ahead of h; h takes the next place with probability s_h / chips left."""
    others = [s for i, s in enumerate(st) if i != h]
    m = len(others)
    size = 1 << m
    sh = st[h]
    total = float(sum(st))
    prob = [0.0] * size
    used = [0.0] * size
    prob[0] = 1.0
    ev = 0.0
    bits = [(1 << j, others[j]) for j in range(m)]
    pop = _POP if m <= 10 else [bin(x).count("1") for x in range(size)]
    for mask in range(size):
        pm = prob[mask]
        if pm == 0.0:
            continue
        um = used[mask]
        f = pm / (total - um)
        ev += f * sh * prizes[pop[mask]]
        for b, s in bits:
            if mask & b:
                continue
            m2 = mask | b
            if prob[m2] == 0.0:
                used[m2] = um + s
            prob[m2] += f * s
    return ev


def icm(stacks, prizes):
    n, prizes, live, dead = _split_alive(stacks, prizes)
    out = [0.0] * n
    if not live:
        return out
    sub = _ev_all([stacks[i] for i in live], prizes[:len(live)])
    for k, i in enumerate(live):
        out[i] = sub[k]
    d = _dead_share(prizes, len(live), len(dead))
    for i in dead:
        out[i] = d
    return out


def icm_one(stacks, prizes, i):
    n, prizes, live, dead = _split_alive(stacks, prizes)
    if stacks[i] <= 0:
        return _dead_share(prizes, len(live), len(dead))
    return _ev_one([stacks[j] for j in live], prizes[:len(live)], live.index(i))


def place_probs(stacks):
    """P[i][k] = chance player i finishes in place k+1."""
    n = len(stacks)
    P = [[0.0] * n for _ in range(n)]
    for k in range(n):
        unit = [0.0] * n
        unit[k] = 1.0
        col = icm(stacks, unit)
        for i in range(n):
            P[i][k] = col[i]
    return P


def points_left(points, alive):
    """Prizes still to hand out among the `alive` players (the top `alive` places)."""
    return list(points[:alive])


@dataclass
class AllIn:
    ev_fold: float        # hero's points if hero folds
    ev_win: float         # ... if hero calls and wins
    ev_lose: float        # ... if hero calls and loses
    need_icm: float       # equity hero needs to call, in points
    need_chips: float     # equity needed by pot odds alone (chip EV)
    bubble: float         # (points lost by losing) / (points gained by winning); 1 = chip EV

    def call_ev(self, equity):
        """Points gained by calling (vs folding) with this equity."""
        return equity * self.ev_win + (1 - equity) * self.ev_lose - self.ev_fold


def allin_spot(behind, prizes, hero, villain, hero_in=0, villain_in=0, pot_extra=0):
    """Hero decides whether to call villain's all-in (heads-up for the rest of the hand).

    behind:      chips behind for every player right now (obs.stacks)
    hero_in:     chips hero already has in this pot (e.g. a blind)
    villain_in:  chips villain has in this pot (the shove)
    pot_extra:   everyone else's chips in the pot (dead money)
    Players other than hero and villain keep `behind`.
    Also works for hero shoving into villain: swap the roles and read ev_win/ev_lose.
    """
    h_total = behind[hero] + hero_in
    v_total = behind[villain] + villain_in
    risk = min(h_total, v_total)
    fold = list(behind)
    fold[villain] = v_total + hero_in + pot_extra
    win = list(behind)
    win[hero] = h_total + risk + pot_extra
    win[villain] = v_total - risk
    lose = list(behind)
    lose[hero] = h_total - risk
    lose[villain] = v_total + risk + pot_extra
    e_f = icm_one(fold, prizes, hero)
    e_w = icm_one(win, prizes, hero)
    e_l = icm_one(lose, prizes, hero)
    span = e_w - e_l
    need = (e_f - e_l) / span if span > 0 else 1.0
    call_cost = risk - hero_in
    need_chips = call_cost / (2 * risk + pot_extra) if risk > 0 else 0.0
    gain, loss = e_w - e_f, e_f - e_l
    bubble = loss / gain if gain > 0 else float("inf")
    return AllIn(e_f, e_w, e_l, max(0.0, min(1.0, need)), need_chips, bubble)


if __name__ == "__main__":
    import random, time
    rng = random.Random(0)
    pts = [100, 60, 40, 30, 20, 10, 5, 0]
    for n in (3, 4, 5, 6, 7, 8):
        st = [rng.randint(200, 6000) for _ in range(n)]
        for name, f in (("icm", lambda: icm(st, pts[:n])), ("icm_one", lambda: icm_one(st, pts[:n], 0)),
                        ("allin_spot", lambda: allin_spot(st, pts[:n], 0, 1, 20, 500, 10))):
            t = time.perf_counter()
            for _ in range(300):
                f()
            print(f"n={n} {name:10s} {1000 * (time.perf_counter() - t) / 300:.3f} ms")
