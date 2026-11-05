"""Malmuth-Harville ICM: chance of finishing in each place is proportional to stack.

icm(stacks, prizes) -> expected prize per player. prizes[0] is 1st place.
Exact recursion with memo over the set of players still unplaced (2^n states).
"""
from functools import lru_cache


def icm(stacks, prizes):
    n = len(stacks)
    prizes = list(prizes) + [0] * max(0, n - len(prizes))
    stacks = tuple(stacks)

    @lru_cache(maxsize=None)
    def ev(mask, place):
        """Expected prize of each player in mask, given places < `place` are taken."""
        out = [0.0] * n
        if mask == 0 or place >= n:
            return tuple(out)
        tot = sum(stacks[i] for i in range(n) if mask >> i & 1)
        if tot == 0:
            return tuple(out)
        for i in range(n):
            if mask >> i & 1:
                p = stacks[i] / tot
                out[i] += p * prizes[place]
                sub = ev(mask & ~(1 << i), place + 1)
                for j in range(n):
                    out[j] += p * sub[j]
        return tuple(out)

    return list(ev((1 << n) - 1, 0))
