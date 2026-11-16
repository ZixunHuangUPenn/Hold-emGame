"""Run many 8-bot sit-and-gos and report average points per bot type.

  python -m eval.run                                  # default lineup, 200 tables
  python -m eval.run --tables 1000 --lineup ours,tag,tag,station,maniac,nit,pushfold,monte
  python -m eval.run --lineup field                   # predicted field: mostly codex-style bots
  python -m eval.run --variant omaha                  # any engine.variants name
  python -m eval.run --variant mixed:holdem,omaha,shortdeck   # rotate every 8 hands
  python -m eval.run --no-time-limit                  # ignore the 1 ms rule (debugging)

  python -m eval.run --tables 5000 --workers 11       # parallel (timing columns get noisy)
  python -m eval.run --set use_phases=False           # change our params for this run
  python -m eval.run --alt phase_open.late=1.6        # A/B: same tables, current vs changed params
  python -m eval.run --json out.json                  # also write the results as JSON

Seats are shuffled every table; each table gets fresh bot instances, and every
bot's own random generator is seeded from the table, so with --no-time-limit
the same --seed gives the same result for any --workers (with the limit on, a
timeout depends on machine load). Scored like the real event: average points per table.

--set and --alt only affect "ours" seats. Keys may be nested with dots
(phase_open.late=1.6); values are Python literals (0.5, True, "x", (1, 2)).
With --alt every table is played twice, once per parameter set, with the same
seats, deck seed and bot seeds, so the reported difference is paired and much
less noisy than two separate runs.
"""
import argparse, ast, copy, itertools, json, multiprocessing, os, random, statistics, sys, time
from collections import defaultdict
from engine.tournament import TournamentConfig, run_table
from agents.registry import BOTS as FACTORIES, LEAD, OurAgent
from agents.baselines import FIELDS

DEFAULT = f"{LEAD},tag,tag,station,maniac,nit,pushfold,monte"
# --lineup field: our seat plus the predicted field
PRESETS = {k: ",".join([LEAD] + v) for k, v in FIELDS.items()}
TIMES_PER_SEAT = 200          # decision times sampled per seat and table


def utf8_stdout():
    """Windows consoles often default to GBK, which cannot print ± or card suits."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass


# ------------------------------------------------------------ parameters
def parse_sets(items):
    """["a=1", "b.c=True"] -> {"a": 1, "b.c": True}"""
    out = {}
    for item in items or []:
        key, sep, raw = item.partition("=")
        if not sep or not key:
            raise SystemExit(f"--set/--alt expects key=value, got {item!r}")
        try:
            out[key.strip()] = ast.literal_eval(raw.strip())
        except (ValueError, SyntaxError):
            out[key.strip()] = raw.strip()          # bare words stay strings
    return out


def our_params(sets):
    """Dotted overrides -> the params dict OurAgent(params) expects (nested dicts merged)."""
    if not sets:
        return {}
    if OurAgent is None:
        raise SystemExit("--set/--alt need agents/ours/, which is not present")
    from agents.ours.params import PARAMS
    out = {}
    for key, value in sets.items():
        top, *path = key.split(".")
        if top not in PARAMS:
            raise SystemExit(f"unknown parameter {top!r}")
        if not path:
            out[top] = value
            continue
        node = out.setdefault(top, copy.deepcopy(PARAMS[top]))
        for part in path[:-1]:
            node = node[part]
        if not isinstance(node, dict) or path[-1] not in node:
            raise SystemExit(f"unknown parameter {key!r}")
        node[path[-1]] = value
    return out


# ------------------------------------------------------------ one table
def _play(job):
    """Play one table. Top-level so worker processes can pickle it."""
    order, table_seed, params, cfg_kwargs = job
    real = random.Random
    seeds = itertools.count(int(table_seed * 2 ** 40))
    # bots seed themselves with random.Random(); make that reproducible per table
    random.Random = lambda x=None: real(next(seeds) if x is None else x)
    try:
        agents = [OurAgent(params) if nm == "ours" and params else FACTORIES[nm]() for nm in order]
        res = run_table(agents, TournamentConfig(**cfg_kwargs), real(table_seed))
    finally:
        random.Random = real
    return {"order": order, "points": res.points, "place": res.place, "hands": res.hands,
            "times": [st.times[:TIMES_PER_SEAT] for st in res.stats],
            "timeouts": [st.timeouts for st in res.stats],
            "errors": [st.errors for st in res.stats],
            "decisions": [st.decisions for st in res.stats]}


def _plan(names, tables, seed):
    rng = random.Random(seed)
    plan = []
    for _ in range(tables):
        order = names[:]
        rng.shuffle(order)
        plan.append((order, rng.random()))
    return plan


def _map(fn, jobs, workers):
    if workers <= 1:
        return [fn(j) for j in jobs]
    with multiprocessing.get_context("spawn").Pool(workers) as pool:
        return pool.map(fn, jobs, chunksize=max(1, len(jobs) // (workers * 8)))


# ------------------------------------------------------------ summary
def summarize(results):
    acc = defaultdict(lambda: {"pts": [], "place": [], "wins": 0, "times": [],
                               "timeouts": 0, "errors": 0, "decisions": 0})
    for r in results:
        for i, nm in enumerate(r["order"]):
            a = acc[nm]
            a["pts"].append(r["points"][i])
            a["place"].append(r["place"][i])
            a["wins"] += r["place"][i] == 1
            a["times"].extend(r["times"][i])
            a["timeouts"] += r["timeouts"][i]
            a["errors"] += r["errors"][i]
            a["decisions"] += r["decisions"][i]
    out = {}
    for nm, a in acc.items():
        p, ts = a["pts"], sorted(a["times"]) or [0.0]
        out[nm] = {"avg_pts": statistics.mean(p),
                   "se": statistics.stdev(p) / len(p) ** 0.5 if len(p) > 1 else 0.0,
                   "win_pct": 100 * a["wins"] / len(p), "avg_place": statistics.mean(a["place"]),
                   "p50_ms": ts[len(ts) // 2], "p99_ms": ts[int(len(ts) * 0.99)],
                   "timeout_pct": 100 * a["timeouts"] / max(1, a["decisions"]),
                   "errors": a["errors"], "seats": len(p)}
    return out


def _ours_per_table(results):
    return [statistics.mean(r["points"][i] for i, nm in enumerate(r["order"]) if nm == "ours")
            for r in results]


def paired(base, alt):
    """Mean and standard error of (alt - base) for our seats, table by table."""
    d = [b - a for a, b in zip(_ours_per_table(base), _ours_per_table(alt))]
    return statistics.mean(d), (statistics.stdev(d) / len(d) ** 0.5 if len(d) > 1 else 0.0)


def evaluate(names, tables=200, seed=1, variant="holdem", time_limit_ms=1.0,
             sets=None, alt=None, workers=1):
    """Run the tables and return a JSON-ready dict. Scripts (parameter sweeps) call this."""
    names = PRESETS.get(names, names) if isinstance(names, str) else names
    names = names.split(",") if isinstance(names, str) else list(names)
    if len(names) != 8:
        raise SystemExit(f"lineup needs 8 bots, got {len(names)}")
    unknown = sorted(set(names) - set(FACTORIES))
    if unknown:
        raise SystemExit(f"unknown bots {unknown}; available: {sorted(FACTORIES)}")
    if (sets or alt) and "ours" not in names:
        raise SystemExit("--set/--alt only change 'ours', which is not in the lineup")
    cfg = {"time_limit_ms": time_limit_ms, "variant": variant}
    base_params = our_params(sets)
    plan = _plan(names, tables, seed)
    t0 = time.time()
    base = _map(_play, [(o, s, base_params, cfg) for o, s in plan], workers)
    out = {"lineup": names, "tables": tables, "seed": seed, "variant": variant,
           "time_limit_ms": time_limit_ms, "workers": workers, "set": sets or {},
           "hands_per_table": statistics.mean(r["hands"] for r in base),
           "bots": summarize(base)}
    if alt:
        alt_params = dict(base_params, **our_params(dict(sets or {}, **alt)))
        alt_res = _map(_play, [(o, s, alt_params, cfg) for o, s in plan], workers)
        diff, se = paired(base, alt_res)
        out.update({"alt": alt, "alt_bots": summarize(alt_res), "alt_minus_base": diff, "alt_se": se})
    out["seconds"] = time.time() - t0
    return out


def print_table(bots, title):
    print(title)
    print(f"{'bot':10s}{'avg pts':>9s}{'±se':>7s}{'win%':>7s}{'avg place':>10s}"
          f"{'p50 ms':>9s}{'p99 ms':>9s}{'timeouts':>10s}{'errors':>8s}")
    for nm in sorted(bots, key=lambda k: -bots[k]["avg_pts"]):
        b = bots[nm]
        print(f"{nm:10s}{b['avg_pts']:9.1f}{b['se']:7.1f}{b['win_pct']:7.1f}{b['avg_place']:10.2f}"
              f"{b['p50_ms']:9.3f}{b['p99_ms']:9.3f}{b['timeout_pct']:9.2f}%{b['errors']:8d}")


def main():
    utf8_stdout()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tables", type=int, default=200)
    ap.add_argument("--lineup", default=DEFAULT, help=f"8 comma-separated bots, or a preset: {', '.join(PRESETS)}")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--variant", default="holdem")
    ap.add_argument("--no-time-limit", action="store_true")
    ap.add_argument("--workers", type=int, default=1, help="processes; timing is only reliable with 1")
    ap.add_argument("--set", action="append", metavar="KEY=VALUE", help="override our params (repeatable)")
    ap.add_argument("--alt", action="append", metavar="KEY=VALUE", help="A/B against these params (repeatable)")
    ap.add_argument("--json", metavar="PATH", help="also write the results to this file")
    a = ap.parse_args()

    r = evaluate(a.lineup, a.tables, a.seed, a.variant, None if a.no_time_limit else 1.0,
                 parse_sets(a.set), parse_sets(a.alt), max(1, a.workers))
    note = "" if a.workers <= 1 else f", {a.workers} workers (timing columns are noisy)"
    head = f"[{a.variant}] {a.tables} tables in {r['seconds']:.1f}s, avg {r['hands_per_table']:.0f} hands/table{note}"
    if r["set"]:
        head += f"\nours with {r['set']}"
    print_table(r["bots"], head)
    if "alt" in r:
        print()
        print_table(r["alt_bots"], f"same tables, ours with {dict(r['set'], **r['alt'])}")
        print(f"\nours, alt - base: {r['alt_minus_base']:+.2f} ± {r['alt_se']:.2f} points per table (paired)")
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(r, f, indent=2)
        print(f"wrote {a.json}")


if __name__ == "__main__":
    main()
