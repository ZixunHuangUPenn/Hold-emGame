"""Poker variants: deck, hole cards, hand ranking, betting limit, hi-lo.

The real variant is announced when the build phase starts. Everything that
differs between variants lives here, so the dealer, the bots and the
precompute scripts all ask the same object:

    v = get("omaha")
    v.deck, v.hole, v.pot_limit, v.hilo
    v.hi(hole, board) -> int, higher is better (same scale as cards.evaluate
                         for hold'em: category * 13**5 + kickers)
    v.lo(hole, board) -> int or None: ace-to-five low, 8 or better (hi-lo only);
                         higher is better, None = no qualifying low
    v.hand_name(score), v.cat(score) -> standard category index 0..8

Supported names (aliases in VARIANTS):
    holdem      no-limit Texas hold'em (2 hole, best 5 of 7)
    shortdeck   6+ hold'em, 36 cards: A-6-7-8-9 is the low straight, flush beats a
                full house, and (Triton rules) trips beat a straight
    omaha       pot-limit Omaha (4 hole, exactly 2 hole + 3 board)
    omaha-nl    no-limit Omaha
    omaha5      pot-limit 5-card Omaha
    omaha8      pot-limit Omaha hi-lo, 8 or better
    pineapple   no-limit hold'em with 3 hole cards played as "best 5 of 8"
                (no discard round; covers 3-card hold'em variants)
Mixed games: schedule("mixed:holdem,omaha,shortdeck", every=8) rotates variants.
"""
from dataclasses import dataclass
from itertools import combinations
from .cards import evaluate as _holdem_eval, CATEGORIES, P5

HIGH, PAIR, TWO_PAIR, TRIPS, STRAIGHT, FLUSH, FULL_HOUSE, QUADS, STRAIGHT_FLUSH = range(9)


# --------------------------------------------------------------- 5+ card evaluator
def _straight_high(mask, wheel):
    for r in range(12, 3, -1):
        if (mask >> (r - 4)) & 31 == 31:
            return r
    return wheel[1] if mask & wheel[0] == wheel[0] else -1


def make_evaluator(order, wheel):
    """Best hand from any number (>= 5) of cards.

    order: list of the 9 standard categories from weakest to strongest; the score's
           category digit is the position in this list.
    wheel: (rank mask of the lowest straight, its high rank for scoring).
    """
    pos = [order.index(c) for c in range(9)]
    top = [[r for r in range(12, -1, -1) if (m >> r) & 1] for m in range(1 << 13)]
    sh = [_straight_high(m, wheel) for m in range(1 << 13)]

    def score(cat, ks):
        s = pos[cat]
        for i in range(5):
            s = s * 13 + (ks[i] if i < len(ks) else 0)
        return s

    def ev(cards):
        rc = [0] * 13
        sm = [0, 0, 0, 0]
        sc = [0, 0, 0, 0]
        mask = 0
        for c in cards:
            r = c % 13
            s = c // 13
            rc[r] += 1
            sc[s] += 1
            sm[s] |= 1 << r
            mask |= 1 << r
        best = -1
        fs = -1
        for s in range(4):
            if sc[s] >= 5:
                fs = s
        if fs >= 0:
            h = sh[sm[fs]]
            if h >= 0:
                best = max(best, score(STRAIGHT_FLUSH, [h]))
            best = max(best, score(FLUSH, top[sm[fs]][:5]))
        quads, trips, pairs = [], [], []
        for r in range(12, -1, -1):
            n = rc[r]
            if n == 4: quads.append(r)
            elif n == 3: trips.append(r)
            elif n == 2: pairs.append(r)
        if quads:
            q = quads[0]
            best = max(best, score(QUADS, [q] + [r for r in top[mask] if r != q][:1]))
        if trips and (len(trips) > 1 or pairs):
            second = max(trips[1] if len(trips) > 1 else -1, pairs[0] if pairs else -1)
            best = max(best, score(FULL_HOUSE, [trips[0], second]))
        st = sh[mask]
        if st >= 0:
            best = max(best, score(STRAIGHT, [st]))
        if trips:
            t = trips[0]
            best = max(best, score(TRIPS, [t] + [r for r in top[mask] if r != t][:2]))
        if len(pairs) >= 2:
            a, b = pairs[0], pairs[1]
            best = max(best, score(TWO_PAIR, [a, b] + [r for r in top[mask] if r != a and r != b][:1]))
        if pairs:
            p = pairs[0]
            best = max(best, score(PAIR, [p] + [r for r in top[mask] if r != p][:3]))
        if best < 0:
            best = score(HIGH, top[mask][:5])
        return best

    return ev


STANDARD_ORDER = list(range(9))
WHEEL = (0x100F, 3)                      # A-2-3-4-5, scored as 5-high
SD_ORDER = [HIGH, PAIR, TWO_PAIR, STRAIGHT, TRIPS, FULL_HOUSE, FLUSH, QUADS, STRAIGHT_FLUSH]
SD_WHEEL = ((1 << 12) | (0b1111 << 4), 3)  # A-6-7-8-9, lowest straight (below 6-T)

_PRIMES = [2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41]


class _FiveTable:
    """Exact 5-card scores by lookup: product of rank primes, plus a flush flag.
    About 1 us per hand in Python, so Omaha's 60 (or 100) combinations stay fast."""

    def __init__(self, ev):
        self.plain, self.flush = {}, {}
        for ranks in combinations(range(13), 5):          # distinct ranks: flush or not
            key = 1
            for r in ranks:
                key *= _PRIMES[r]
            self.flush[key] = ev([r for r in ranks])          # all spades
            self.plain[key] = ev([r + 13 * (i % 2) for i, r in enumerate(ranks)])
        from itertools import combinations_with_replacement as cwr
        for ranks in cwr(range(13), 5):                   # with pairs: never a flush
            cnt = [ranks.count(r) for r in set(ranks)]
            if len(set(ranks)) == 5 or max(cnt) > 4:
                continue
            key = 1
            seen = {}
            cards = []
            for r in ranks:
                key *= _PRIMES[r]
                k = seen.get(r, 0)
                seen[r] = k + 1
                cards.append(r + 13 * k)
            self.plain[key] = ev(cards)


def _parts(cards, k):
    """(prime product, suit or -1 if mixed) for every k-subset."""
    out = []
    for sub in combinations(cards, k):
        key = 1
        s = sub[0] // 13
        for c in sub:
            key *= _PRIMES[c % 13]
            if c // 13 != s:
                s = -1
        out.append((key, s))
    return out


# --------------------------------------------------------------- low (8 or better)
_LOW_RANK = {12: 1, 0: 2, 1: 3, 2: 4, 3: 5, 4: 6, 5: 7, 6: 8}   # ace plays low


def _low_value(vals):
    """vals: 5 distinct low values (1..8). Higher result = better low."""
    v = sorted(vals, reverse=True)
    code = 0
    for x in v:
        code = code * 9 + x
    return 9 ** 5 - code


def low_name(lo):
    if lo is None:
        return "NO LOW"
    code = 9 ** 5 - lo
    v = []
    for _ in range(5):
        v.append(code % 9)
        code //= 9
    return "-".join("A" if x == 1 else str(x) for x in reversed(v)) + " LOW"


# --------------------------------------------------------------- variants
@dataclass(frozen=True)
class Variant:
    name: str
    title: str
    hole: int = 2
    min_rank: int = 0            # 0 = full deck, 4 = short deck (6 and up)
    omaha: bool = False          # exactly 2 hole + 3 board
    order: tuple = tuple(STANDARD_ORDER)
    wheel: tuple = WHEEL
    pot_limit: bool = False
    hilo: bool = False

    @property
    def deck(self):
        return [c for c in range(52) if c % 13 >= self.min_rank]

    def cat(self, score):
        return self.order[score // P5]

    def hand_name(self, score):
        c = self.cat(score)
        if c == STRAIGHT_FLUSH and (score // 13 ** 4) % 13 == 12:
            return "ROYAL FLUSH"
        return CATEGORIES[c]


class _Engine:
    """Evaluators for one variant (built once per variant, then cached)."""

    def __init__(self, v):
        self.v = v
        if v.order == tuple(STANDARD_ORDER) and v.wheel == WHEEL:
            self.any_eval = _holdem_eval
        else:
            self.any_eval = make_evaluator(list(v.order), v.wheel)
        if v.omaha:
            self.five = _FiveTable(make_evaluator(list(v.order), v.wheel))

    def hi(self, hole, board):
        if not self.v.omaha:
            return self.any_eval(list(hole) + list(board))
        if len(board) < 3:                      # preflop: score the hole cards alone
            return self.any_eval(list(hole))
        plain, flush = self.five.plain, self.five.flush
        hp, bp = _parts(hole, 2), _parts(board, 3)
        best = -1
        for hk, hs in hp:
            for bk, bs in bp:
                if hs >= 0 and hs == bs:
                    s = flush[hk * bk]
                else:
                    s = plain[hk * bk]
                if s > best:
                    best = s
        return best

    def lo(self, hole, board):
        if not self.v.hilo or len(board) < 3:
            return None
        if self.v.omaha:
            hv = {_LOW_RANK[c % 13] for c in hole if c % 13 in _LOW_RANK}
            bv = {_LOW_RANK[c % 13] for c in board if c % 13 in _LOW_RANK}
            best = None
            for h in combinations(sorted(hv), 2):
                rest = bv - set(h)
                if len(rest) < 3:
                    continue
                low3 = sorted(rest)[:3]          # lowest 3 board values make the best low
                val = _low_value(list(h) + low3)
                if best is None or val > best:
                    best = val
            return best
        vals = sorted({_LOW_RANK[c % 13] for c in list(hole) + list(board) if c % 13 in _LOW_RANK})
        return _low_value(vals[:5]) if len(vals) >= 5 else None


VARIANTS = {
    "holdem": Variant("holdem", "NO-LIMIT HOLD'EM"),
    "shortdeck": Variant("shortdeck", "SHORT DECK HOLD'EM", min_rank=4,
                         order=tuple(SD_ORDER), wheel=SD_WHEEL),
    "omaha": Variant("omaha", "POT-LIMIT OMAHA", hole=4, omaha=True, pot_limit=True),
    "omaha-nl": Variant("omaha-nl", "NO-LIMIT OMAHA", hole=4, omaha=True),
    "omaha5": Variant("omaha5", "5-CARD PLO", hole=5, omaha=True, pot_limit=True),
    "omaha8": Variant("omaha8", "PLO HI-LO 8", hole=4, omaha=True, pot_limit=True, hilo=True),
    "pineapple": Variant("pineapple", "3-CARD HOLD'EM", hole=3),
}
ALIASES = {"nlhe": "holdem", "holdem": "holdem", "6plus": "shortdeck", "short": "shortdeck",
           "plo": "omaha", "plo4": "omaha", "nlo": "omaha-nl", "plo5": "omaha5",
           "plo8": "omaha8", "o8": "omaha8", "omaha-hilo": "omaha8"}
_ENGINES = {}


def get(name):
    """Variant by name (or alias); also accepts a Variant."""
    if isinstance(name, Variant):
        return name
    name = ALIASES.get(name, name)
    return VARIANTS[name]


def engine(name):
    v = get(name)
    e = _ENGINES.get(v.name)
    if e is None:
        e = _ENGINES[v.name] = _Engine(v)
    return e


def hi(name, hole, board):
    return engine(name).hi(hole, board)


def lo(name, hole, board):
    return engine(name).lo(hole, board)


def schedule(spec, every=8):
    """'omaha' -> always omaha; 'mixed:holdem,omaha' -> rotate every `every` hands.
    Returns f(hand_index) -> variant name."""
    if not spec.startswith("mixed"):
        name = get(spec).name
        return lambda h: name
    names = [get(x).name for x in spec.split(":", 1)[1].split(",")] if ":" in spec else \
        ["holdem", "omaha", "shortdeck"]
    return lambda h: names[(h // every) % len(names)]
