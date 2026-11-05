"""Cards and hand evaluation.

Card encoding follows the site's exhibits: an int 0..51, rank = c % 13
(0 = deuce, 12 = ace), suit = c // 13.

evaluate(cards) works for 1..7 cards and returns an int: higher is better.
category(score) gives 0 (high card) .. 8 (straight flush).
"""
RANKS = "23456789TJQKA"
SUITS = "shdc"
SUIT_GLYPH = "♠♥♦♣"
P5 = 13 ** 5
CATEGORIES = ["HIGH CARD", "PAIR", "TWO PAIR", "THREE OF A KIND", "STRAIGHT",
              "FLUSH", "FULL HOUSE", "FOUR OF A KIND", "STRAIGHT FLUSH"]


def rank(c): return c % 13
def suit(c): return c // 13
def card_str(c): return RANKS[c % 13] + SUIT_GLYPH[c // 13]
def cards_str(cs): return " ".join(card_str(c) for c in cs)


def parse(s):
    """'As' -> 12 + 0*13. Accepts 'T' or '10' for ten."""
    s = s.replace("10", "T")
    return RANKS.index(s[0].upper()) + 13 * SUITS.index(s[1].lower())


# --- lookup tables -------------------------------------------------------
def _straight_high(m):
    for r in range(12, 3, -1):
        if (m >> (r - 4)) & 31 == 31:
            return r
    return 3 if m & 0x100F == 0x100F else -1   # wheel A-2-3-4-5


STRAIGHT_HIGH = [_straight_high(m) for m in range(1 << 13)]
TOP_RANKS = [[r for r in range(12, -1, -1) if (m >> r) & 1] for m in range(1 << 13)]


def _score(cat, ks):
    s = cat
    for i in range(5):
        s = s * 13 + (ks[i] if i < len(ks) else 0)
    return s


def evaluate(cards):
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
    fs = -1
    for s in range(4):
        if sc[s] >= 5:
            fs = s
    if fs >= 0:
        h = STRAIGHT_HIGH[sm[fs]]
        if h >= 0:
            return _score(8, [h])
    quads = []; trips = []; pairs = []
    for r in range(12, -1, -1):
        n = rc[r]
        if n == 4: quads.append(r)
        elif n == 3: trips.append(r)
        elif n == 2: pairs.append(r)
    if quads:
        q = quads[0]
        return _score(7, [q] + [r for r in TOP_RANKS[mask] if r != q][:1])
    if trips and (len(trips) > 1 or pairs):
        second = max(trips[1] if len(trips) > 1 else -1, pairs[0] if pairs else -1)
        return _score(6, [trips[0], second])
    if fs >= 0:
        return _score(5, TOP_RANKS[sm[fs]][:5])
    st = STRAIGHT_HIGH[mask]
    if st >= 0:
        return _score(4, [st])
    if trips:
        t = trips[0]
        return _score(3, [t] + [r for r in TOP_RANKS[mask] if r != t][:2])
    if len(pairs) >= 2:
        a, b = pairs[0], pairs[1]
        return _score(2, [a, b] + [r for r in TOP_RANKS[mask] if r != a and r != b][:1])
    if pairs:
        p = pairs[0]
        return _score(1, [p] + [r for r in TOP_RANKS[mask] if r != p][:3])
    return _score(0, TOP_RANKS[mask][:5])


def category(score):
    return score // P5


def hand_name(score):
    cat = category(score)
    if cat == 8 and (score // 13 ** 4) % 13 == 12:
        return "ROYAL FLUSH"
    return CATEGORIES[cat]
