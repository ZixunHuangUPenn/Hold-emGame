"""Print a few hands as an Exhibit-D style message trace (dealer <-> bots).

  python -m eval.trace                  # 3 hands, default lineup
  python -m eval.trace --hands 10 --seed 7
  python -m eval.trace --variant omaha8   # any engine.variants name, or mixed:holdem,omaha
"""
import argparse, random
from engine.table import play_hand
from engine.variants import schedule
from eval.run import FACTORIES, DEFAULT


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hands", type=int, default=3)
    ap.add_argument("--seed", type=int, default=3)
    ap.add_argument("--lineup", default=DEFAULT)
    ap.add_argument("--variant", default="holdem")
    a = ap.parse_args()
    game_of = schedule(a.variant, 1)
    rng = random.Random(a.seed)
    names = a.lineup.split(",")
    agents = [FACTORIES[nm]() for nm in names]
    for i, ag in enumerate(agents):
        ag.reset(i, len(agents))
    print("SEATS: " + ", ".join(f"S{i+1}={nm}" for i, nm in enumerate(names)))

    def log(frm, to, text):
        if frm == "--":
            print("-" * 20, text, "-" * 20)
        else:
            print(f"{frm:>4s} -> {to:<4s} {text}")

    stacks, dealer = [2000] * len(agents), 0
    for h in range(a.hands):
        stacks = play_hand(agents, stacks, dealer, 10, 20, rng, h + 1, 0, 1.0, None, log,
                            variant=game_of(h))
        dealer = (dealer + 1) % len(agents)
        while stacks[dealer] == 0:
            dealer = (dealer + 1) % len(agents)


if __name__ == "__main__":
    main()
