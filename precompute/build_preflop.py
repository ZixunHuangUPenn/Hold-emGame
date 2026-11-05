"""Offline: equity of each of the 169 starting-hand classes vs 1..7 random hands.

Writes precompute/preflop_equity.json:
  {"AKs": [eq_vs_1, eq_vs_2, ..., eq_vs_7], ...}
Run:  python -m precompute.build_preflop [samples]
Takes a few minutes at the default 6,000 samples per class and opponent count.
At the event, if the variant changes, edit the deck/evaluator and rerun.
"""
import json, os, random, sys
from engine.cards import evaluate, RANKS

OUT = os.path.join(os.path.dirname(__file__), "preflop_equity.json")


def classes():
    out = []
    for hi in range(12, -1, -1):
        for lo in range(hi, -1, -1):
            if hi == lo:
                out.append((RANKS[hi] * 2, hi, lo, False))
            else:
                out.append((RANKS[hi] + RANKS[lo] + "s", hi, lo, True))
                out.append((RANKS[hi] + RANKS[lo] + "o", hi, lo, False))
    return out


def equity(hole, n_opp, samples, rng):
    rest = [c for c in range(52) if c not in hole]
    win = 0.0
    need = 5 + 2 * n_opp
    for _ in range(samples):
        d = rng.sample(rest, need)
        board = d[:5]
        me = evaluate(list(hole) + board)
        best = max(evaluate(d[5 + 2 * k: 7 + 2 * k] + board) for k in range(n_opp))
        if me > best:
            win += 1
        elif me == best:
            ties = sum(1 for k in range(n_opp) if evaluate(d[5 + 2 * k: 7 + 2 * k] + board) == me)
            win += 1 / (ties + 1)
    return win / samples


def main():
    samples = int(sys.argv[1]) if len(sys.argv) > 1 else 6000
    rng = random.Random(42)
    table = {}
    for name, hi, lo, suited in classes():
        hole = (hi, lo + (0 if suited else 13))
        table[name] = [round(equity(hole, k, samples, rng), 4) for k in range(1, 8)]
        print(name, table[name][:3])
    with open(OUT, "w") as f:
        json.dump(table, f)
    print("wrote", OUT)


if __name__ == "__main__":
    main()
