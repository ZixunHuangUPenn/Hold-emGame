"""One 8-bot sit-and-go table, following the official rules (Sec. 4.4-4.5):
2,000 chips each, blinds start 10/20 and rise every 25 hands, the table plays
until one bot has all the chips or 200 hands; points by finishing place, and at
the hand cap the remaining points are split among survivors by ICM.

The blind schedule beyond 10/20 and the points table are NOT published yet
(announced at the build phase), so they live in TournamentConfig as guesses.
"""
import random
from dataclasses import dataclass, field
from .table import play_hand, SeatStats
from .icm import icm


@dataclass
class TournamentConfig:
    n_seats: int = 8
    start_stack: int = 2000
    blinds: list = field(default_factory=lambda: [
        (10, 20), (15, 30), (25, 50), (40, 80), (60, 120), (100, 200), (150, 300), (200, 400)])
    hands_per_level: int = 25
    max_hands: int = 200
    # points for 1st..8th. PLACEHOLDER: the real table is announced at the event.
    points: list = field(default_factory=lambda: [100, 60, 40, 30, 20, 10, 5, 0])
    time_limit_ms: float = 1.0      # official: 1 ms per decision; None disables


@dataclass
class TableResult:
    points: list          # per seat (float, ICM-split at the hand cap)
    place: list           # per seat, 1 = winner (float when ICM-split: expected place)
    hands: int
    stats: list           # SeatStats per seat


def run_table(agents, cfg=None, rng=None, log=None, on_update=None):
    cfg = cfg or TournamentConfig()
    rng = rng or random.Random()
    n = len(agents)
    for i, a in enumerate(agents):
        a.reset(i, n)                       # bots are reset at the start of each table
    stacks = [cfg.start_stack] * n
    stats = [SeatStats() for _ in range(n)]
    points = [0.0] * n
    place = [0.0] * n
    dealer = rng.randrange(n)
    hand = 0
    next_place = n                           # worst place still to hand out
    while sum(1 for s in stacks if s > 0) > 1 and hand < cfg.max_hands:
        level = min(hand // cfg.hands_per_level, len(cfg.blinds) - 1)
        sb, bb = cfg.blinds[level]
        before = list(stacks)
        stacks = play_hand(agents, stacks, dealer, sb, bb, rng, hand + 1, level,
                           cfg.time_limit_ms, stats, log, on_update)
        assert sum(stacks) == sum(before), "chips not conserved"
        hand += 1
        busted = [i for i in range(n) if before[i] > 0 and stacks[i] == 0]
        # busted in the same hand: bigger starting stack finishes higher; equal stacks split
        busted.sort(key=lambda i: before[i])
        k = 0
        while k < len(busted):
            grp = [i for i in busted if before[i] == before[busted[k]]]
            places = list(range(next_place, next_place - len(grp), -1))
            pts = sum(cfg.points[p - 1] for p in places) / len(grp)
            for i in grp:
                points[i] = pts
                place[i] = sum(places) / len(grp)
            next_place -= len(grp)
            k += len(grp)
            if on_update:
                for i in grp:
                    on_update("eliminated", {"seat": i, "place": place[i], "points": points[i]})
        if sum(1 for s in stacks if s > 0) > 1:
            j = (dealer + 1) % n
            while stacks[j] == 0:
                j = (j + 1) % n
            dealer = j
    alive = [i for i in range(n) if stacks[i] > 0]
    if len(alive) == 1:
        points[alive[0]] = cfg.points[0]
        place[alive[0]] = 1
    else:  # hand cap: ICM split of the places still open
        ev = icm([stacks[i] for i in alive], cfg.points[:len(alive)])
        evp = icm([stacks[i] for i in alive], list(range(1, len(alive) + 1)))
        for k, i in enumerate(alive):
            points[i] = ev[k]
            place[i] = evp[k]
    if on_update:
        on_update("finished", {"points": points, "place": place, "hands": hand, "stacks": stacks})
    return TableResult(points, place, hand, stats)
