"""Preflop strength for Omaha-family hands (4 or 5 hole cards), without a table.

There are ~16k strategically different 4-card hands (and far more 5-card ones),
too many to simulate one by one. Instead precompute.build_omaha fits a linear
model from these features to Monte Carlo equity, and writes the weights to
precompute/omaha_preflop.json. At run time:

    from precompute.omaha_features import PreflopModel
    m = PreflopModel("omaha")          # or "omaha5", "omaha8", "omaha-nl"
    m.equity(hole, n_opp)              # predicted equity vs n_opp random hands (1..3 fitted)
    m.pct(hole)                        # fraction of starting hands at least this strong

Feature extraction is ~10 us; everything is plain Python.
"""
import bisect, json, os

PATH = os.path.join(os.path.dirname(__file__), "omaha_preflop.json")
LOW = {12: 1, 0: 2, 1: 3, 2: 4, 3: 5, 4: 6, 5: 7, 6: 8}

NAMES = [
    "bias", "rank_sum", "broadways", "aces", "kings",
    "pairs", "pair_hi", "aa", "kk", "qq", "trips",
    "suited_groups", "double_suited", "suited_ace", "suited_king", "suit3",
    "conn1", "conn2", "window4", "window5", "rundown",
    "low_cards", "a2", "a3", "a_low", "low_pairs",
    "dangler",
]


def features(hole):
    rs = [c % 13 for c in hole]
    ss = [c // 13 for c in hole]
    srt = sorted(rs, reverse=True)
    cnt = {}
    for r in rs:
        cnt[r] = cnt.get(r, 0) + 1
    pairs = [r for r, k in cnt.items() if k == 2]
    suits = [ss.count(x) for x in range(4)]
    suited_groups = sum(1 for k in suits if k >= 2)
    ace_suit = [ss[i] for i in range(len(hole)) if rs[i] == 12]
    king_suit = [ss[i] for i in range(len(hole)) if rs[i] == 11]
    distinct = sorted(cnt)
    # connectivity: neighbours among distinct ranks (ace also low)
    dr = set(distinct)
    if 12 in dr:
        dr.add(-1)
    conn1 = sum(1 for r in distinct if r + 1 in dr or (r == 12 and 0 in dr))
    conn2 = sum(1 for a in distinct for b in distinct if 0 < b - a <= 2)
    best_w = 0
    for lo in range(-1, 9):                  # 5-rank windows (ace-low included)
        w = sum(1 for r in dr if lo <= r <= lo + 4)
        best_w = max(best_w, w)
    window4 = 1 if best_w >= 4 else 0
    window5 = 1 if best_w >= 5 else 0
    rundown = 1 if len(distinct) >= 4 and window4 and srt[3] >= 5 else 0
    lows = {LOW[r] for r in rs if r in LOW}
    low_cards = len(lows)
    a2 = 1 if 1 in lows and 2 in lows else 0
    a3 = 1 if 1 in lows and 3 in lows else 0
    a_low = 1 if 1 in lows and len(lows) >= 2 else 0
    low_pairs = sum(1 for r in pairs if r in LOW)
    # dangler: a card unconnected (gap > 3), unpaired and unsuited with the rest
    dangler = 0
    for i, r in enumerate(rs):
        if cnt[r] > 1 or suits[ss[i]] > 1:
            continue
        if all(abs(r - x) > 3 and not (r == 12 and x <= 2) and not (x == 12 and r <= 2)
               for j, x in enumerate(rs) if j != i):
            dangler += 1
    return [
        1.0, sum(rs) / 12.0, sum(1 for r in rs if r >= 8), rs.count(12), rs.count(11),
        len(pairs), (max(pairs) + 1) / 13.0 if pairs else 0.0,
        1 if cnt.get(12) == 2 else 0, 1 if cnt.get(11) == 2 else 0, 1 if cnt.get(10) == 2 else 0,
        sum(1 for k in cnt.values() if k >= 3),
        suited_groups, 1 if suited_groups >= 2 else 0,
        1 if any(suits[s] >= 2 for s in ace_suit) else 0,
        1 if any(suits[s] >= 2 for s in king_suit) else 0,
        sum(1 for k in suits if k >= 3),
        conn1, conn2, window4, window5, rundown,
        low_cards, a2, a3, a_low, low_pairs,
        dangler,
    ]


class PreflopModel:
    def __init__(self, variant, path=PATH):
        from engine.variants import get
        name = get(variant).name
        key = {"omaha-nl": "omaha"}.get(name, name)
        with open(path) as f:
            data = json.load(f)[key]
        self.w = {int(k): v for k, v in data["weights"].items()}   # n_opp -> weights
        self.q = data["quantiles"]          # sorted predicted scores of random hands
        self.r2 = data.get("r2")

    def equity(self, hole, n_opp=1):
        k = min(self.w, key=lambda x: abs(x - n_opp))
        f = features(hole)
        return sum(a * b for a, b in zip(self.w[k], f))

    def score(self, hole):
        """Blend of heads-up and 3-way equity (the ranking used for pct)."""
        f = features(hole)
        ks = sorted(self.w)
        return sum(sum(a * b for a, b in zip(self.w[k], f)) for k in ks) / len(ks)

    def pct(self, hole):
        s = self.score(hole)
        i = bisect.bisect_left(self.q, s)
        return max(0.001, 1.0 - i / len(self.q))
