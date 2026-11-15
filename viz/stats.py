"""Per-table player stats and broadcast-style awards for the table viewer.

Fed by the dealer's on_update snapshots (the same ones the page renders), so it
works for the local server and the browser build alike. Nothing here affects
play or scoring.

Luck is measured the way TV poker shows it: whenever the money goes in before
the river and no more betting is possible, every contender's equity is worked
out over the remaining cards (exactly when there are few runouts, otherwise by
sampling). Luck = chips actually won - chips expected. Over a table it sums to
about zero; the "luck box" ran far above expectation, the unluckiest far below.
"""
import random
from itertools import combinations
from engine import variants as V
from engine.table import split_pots

EXACT_MAX = 1500        # enumerate runouts up to this many, else sample
SAMPLES = 500
_EV_CACHE = {}          # the browser build replays tables from hand one: reuse results


def allin_ev(variant, holes, board, total, rng):
    """Expected chips each contender gets back from the pot, and their equity.

    holes: {seat: cards} of contenders; board: cards so far; total: chips put in
    per seat (all seats, folded ones included), after the uncalled excess is removed.
    """
    v = V.get(variant)
    eng = V.engine(v)
    seats = sorted(holes)
    key = (v.name, tuple((s, tuple(holes[s])) for s in seats), tuple(board), tuple(total))
    if key in _EV_CACHE:
        return _EV_CACHE[key]
    used = set(board)
    for s in seats:
        used.update(holes[s])
    rest = [c for c in v.deck if c not in used]
    need = 5 - len(board)
    n_run = 1
    for k in range(need):
        n_run = n_run * (len(rest) - k) // (k + 1)
    if need == 0:
        runs = [()]
    elif n_run <= EXACT_MAX:
        runs = list(combinations(rest, need))
    else:
        runs = [tuple(rng.sample(rest, need)) for _ in range(SAMPLES)]
    n = len(total)
    ev = [0.0] * n
    eq = {s: 0.0 for s in seats}
    pot = sum(total)
    for run in runs:
        b = list(board) + list(run)
        scores = [-1] * n
        lows = [None] * n
        for s in seats:
            scores[s] = eng.hi(holes[s], b)
            lows[s] = eng.lo(holes[s], b)
        won, won_lo = split_pots(total, seats, scores, lows, v.hilo)
        for s in seats:
            ev[s] += won[s] + won_lo[s]
            eq[s] += (won[s] + won_lo[s]) / pot if pot else 0
    m = len(runs)
    out = ({s: ev[s] / m for s in seats}, {s: eq[s] / m for s in seats})
    if len(_EV_CACHE) > 5000:
        _EV_CACHE.clear()
    _EV_CACHE[key] = out
    return out


class TableStats:
    def __init__(self, n, names):
        self.n, self.names = n, names
        z = lambda: [0] * n
        self.hands, self.vpip, self.pfr = z(), z(), z()
        self.bets, self.calls = z(), z()                 # postflop aggression
        self.allins, self.showdowns, self.sd_won = z(), z(), z()
        self.pots_won, self.won_nosd = z(), z()
        self.bluffs, self.hero_calls, self.bad_beats, self.suckouts = z(), z(), z(), z()
        self.biggest = z()
        self.luck = [0.0] * n
        self.ev_spots = z()
        self.biggest_hand = [None] * n                   # (score, name, variant)
        self._new_hand()

    def _new_hand(self):
        self.start = [0] * self.n
        self.lock = None
        self.vp, self.pr = set(), set()
        self.top_bet = 0
        self.last_aggr = None
        self.river_callers = set()
        self.variant = "holdem"
        self.board = []
        self.holes = []

    # ------------------------------------------------------------ events
    def update(self, kind, d):
        if kind not in ("blinds", "deal", "action", "street", "showdown", "win"):
            return
        n = self.n
        if kind == "blinds":
            self._new_hand()
            self.variant = d.get("variant", "holdem")
            self.start = [d["stacks"][i] + d["bets"][i] for i in range(n)]
            self.top_bet = max(d["bb"], max(d["bets"]))
            for i in range(n):
                if d["dealt"][i]:
                    self.hands[i] += 1
            return
        self.board = list(d["board"])
        self.holes = d["holes"]
        if kind == "action":
            i, code, st = d["actor"], d["action"]["code"], d["street"]
            if code == "A":
                self.allins[i] += 1
            if st == 0:
                if code in "CBRA" and i not in self.vp:
                    self.vp.add(i)
                    self.vpip[i] += 1
                if d["bets"][i] > self.top_bet and i not in self.pr:
                    self.pr.add(i)
                    self.pfr[i] += 1
                self.top_bet = max(self.top_bet, d["bets"][i])
            else:
                if code in "BR" or (code == "A" and d["bets"][i] >= max(d["bets"])):
                    self.bets[i] += 1
                elif code in "CA":
                    self.calls[i] += 1
                if code == "C" and st == 3:
                    self.river_callers.add(i)
            if code in "BR" or (code == "A" and d["bets"][i] >= max(d["bets"])):
                self.last_aggr = i
            self._check_lock(d)

    def _check_lock(self, d):
        """All the money that will go in is in, with cards still to come."""
        if self.lock is not None or len(d["board"]) >= 5:
            return
        n = self.n
        cont = [i for i in range(n) if d["dealt"][i] and not d["folded"][i]]
        if len(cont) < 2:
            return
        live = [i for i in cont if d["stacks"][i] > 0]
        top = max(d["bets"][i] for i in cont)
        if len(live) > 1 or (live and d["bets"][live[0]] < top):
            return
        total = [self.start[i] - d["stacks"][i] for i in range(n)]
        order = sorted(range(n), key=lambda k: -total[k])
        total[order[0]] -= total[order[0]] - total[order[1]]       # uncalled excess
        self.lock = ({i: list(d["holes"][i]) for i in cont}, list(d["board"]), total, self.variant)

    def finish(self, d, rng, private=None):
        """Call with the 'win' snapshot. private: seats whose unshown cards may be
        used (bluffs are judged from hidden cards); None = everyone (watch mode)."""
        n = self.n
        winners = d.get("winners") or []
        won = [0] * n
        for w in winners:
            won[w["seat"]] += w["amount"]
            self.pots_won[w["seat"]] += 1
            self.biggest[w["seat"]] = max(self.biggest[w["seat"]], w["amount"])
        sd = d.get("showdown") or {}
        v = V.get(self.variant)
        eng = V.engine(v)
        board = list(d["board"])
        if sd:
            for k, cards in sd.items():
                i = int(k)
                self.showdowns[i] += 1
                if won[i]:
                    self.sd_won[i] += 1
                if len(board) >= 3:
                    s = eng.hi(cards, board)
                    if self.biggest_hand[i] is None or s > self.biggest_hand[i][0]:
                        self.biggest_hand[i] = (s, v.hand_name(s), v.title)
                    if i in self.river_callers and won[i] and v.cat(s) <= 1:
                        self.hero_calls[i] += 1
        else:
            for w in winners:
                i = w["seat"]
                self.won_nosd[i] += 1
                holes = d["holes"][i]
                if private is not None and i not in private:
                    continue
                if i == self.last_aggr and len(board) >= 3 and holes and v.cat(eng.hi(holes, board)) == 0:
                    self.bluffs[i] += 1
        if self.lock is not None and sd:
            holes, lboard, total, variant = self.lock
            ev, eq = allin_ev(variant, holes, lboard, total, rng)
            for s in holes:
                self.luck[s] += won[s] - ev[s]
                self.ev_spots[s] += 1
            fav = [s for s in holes if eq[s] >= 0.7]
            dogs = [s for s in holes if eq[s] <= 0.3 and won[s] > ev[s]]
            for s in fav:
                if won[s] < 0.5 * ev[s]:
                    self.bad_beats[s] += 1
            for s in dogs:
                if fav:
                    self.suckouts[s] += 1
        self._new_hand()

    # ------------------------------------------------------------ page
    def table(self, stacks):
        rows = []
        for i in range(self.n):
            h = self.hands[i]
            rows.append({
                "seat": i, "name": self.names[i], "hands": h,
                "vpip": self.vpip[i], "pfr": self.pfr[i],
                "af": round(self.bets[i] / self.calls[i], 2) if self.calls[i] else (self.bets[i] or None),
                "wtsd": self.showdowns[i], "wsd": self.sd_won[i], "pots": self.pots_won[i],
                "allins": self.allins[i], "luck": round(self.luck[i]), "ev_spots": self.ev_spots[i],
                "biggest": self.biggest[i], "bluffs": self.bluffs[i], "hero": self.hero_calls[i],
                "bad_beats": self.bad_beats[i], "suckouts": self.suckouts[i],
                "net": stacks[i] - 2000 if stacks else 0,
                "best_hand": self.biggest_hand[i][1] if self.biggest_hand[i] else None,
            })
        return rows

    def awards(self, rows):
        """Broadcast-style superlatives. Rate awards need some hands to mean anything."""
        MIN = 12
        out = []
        seen = [r for r in rows if r["hands"] >= MIN]

        def best(key, pool, high=True, ok=lambda r, v: True):
            pool = [r for r in pool if ok(r, key(r))]
            if not pool:
                return None
            return (max if high else min)(pool, key=key)

        def add(code, title, blurb, r, value):
            if r is not None:
                out.append({"code": code, "title": title, "seat": r["seat"], "name": r["name"],
                            "value": value(r), "blurb": blurb})

        vp = lambda r: r["vpip"] / r["hands"]
        times = lambda k, word: f"{k} {word}" + ("" if k == 1 else "s")
        add("luck", "LUCK BOX", "most chips won above all-in equity",
            best(lambda r: r["luck"], rows, ok=lambda r, v: v > 0), lambda r: f"+{r['luck']:,} chips")
        add("unlucky", "UNLUCKIEST", "most chips lost below all-in equity",
            best(lambda r: r["luck"], rows, high=False, ok=lambda r, v: v < 0), lambda r: f"{r['luck']:,} chips")
        add("nit", "MOST NIT", "plays the fewest hands",
            best(vp, seen, high=False), lambda r: f"VPIP {round(100 * vp(r))}%")
        add("action", "ACTION PLAYER", "plays the most hands",
            best(vp, seen), lambda r: f"VPIP {round(100 * vp(r))}%")
        add("aggro", "AGGRESSOR", "bets and raises after the flop the most per call",
            best(lambda r: r["af"] or 0, seen, ok=lambda r, v: v > 0), lambda r: f"AF {r['af']}")
        add("station", "CALLING STATION", "goes to showdown the most",
            best(lambda r: r["wtsd"] / r["hands"], seen, ok=lambda r, v: r["wtsd"] >= 3),
            lambda r: f"{r['wtsd']} showdowns")
        add("bluff", "BLUFF KING", "won without showdown holding nothing",
            best(lambda r: r["bluffs"], rows, ok=lambda r, v: v > 0), lambda r: times(r["bluffs"], "bluff"))
        add("hero", "HERO CALL", "called the river and won with a pair or less",
            best(lambda r: r["hero"], rows, ok=lambda r, v: v > 0), lambda r: times(r["hero"], "call"))
        add("suckout", "SUCKOUT ARTIST", "won all-ins as a big underdog",
            best(lambda r: r["suckouts"], rows, ok=lambda r, v: v > 0), lambda r: times(r["suckouts"], "time"))
        add("badbeat", "BAD BEAT", "lost all-ins as a big favourite",
            best(lambda r: r["bad_beats"], rows, ok=lambda r, v: v > 0), lambda r: times(r["bad_beats"], "time"))
        add("pot", "BIGGEST POT", "largest single pot won",
            best(lambda r: r["biggest"], rows, ok=lambda r, v: v > 0), lambda r: f"{r['biggest']:,} chips")
        add("shove", "SHOVE MACHINE", "most all-ins",
            best(lambda r: r["allins"], rows, ok=lambda r, v: v >= 2), lambda r: f"{r['allins']} all-ins")
        return out
