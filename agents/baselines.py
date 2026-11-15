"""Opponent pool: the kinds of bots other teams are likely to write in 60 minutes.

Test against these, not against yourself. Every bot here decides in well
under 1 ms, except MonteBot with large `iters` (a deliberate trap: the exhibit's
Monte Carlo policy is too slow for the 1 ms limit in Python).

All of them play every variant in engine.variants the simple way a rushed team
would: hand strength from the variant's evaluator, preflop from a quick score.
"""
import random
from itertools import combinations
from engine.cards import rank, suit
from engine import variants as V
from engine.protocol import (Action, ActionType as AT, FOLD, CHECK, CALL, ALL_IN, RAISE_TO)
from .base import Agent


def _chen2(hole):
    """Quick preflop score (Chen-like, ~0..20)."""
    a, b = sorted((rank(hole[0]), rank(hole[1])), reverse=True)
    val = {12: 10, 11: 8, 10: 7, 9: 6}.get(a, (a + 2) / 2)
    if a == b:
        return max(5, val * 2)
    s = val + (2 if suit(hole[0]) == suit(hole[1]) else 0)
    gap = a - b - 1
    s -= [0, 1, 2, 4][min(gap, 3)] + (1 if gap >= 4 else 0)
    if gap <= 1 and a < 10:
        s += 1
    return s


def _omaha_score(hole):
    """Rushed Omaha points, scaled to the Chen range: high pairs, suits, connectors."""
    rs = sorted((rank(c) for c in hole), reverse=True)
    s = sum(max(0, r - 6) for r in rs) * 0.5
    for r in set(rs):
        k = rs.count(r)
        if k == 2: s += 2 + r * 0.35
        if k >= 3: s -= 3
    suits = [sum(1 for c in hole if suit(c) == x) for x in range(4)]
    s += sum(1.5 for k in suits if k == 2) - sum(2 for k in suits if k >= 3)
    if any(rank(c) == 12 and suits[suit(c)] >= 2 for c in hole): s += 1.5
    u = sorted(set(rs))
    s += sum(1 for a, b in zip(u, u[1:]) if b - a <= 2) * 0.8
    return s


def _chen(hole):
    if len(hole) == 2:
        return _chen2(hole)
    if len(hole) == 3:                 # 3-card hold'em: best two
        return max(_chen2(p) for p in combinations(hole, 2))
    return _omaha_score(hole)


def _cat(obs):
    """Standard category 0 (high card) .. 8 (straight flush) under this variant's rules."""
    v = V.get(obs.variant)
    return v.cat(V.hi(v, obs.hole, obs.board))


def _raise(obs, frac_pot):
    if AT.RAISE not in obs.legal and AT.BET not in obs.legal:
        return CALL if AT.CALL in obs.legal else CHECK
    to = obs.bets[obs.seat] + obs.to_call + int(frac_pot * (obs.pot + obs.to_call))
    to = max(obs.min_raise_to, min(to, obs.max_raise_to))
    t = AT.RAISE if AT.RAISE in obs.legal else AT.BET
    return Action(t, to)


def _passive(obs):
    return CHECK if AT.CHECK in obs.legal else CALL


class RandomBot(Agent):
    name = "random"
    def reset(self, seat, n):
        super().reset(seat, n); self.rng = random.Random()
    def act(self, obs):
        r = self.rng.random()
        if r < 0.25: return FOLD if AT.CHECK not in obs.legal else CHECK
        if r < 0.8: return _passive(obs)
        return _raise(obs, self.rng.choice([0.5, 1.0]))


class CallingStation(Agent):
    """Never folds a pair or better, calls most things, rarely raises."""
    name = "station"
    def act(self, obs):
        if obs.street > 0:
            cat = _cat(obs)
            if cat >= 3 and (AT.RAISE in obs.legal or AT.BET in obs.legal):
                return _raise(obs, 0.6)
        if obs.to_call > 0.5 * obs.my_stack and _chen(obs.hole) < 8 and obs.street == 0:
            return FOLD
        return _passive(obs)


class Maniac(Agent):
    """Raises and shoves a lot."""
    name = "maniac"
    def reset(self, seat, n):
        super().reset(seat, n); self.rng = random.Random()
    def act(self, obs):
        r = self.rng.random()
        if r < 0.15 and AT.ALL_IN in obs.legal and _chen(obs.hole) >= 7:
            return ALL_IN
        if r < 0.6:
            return _raise(obs, 1.0)
        return _passive(obs)


class Nit(Agent):
    """Plays only premium hands, folds to aggression without a strong hand."""
    name = "nit"
    def act(self, obs):
        if obs.street == 0:
            c = _chen(obs.hole)
            if c >= 12: return _raise(obs, 1.0)
            if c >= 9 and obs.to_call <= 3 * obs.bb: return _passive(obs)
            return CHECK if AT.CHECK in obs.legal else FOLD
        cat = _cat(obs)
        if cat >= 2: return _raise(obs, 0.75)
        if cat == 1 and obs.to_call <= 0.3 * obs.pot: return _passive(obs)
        return CHECK if AT.CHECK in obs.legal else FOLD


class TAGBot(Agent):
    """Simple tight-aggressive rule bot: a typical decent 60-minute bot."""
    name = "tag"
    def act(self, obs):
        bb_left = obs.my_stack / obs.bb
        if obs.street == 0:
            c = _chen(obs.hole)
            if bb_left < 12:
                return ALL_IN if c >= 9 and AT.ALL_IN in obs.legal else (CHECK if AT.CHECK in obs.legal else FOLD)
            if obs.to_call <= obs.bb:
                if c >= 8: return _raise(obs, 0.8)
                return CHECK if AT.CHECK in obs.legal else FOLD
            if c >= 11: return _raise(obs, 1.0)
            if c >= 9 and obs.to_call <= 0.15 * obs.my_stack: return CALL
            return FOLD
        cat = _cat(obs)
        if cat >= 2: return _raise(obs, 0.7)
        if cat == 1:
            if obs.to_call == 0: return _raise(obs, 0.5)
            if obs.to_call <= 0.5 * obs.pot: return CALL
        return CHECK if AT.CHECK in obs.legal else FOLD


class PushFold(Agent):
    """Shoves or folds every hand preflop."""
    name = "pushfold"
    def act(self, obs):
        if obs.street > 0:
            return _passive(obs)
        if _chen(obs.hole) >= 9 and AT.ALL_IN in obs.legal:
            return ALL_IN
        if obs.to_call > 0 and AT.CALL in obs.legal and _chen(obs.hole) >= 10:
            return CALL
        return CHECK if AT.CHECK in obs.legal else FOLD


class MonteBot(Agent):
    """Port of the site's exhibit policy: Monte Carlo equity vs random hands.
    With iters=160 (as on the site) it blows the 1 ms limit in Python.
    Omaha costs ~2x per iteration, so it uses fewer there."""
    name = "monte"
    def __init__(self, iters=12, agg=0.45):
        self.iters, self.agg = iters, agg
    def reset(self, seat, n):
        super().reset(seat, n); self.rng = random.Random()
    def act(self, obs):
        rng = self.rng
        v = V.get(obs.variant)
        eng = V.engine(v)
        used = set(obs.hole) | set(obs.board)
        rest = [c for c in v.deck if c not in used]
        need = 5 - len(obs.board)
        k = v.hole
        win = 0.0
        iters = self.iters if k <= 3 else max(4, self.iters // 2)
        for _ in range(iters):
            d = rng.sample(rest, need + k)
            b = list(obs.board) + d[k:]
            me, op = eng.hi(obs.hole, b), eng.hi(d[:k], b)
            win += 1 if me > op else 0.5 if me == op else 0
        e = win / iters
        live = sum(obs.in_hand)
        strength = e * live
        x = rng.random()
        if obs.to_call > 0:
            odds = obs.to_call / (obs.pot + obs.to_call)
            if strength > 1.7 and x < 0.25 + 0.4 * self.agg:
                return _raise(obs, 0.5 + 0.6 * rng.random())
            if (strength < 0.9 if obs.street == 0 else e < odds * 0.7) and rng.random() < 0.8:
                return FOLD
            return CALL
        if (strength > 1.3 and x < 0.5) or x < 0.05:
            return _raise(obs, 0.5 + 0.6 * rng.random())
        return CHECK


def _top_pair_or_better(obs):
    """Made hand of at least top pair using a hole card."""
    cat = _cat(obs)
    if cat >= 2:
        return True
    if cat == 1:
        top = max(rank(c) for c in obs.board)
        hr = [rank(c) for c in obs.hole]
        return top in hr or (hr[0] == hr[1] and hr[0] > top)   # top pair or overpair
    return False


class CodexTAG(Agent):
    """What an AI assistant writes when asked for 'a solid tight-aggressive bot':
    open 3 BB (+1 per limper), 3-bet premiums, c-bet 2/3 pot as the preflop raiser,
    value-bet top pair+, call a half-pot bet with top pair, otherwise give up.
    Never bluffs after the flop c-bet and folds to raises without two pair.
    Expected to be the most common bot in the field."""
    name = "codex"

    def act(self, obs):
        bb_left = obs.my_stack / obs.bb
        if obs.street == 0:
            c = _chen(obs.hole)
            if bb_left < 15:                      # the usual "short stack: shove" branch
                if c >= 9 and AT.ALL_IN in obs.legal: return ALL_IN
                return CHECK if AT.CHECK in obs.legal else FOLD
            raised = obs.to_call > obs.bb - obs.my_bet
            if not raised:
                if c >= 8:
                    limpers = sum(1 for e in obs.history
                                  if e.type == "action" and e.code == "C" and e.street == 0)
                    to = (3 + limpers) * obs.bb
                    if AT.RAISE in obs.legal:
                        return Action(AT.RAISE, max(obs.min_raise_to, min(to, obs.max_raise_to)))
                    return _passive(obs)
                return CHECK if AT.CHECK in obs.legal else FOLD
            if c >= 12: return _raise(obs, 1.0)   # 3-bet premiums
            if c >= 10 and obs.to_call <= 0.1 * obs.my_stack: return CALL
            return FOLD
        aggressor = None
        for e in obs.history:
            if e.type == "action" and e.street == 0 and e.code in ("R", "B", "A"):
                aggressor = e.seat
        cat = _cat(obs)
        if obs.to_call == 0:
            if _top_pair_or_better(obs): return _raise(obs, 0.66)
            if obs.street == 1 and aggressor == obs.seat: return _raise(obs, 0.66)   # auto c-bet
            return CHECK
        facing_raise = any(e.type == "action" and e.street == obs.street and e.code == "R"
                           for e in obs.history)
        if cat >= 2 and not facing_raise: return _raise(obs, 0.66)
        if cat >= 2: return CALL
        if _top_pair_or_better(obs) and not facing_raise and obs.to_call <= 0.5 * obs.pot:
            return CALL
        return FOLD


REGISTRY = {
    "random": RandomBot, "station": CallingStation, "maniac": Maniac, "nit": Nit,
    "tag": TAGBot, "pushfold": PushFold, "monte": MonteBot,
    "codex": CodexTAG,
}

# Predicted field (see the rules analysis): mostly AI-written tight-aggressive bots.
FIELDS = {
    "field": ["codex", "codex", "codex", "tag", "pushfold", "nit", "maniac"],
}
