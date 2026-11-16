"""Offline: hold'em all-in equity of every starting-hand class against every other.

Writes precompute/hu_equity.json, used by the GTO trainer's push/fold solver and
by the live advisor when you face an all-in:
  {"hands": ["AA", "AKs", ...169], "eq": [[...169] x 169]}   eq[i][j] in 1/1000
eq[i][j] is hand class i's equity (ties count half) against class j, averaged over
random non-colliding suit combos and random boards.
Run:  python -m precompute.build_hu_equity [samples] [--workers N]
About a minute with 11 workers at the default 2,000 samples per matchup.
"""
import json, os, random, sys
from multiprocessing import Pool

from engine.cards import RANKS, evaluate

OUT = os.path.join(os.path.dirname(__file__), "hu_equity.json")


def classes():
    """The 169 classes in the usual 13x13 grid order (row = high rank, AA first)."""
    out = []
    for i in range(12, -1, -1):
        for j in range(12, -1, -1):
            if i == j:
                out.append(RANKS[i] * 2)
            elif j < i:
                out.append(RANKS[i] + RANKS[j] + "s")
            else:
                out.append(RANKS[j] + RANKS[i] + "o")
    return out


def combos(name):
    hi, lo = RANKS.index(name[0]), RANKS.index(name[1])
    if hi == lo:
        return [(hi + 13 * a, lo + 13 * b) for a in range(4) for b in range(a + 1, 4)]
    if name[2] == "s":
        return [(hi + 13 * s, lo + 13 * s) for s in range(4)]
    return [(hi + 13 * a, lo + 13 * b) for a in range(4) for b in range(4) if a != b]


def row(args):
    i, samples = args
    names = classes()
    rng = random.Random(1000 + i)
    a_combos = combos(names[i])
    out = []
    for j in range(len(names)):
        if j < i:
            out.append(None)                      # filled from the symmetric entry
            continue
        pairs = [(a, b) for a in a_combos for b in combos(names[j]) if not set(a) & set(b)]
        win = 0.0
        for _ in range(samples):
            a, b = pairs[rng.randrange(len(pairs))]
            rest = [c for c in range(52) if c not in a and c not in b]
            board = rng.sample(rest, 5)
            x, y = evaluate(list(a) + board), evaluate(list(b) + board)
            win += 1.0 if x > y else 0.5 if x == y else 0.0
        out.append(win / samples)
    return out


def main():
    args = [a for a in sys.argv[1:]]
    workers = int(args[args.index("--workers") + 1]) if "--workers" in args else os.cpu_count()
    nums = [a for a in args if a.isdigit() and (not "--workers" in args or a != args[args.index("--workers") + 1])]
    samples = int(nums[0]) if nums else 2000
    names = classes()
    with Pool(workers) as pool:
        rows = pool.map(row, [(i, samples) for i in range(len(names))])
    n = len(names)
    eq = [[0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i, n):
            v = rows[i][j]
            if i == j:
                v = 0.5                           # same class: symmetric by definition
            eq[i][j] = round(1000 * v)
            eq[j][i] = 1000 - eq[i][j]
    with open(OUT, "w") as f:
        json.dump({"hands": names, "eq": eq}, f, separators=(",", ":"))
    print(f"wrote {OUT}: {n}x{n}, {samples} samples per matchup")


if __name__ == "__main__":
    main()
