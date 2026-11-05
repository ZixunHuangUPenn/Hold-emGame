"""Opponent pool: the kinds of bots other teams are likely to write in 60 minutes.

Test against these, not against yourself. Every bot here decides in well
under 1 ms, except MonteBot with large `iters` (a deliberate trap: the exhibit's
Monte Carlo policy is too slow for the 1 ms limit in Python).
"""
import random
from engine.cards import evaluate, rank, suit
from engine.protocol import (Action, ActionType as AT, FOLD, CHECK, CALL, ALL_IN, RAISE_TO)
from .base import Agent


def _chen(hole):
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
            cat = evaluate(list(obs.hole) + list(obs.board)) // 13 ** 5
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
        cat = evaluate(list(obs.hole) + list(obs.board)) // 13 ** 5
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
        cat = evaluate(list(obs.hole) + list(obs.board)) // 13 ** 5
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
    With iters=160 (as on the site) it blows the 1 ms limit in Python."""
    name = "monte"
    def __init__(self, iters=12, agg=0.45):
        self.iters, self.agg = iters, agg
    def reset(self, seat, n):
        super().reset(seat, n); self.rng = random.Random()
    def act(self, obs):
        rng = self.rng
        used = set(obs.hole) | set(obs.board)
        rest = [c for c in range(52) if c not in used]
        need = 5 - len(obs.board)
        win = 0.0
        for _ in range(self.iters):
            d = rng.sample(rest, need + 2)
            b = list(obs.board) + d[2:]
            me, op = evaluate(list(obs.hole) + b), evaluate(d[:2] + b)
            win += 1 if me > op else 0.5 if me == op else 0
        e = win / self.iters
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


REGISTRY = {
    "random": RandomBot, "station": CallingStation, "maniac": Maniac, "nit": Nit,
    "tag": TAGBot, "pushfold": PushFold, "monte": MonteBot,
}
