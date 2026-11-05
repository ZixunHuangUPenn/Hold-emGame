"""
Castle Challenge solver (Colonel Blotto variant)
  - 100 soldiers, 5 castles worth 1..5 points.
  - Game 1 (head-to-head): avg castle points vs every other applicant. Ties split.
  - Game 2 (4-way): most soldiers takes each castle (ties split points); rank by
    points, payouts 9/4/2/0 by place, tied places split payouts.

Your score depends on the FIELD (what other applicants submit). So the solver:
  1. Builds field models (mixtures of human archetypes + noise, plus "evolved"
     fields made of strategic players).
  2. Game 1: computes the EXACT best response to a field via dynamic programming
     (payoff is additive across castles, so it decomposes per castle).
  3. Game 2: Monte Carlo + hill climbing / restarts (payoff is rank-based, so it
     doesn't decompose).
  4. Checks robustness: scores top candidates against every field model.

Usage:  python castle_solver.py            (full run)
        python castle_solver.py --quick    (fewer samples)
"""
import numpy as np, sys, itertools

V = np.array([1, 2, 3, 4, 5])
N, K = 100, 5
RNG = np.random.default_rng(0)
QUICK = "--quick" in sys.argv

# --------------------------------------------------------------------------
# Utilities
# --------------------------------------------------------------------------
def normalize(a):
    """Round an arbitrary nonnegative vector to integers summing to 100."""
    a = np.maximum(np.asarray(a, float), 0)
    a = a / a.sum() * N
    f = np.floor(a).astype(int)
    r = N - f.sum()
    f[np.argsort(-(a - f))[:r]] += 1
    return f

def jitter(a, rng, scale):
    """Humans nudge numbers (21 instead of 20 to win ties). Move soldiers randomly."""
    a = a.copy()
    for _ in range(rng.poisson(scale)):
        i, j = rng.integers(K, size=2)
        if a[i] > 0:
            a[i] -= 1; a[j] += 1
    return a

# --------------------------------------------------------------------------
# Field models
# --------------------------------------------------------------------------
ARCHETYPES = {
    # name: (allocation, weight in "naive human" field)
    "uniform":        ([20, 20, 20, 20, 20], 10),
    "uniform+":       ([19, 20, 20, 20, 21], 4),
    "proportional":   ([7, 13, 20, 27, 33], 14),
    "proportional+":  ([6, 13, 20, 27, 34], 6),
    "top-heavy":      ([0, 10, 20, 30, 40], 6),
    "top-two":        ([0, 0, 0, 50, 50], 5),
    "top-three":      ([0, 0, 33, 33, 34], 7),
    "skip-5":         ([25, 25, 25, 25, 0], 3),
    "8pts 3+5":       ([0, 0, 50, 0, 50], 3),
    "8pts 1+3+4":     ([34, 0, 33, 33, 0], 2),
    "8pts 2+3+4 ":    ([0, 34, 33, 33, 0], 3),
    "8pts 1+2+5":     ([33, 33, 0, 0, 34], 2),
    "cheap-low":      ([2, 3, 30, 32, 33], 5),
    "mid-heavy":      ([5, 15, 30, 30, 20], 4),
    "all-in-5":       ([0, 0, 0, 0, 100], 1),
    "skip-1":         ([0, 22, 25, 26, 27], 6),
}

def sample_field(n, rng, mix=None, jitter_scale=6, dirichlet_frac=0.15):
    """Sample n opponents. mix: dict name->weight (default: naive human field)."""
    names = list(ARCHETYPES)
    w = np.array([ (mix or {}).get(k, ARCHETYPES[k][1]) for k in names ], float)
    w /= w.sum()
    out = np.empty((n, K), int)
    for t in range(n):
        if rng.random() < dirichlet_frac:          # "random-ish" players
            out[t] = normalize(rng.dirichlet(np.ones(K) * 1.5))
        else:
            out[t] = jitter(np.array(ARCHETYPES[names[rng.choice(len(names), p=w)]][0]),
                            rng, jitter_scale)
    return out

# --------------------------------------------------------------------------
# Game 1: exact best response by DP
# --------------------------------------------------------------------------
def castle_value_table(field):
    """val[i, s] = expected points from castle i when sending s soldiers vs field."""
    val = np.zeros((K, N + 1))
    for i in range(K):
        counts = np.bincount(field[:, i], minlength=N + 1)[:N + 1] / len(field)
        less = np.concatenate([[0], np.cumsum(counts)[:-1]])
        val[i] = V[i] * (less + 0.5 * counts)
    return val

def g1_best_response(field, val=None):
    if val is None: val = castle_value_table(field)
    dp = np.full((K + 1, N + 1), -np.inf); dp[0, 0] = 0
    arg = np.zeros((K + 1, N + 1), int)
    for i in range(K):
        for tot in range(N + 1):
            cand = dp[i, :tot + 1][::-1] + val[i, :tot + 1]   # s soldiers to castle i
            s = int(np.argmax(cand)); dp[i + 1, tot] = cand[s]; arg[i + 1, tot] = s
    alloc, tot = [], N
    for i in range(K, 0, -1):
        s = arg[i, tot]; alloc.append(s); tot -= s
    return np.array(alloc[::-1]), dp[K, N]

def g1_score(a, field):
    a = np.asarray(a)
    win = (a > field) + 0.5 * (a == field)
    return float((win * V).sum(1).mean())

# --------------------------------------------------------------------------
# Game 2: Monte Carlo 4-way battle
# --------------------------------------------------------------------------
PAY = np.array([9, 4, 2, 0], float)

def make_groups(field, n_groups, rng):
    idx = rng.integers(len(field), size=(n_groups, 3))
    return field[idx]                                   # (G, 3, K)

def g2_scores(cands, groups):
    """cands: (C, K). groups: (G, 3, K). Returns expected payoff per candidate."""
    cands = np.atleast_2d(cands)
    C, G = len(cands), len(groups)
    allp = np.concatenate([np.broadcast_to(cands[:, None, None, :], (C, G, 1, K)),
                           np.broadcast_to(groups[None], (C, G, 3, K))], axis=2)  # (C,G,4,K)
    mx = allp.max(2, keepdims=True)
    top = (allp == mx)
    pts = (top / top.sum(2, keepdims=True) * V).sum(3)          # (C,G,4)
    me = pts[:, :, :1]
    better = (pts[:, :, 1:] > me + 1e-9).sum(2)                 # players strictly ahead
    tied = (np.abs(pts[:, :, 1:] - me) < 1e-9).sum(2)           # players tied with me
    csum = np.concatenate([[0], np.cumsum(PAY)])
    payoff = (csum[better + tied + 1] - csum[better]) / (tied + 1)
    return payoff.mean(1)

def neighbors(a, step):
    out = []
    for i, j in itertools.permutations(range(K), 2):
        if a[i] >= step:
            b = a.copy(); b[i] -= step; b[j] += step; out.append(b)
    return np.array(out)

def g2_optimize(field, rng, n_groups=4000, restarts=12, starts=None):
    groups = make_groups(field, n_groups, rng)           # common random numbers
    best, best_s = None, -1
    starts = list(starts or []) + [normalize(rng.dirichlet(np.ones(K))) for _ in range(restarts)]
    for a in starts:
        a = np.array(a); s = g2_scores(a, groups)[0]
        for step in (10, 5, 3, 2, 1):
            improved = True
            while improved:
                nb = neighbors(a, step)
                sc = g2_scores(nb, groups)
                k = int(np.argmax(sc)); improved = sc[k] > s + 1e-9
                if improved: a, s = nb[k], sc[k]
        if s > best_s: best, best_s = a, s
    # re-score on fresh groups to avoid overfitting the sample
    return best, g2_scores(best, make_groups(field, n_groups, rng))[0]

# --------------------------------------------------------------------------
# "Evolved" fields: what if many applicants are strategic?
# --------------------------------------------------------------------------
def evolve_field_g1(base, rng, rounds=30, frac=0.04):
    """Fictitious-play-style: repeatedly add best responders into the field."""
    field = base.copy()
    for _ in range(rounds):
        br, _ = g1_best_response(field)
        m = int(len(field) * frac)
        newcomers = np.array([jitter(br, rng, 3) for _ in range(m)])
        field = np.vstack([field, newcomers])
    return field

def evolve_field_g2(base, rng, rounds=10, frac=0.06):
    field = base.copy()
    for _ in range(rounds):
        br, _ = g2_optimize(field, rng, n_groups=1500 if QUICK else 2500, restarts=4)
        m = int(len(field) * frac)
        field = np.vstack([field, [jitter(br, rng, 3) for _ in range(m)]])
    return field

# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------
def main():
    n = 3000 if QUICK else 8000
    fields = {
        "naive humans":       sample_field(n, RNG),
        "noisy (more random)": sample_field(n, RNG, jitter_scale=12, dirichlet_frac=0.4),
        "top-heavy crowd":    sample_field(n, RNG, mix={"top-heavy": 15, "top-three": 15,
                                    "cheap-low": 15, "skip-1": 15, "proportional": 10}),
    }
    print("Evolving strategic fields (adds best responders over many rounds)...")
    fields["strategic G1"] = evolve_field_g1(fields["naive humans"], RNG)
    fields["strategic G2"] = evolve_field_g2(fields["naive humans"], RNG)

    # ---- Game 1
    print("\n=== GAME 1: head-to-head (max 15 pts, avg vs field) ===")
    g1_cands = {}
    for name, f in fields.items():
        br, v = g1_best_response(f)
        g1_cands[f"BR[{name}]"] = br
        print(f"  best response to {name:20s}: {br}  -> {v:.3f} pts")
    for k in ["uniform", "proportional", "top-three"]:
        g1_cands[k] = np.array(ARCHETYPES[k][0])
    print("\n  Robustness (rows = candidate, cols = field):")
    print("  " + " " * 30 + "".join(f"{n[:12]:>13s}" for n in fields) + "     mean      min")
    table = {}
    for cname, a in g1_cands.items():
        sc = [g1_score(a, f) for f in fields.values()]
        table[cname] = sc
        print(f"  {cname[:22]:22s}{str(a):>9s}" + "".join(f"{s:13.3f}" for s in sc)
              + f"{np.mean(sc):9.3f}{np.min(sc):9.3f}")
    # a robust G1 pick: best response to the union of all fields
    union = np.vstack([f[RNG.choice(len(f), 3000)] for f in fields.values()])  # equal weight
    avg_val = np.mean([castle_value_table(f) for f in fields.values()], axis=0)
    robust1, _ = g1_best_response(None, avg_val)
    print(f"\n  Robust G1 pick (max mean over fields, exact DP): {robust1}  "
          f"mean={np.mean([g1_score(robust1, f) for f in fields.values()]):.3f}")

    # ---- Game 2
    print("\n=== GAME 2: 4-way battle (payout 9/4/2/0, avg 3.75) ===")
    g2_cands = {}
    G = 2000 if QUICK else 5000
    for name, f in fields.items():
        a, s = g2_optimize(f, RNG, n_groups=G, restarts=6 if QUICK else 12,
                           starts=[robust1, g1_cands[f"BR[{name}]"]])
        g2_cands[f"BR[{name}]"] = a
        print(f"  best response to {name:20s}: {a}  -> {s:.3f}")
    g2_cands["robust G1 pick"] = robust1
    for k in ["uniform", "proportional", "top-three"]:
        g2_cands[k] = np.array(ARCHETYPES[k][0])
    print("\n  Robustness:")
    print("  " + " " * 30 + "".join(f"{n[:12]:>13s}" for n in fields) + "     mean      min")
    grp = {n: make_groups(f, G, RNG) for n, f in fields.items()}
    for cname, a in g2_cands.items():
        sc = [g2_scores(a, g)[0] for g in grp.values()]
        print(f"  {cname[:22]:22s}{str(a):>9s}" + "".join(f"{s:13.3f}" for s in sc)
              + f"{np.mean(sc):9.3f}{np.min(sc):9.3f}")
    robust2, s = g2_optimize(union, RNG, n_groups=G, restarts=12,
                             starts=list(g2_cands.values()))
    sc = [g2_scores(robust2, g)[0] for g in grp.values()]
    print(f"\n  Robust G2 pick (optimized vs union of fields): {robust2}  "
          f"mean={np.mean(sc):.3f} min={np.min(sc):.3f}")

if __name__ == "__main__":
    main()
