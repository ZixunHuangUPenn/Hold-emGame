"""Offline: equity of each 2-card starting-hand class vs 1..7 random hands.

Writes precompute/preflop_equity.json (hold'em) or preflop_<variant>.json:
  {"AKs": [eq_vs_1, eq_vs_2, ..., eq_vs_7], ...}
Run:  python -m precompute.build_preflop [samples] [--variant shortdeck]
Takes a few minutes at the default 6,000 samples per class and opponent count.
Works for any 2-hole-card variant in engine.variants (deck and ranking come from there).
"""
import json, os, random, sys
from engine.cards import RANKS
from engine import variants as V


def out_path(variant):
    name = "preflop_equity.json" if variant == "holdem" else f"preflop_{variant}.json"
    return os.path.join(os.path.dirname(__file__), name)


def classes(min_rank=0):
    out = []
    for hi in range(12, min_rank - 1, -1):
        for lo in range(hi, min_rank - 1, -1):
            if hi == lo:
                out.append((RANKS[hi] * 2, hi, lo, False))
            else:
                out.append((RANKS[hi] + RANKS[lo] + "s", hi, lo, True))
                out.append((RANKS[hi] + RANKS[lo] + "o", hi, lo, False))
    return out


def equity(hole, n_opp, samples, rng, variant="holdem"):
    v = V.get(variant)
    evaluate = V.engine(v).any_eval
    rest = [c for c in v.deck if c not in hole]
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
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    variant = sys.argv[sys.argv.index("--variant") + 1] if "--variant" in sys.argv else "holdem"
    args = [a for a in args if a != variant]
    v = V.get(variant)
    assert v.hole == 2 and not v.omaha, "2-card variants only (Omaha: precompute.build_omaha)"
    samples = int(args[0]) if args else 6000
    rng = random.Random(42)
    table = {}
    for name, hi, lo, suited in classes(v.min_rank):
        hole = (hi, lo + (0 if suited else 13))
        table[name] = [round(equity(hole, k, samples, rng, v.name), 4) for k in range(1, 8)]
        print(name, table[name][:3])
    out = out_path(v.name)
    with open(out, "w") as f:
        json.dump(table, f)
    print("wrote", out)


if __name__ == "__main__":
    main()
