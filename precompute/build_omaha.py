"""Offline: fit the Omaha preflop model (precompute/omaha_features.py).

For each variant, deal random hands, estimate their equity vs 1 and 3 random
hands by Monte Carlo (hi-lo: share of the pot, halves split), and fit a least-
squares linear model from features() to equity. Writes omaha_preflop.json:

  {"omaha": {"weights": {"1": [...], "3": [...]}, "quantiles": [...], "r2": {...}}, ...}

Run:  python -m precompute.build_omaha [hands] [samples] [variants...]
      default 6000 hands x 300 samples for omaha, omaha5, omaha8 (~5 min on 12 cores)
Needs numpy (offline only; the bot does not).
"""
import json, os, random, sys, time
from multiprocessing import Pool
from engine import variants as V
from precompute.omaha_features import features, PATH, NAMES

OPPS = (1, 3)


def _equity(args):
    variant, hole, samples, seed = args
    v = V.get(variant)
    eng = V.engine(v)
    rng = random.Random(seed)
    rest = [c for c in v.deck if c not in hole]
    k = v.hole
    out = []
    for n_opp in OPPS:
        share = 0.0
        for _ in range(samples):
            d = rng.sample(rest, 5 + k * n_opp)
            board = d[:5]
            hands = [hole] + [d[5 + k * j: 5 + k * (j + 1)] for j in range(n_opp)]
            his = [eng.hi(h, board) for h in hands]
            best = max(his)
            hi_w = [i for i in range(len(hands)) if his[i] == best]
            hi_share = (1.0 / len(hi_w)) if 0 in hi_w else 0.0
            if v.hilo:
                los = [eng.lo(h, board) for h in hands]
                q = [x for x in los if x is not None]
                if q:
                    bl = max(q)
                    lo_w = [i for i in range(len(hands)) if los[i] == bl]
                    lo_share = (1.0 / len(lo_w)) if 0 in lo_w else 0.0
                    share += 0.5 * hi_share + 0.5 * lo_share
                    continue
            share += hi_share
        out.append(share / samples)
    return out


def fit(variant, n_hands, samples, pool):
    import numpy as np
    v = V.get(variant)
    rng = random.Random(7)
    hands = [tuple(rng.sample(v.deck, v.hole)) for _ in range(n_hands)]
    t0 = time.time()
    eqs = pool.map(_equity, [(variant, h, samples, i) for i, h in enumerate(hands)], chunksize=20)
    X = np.array([features(h) for h in hands], dtype=float)
    Y = np.array(eqs, dtype=float)
    res = {"weights": {}, "r2": {}}
    for j, k in enumerate(OPPS):
        w, *_ = np.linalg.lstsq(X, Y[:, j], rcond=None)
        pred = X @ w
        ss = ((Y[:, j] - pred) ** 2).sum()
        r2 = 1 - ss / ((Y[:, j] - Y[:, j].mean()) ** 2).sum()
        res["weights"][str(k)] = [round(float(x), 6) for x in w]
        res["r2"][str(k)] = round(float(r2), 3)
    score = sum(X @ np.array(res["weights"][str(k)]) for k in OPPS) / len(OPPS)
    res["quantiles"] = [round(float(x), 6) for x in np.sort(score)[::max(1, n_hands // 2000)]]
    res["features"] = NAMES
    res["samples"] = {"hands": n_hands, "per_hand": samples}
    print(f"{variant}: {n_hands} hands in {time.time() - t0:.0f}s, R2 {res['r2']}, "
          f"mean eq {Y.mean(axis=0).round(3).tolist()}")
    return res


def main():
    args = sys.argv[1:]
    nums = [int(a) for a in args if a.isdigit()]
    names = [a for a in args if not a.isdigit()] or ["omaha", "omaha5", "omaha8"]
    n_hands = nums[0] if nums else 6000
    samples = nums[1] if len(nums) > 1 else 300
    data = {}
    if os.path.exists(PATH):
        with open(PATH) as f:
            data = json.load(f)
    with Pool() as pool:
        for name in names:
            data[V.get(name).name] = fit(name, n_hands, samples, pool)
            with open(PATH, "w") as f:
                json.dump(data, f)
    print("wrote", PATH)


if __name__ == "__main__":
    main()
