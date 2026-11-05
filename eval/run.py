"""Run many 8-bot sit-and-gos and report average points per bot type.

  python -m eval.run                                  # default lineup, 200 tables
  python -m eval.run --tables 1000 --lineup ours,tag,tag,station,maniac,nit,pushfold,monte
  python -m eval.run --no-time-limit                  # ignore the 1 ms rule (debugging)

Seats are shuffled every table; each table gets fresh bot instances.
Scored like the real event: average points per table.
"""
import argparse, random, statistics, time
from collections import defaultdict
from engine.tournament import TournamentConfig, run_table
from agents.registry import BOTS as FACTORIES, LEAD

DEFAULT = f"{LEAD},tag,tag,station,maniac,nit,pushfold,monte"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tables", type=int, default=200)
    ap.add_argument("--lineup", default=DEFAULT)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--no-time-limit", action="store_true")
    a = ap.parse_args()

    names = a.lineup.split(",")
    assert len(names) == 8, "lineup needs 8 bots"
    unknown = sorted(set(names) - set(FACTORIES))
    assert not unknown, f"unknown bots {unknown}; available: {sorted(FACTORIES)}"
    cfg = TournamentConfig(time_limit_ms=None if a.no_time_limit else 1.0)
    rng = random.Random(a.seed)
    pts, places, wins = defaultdict(list), defaultdict(list), defaultdict(int)
    times, timeouts, errors, decisions = defaultdict(list), defaultdict(int), defaultdict(int), defaultdict(int)
    hands = []
    t0 = time.time()
    for t in range(a.tables):
        order = names[:]
        rng.shuffle(order)
        agents = [FACTORIES[nm]() for nm in order]
        res = run_table(agents, cfg, random.Random(rng.random()))
        hands.append(res.hands)
        for i, nm in enumerate(order):
            pts[nm].append(res.points[i])
            places[nm].append(res.place[i])
            if res.place[i] == 1:
                wins[nm] += 1
            st = res.stats[i]
            times[nm].extend(st.times[:200])
            timeouts[nm] += st.timeouts
            errors[nm] += st.errors
            decisions[nm] += st.decisions

    print(f"{a.tables} tables in {time.time() - t0:.1f}s, avg {statistics.mean(hands):.0f} hands/table")
    print(f"{'bot':10s}{'avg pts':>9s}{'±se':>7s}{'win%':>7s}{'avg place':>10s}"
          f"{'p50 ms':>9s}{'p99 ms':>9s}{'timeouts':>10s}{'errors':>8s}")
    for nm in sorted(pts, key=lambda k: -statistics.mean(pts[k])):
        p = pts[nm]
        se = statistics.stdev(p) / len(p) ** 0.5 if len(p) > 1 else 0
        ts = sorted(times[nm]) or [0]
        tables_seen = len(p)
        print(f"{nm:10s}{statistics.mean(p):9.1f}{se:7.1f}{100 * wins[nm] / tables_seen:7.1f}"
              f"{statistics.mean(places[nm]):10.2f}{ts[len(ts) // 2]:9.3f}{ts[int(len(ts) * 0.99)]:9.3f}"
              f"{timeouts[nm] / max(1, decisions[nm]) * 100:9.2f}%{errors[nm]:8d}")


if __name__ == "__main__":
    main()
