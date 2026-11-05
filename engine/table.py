"""The dealer: plays one hand of no-limit hold'em at an N-seat table.

Rules follow the site's Exhibit B engine plus the official rules:
  - blinds posted by the next live seats after the button (heads-up: button = SB,
    acts first preflop, last postflop)
  - a raise reopens the action for everyone else who can still act
    (simplification shared with the exhibit; short all-ins also reopen)
  - min raise = previous raise size (at least the big blind)
  - uncalled excess is returned first, then side pots by contribution level
  - a bot that throws or exceeds the time limit checks if it can, else folds
"""
import time
from dataclasses import dataclass, field
from .cards import evaluate, hand_name, cards_str, card_str
from .protocol import (Action, ActionType, Event, Observation, STREET_NAMES,
                       NEW_HAND, BLIND, DEAL, ACTION, STREET, REFUND, SHOWDOWN,
                       WIN, END_HAND)

AT = ActionType


@dataclass
class SeatStats:
    decisions: int = 0
    timeouts: int = 0
    errors: int = 0
    total_ms: float = 0.0
    max_ms: float = 0.0
    times: list = field(default_factory=list)   # sampled decision times (ms)

    def record(self, ms):
        self.decisions += 1
        self.total_ms += ms
        if ms > self.max_ms:
            self.max_ms = ms
        if len(self.times) < 20000:
            self.times.append(ms)


def _fmt(n): return f"{int(n):,}"


def play_hand(agents, stacks, dealer, sb_amt, bb_amt, rng, hand_no=1, level=0,
              time_limit_ms=1.0, stats=None, log=None, on_update=None):
    """Play one hand. Returns the new stacks list.

    agents: list of Agent (index = seat). Seats with stack 0 sit out.
    log: optional callable(from_, to, text) for an Exhibit-D style trace.
    on_update: optional callable(kind, snapshot) for live viewers (viz/server.py).
      kinds: blinds, deal, ask, action, street, showdown, win, end.
      Exceptions raised by on_update propagate (used to stop a game).
    Agents with attribute human=True are exempt from the time limit.
    """
    n = len(agents)
    stacks = list(stacks)
    dealt = [stacks[i] > 0 for i in range(n)]
    live_seats = [i for i in range(n) if dealt[i]]
    assert len(live_seats) >= 2
    stats = stats if stats is not None else [SeatStats() for _ in range(n)]

    folded = [not dealt[i] for i in range(n)]
    bet = [0] * n          # this street
    total = [0] * n        # this hand
    holes = [()] * n
    board = []
    history = []

    def nxt(i):
        j = (i + 1) % n
        while not dealt[j]:
            j = (j + 1) % n
        return j

    def say(frm, to, text):
        if log:
            log(frm, to, text)

    def emit(ev, to_all=True, only=None):
        if to_all:
            history.append(ev)
        targets = live_seats if only is None else [only]
        for i in targets:
            try:
                agents[i].on_event(ev)
            except Exception:
                stats[i].errors += 1

    def pay(i, a):
        a = min(a, stacks[i])
        stacks[i] -= a
        bet[i] += a
        total[i] += a
        return a

    def can_act(i): return dealt[i] and not folded[i] and stacks[i] > 0
    def live_count(): return sum(1 for i in range(n) if dealt[i] and not folded[i])
    def pot(): return sum(total)

    ctx = {"street": 0, "sb_seat": None, "bb_seat": None}

    def snap(kind, **extra):
        if on_update is None:
            return
        d = {"hand_no": hand_no, "level": level, "sb": sb_amt, "bb": bb_amt,
             "street": ctx["street"], "board": list(board), "pot": pot(), "dealer": dealer,
             "sb_seat": ctx["sb_seat"], "bb_seat": ctx["bb_seat"], "stacks": list(stacks),
             "bets": list(bet), "folded": list(folded), "dealt": list(dealt),
             "holes": [list(h) for h in holes]}
        d.update(extra)
        on_update(kind, d)

    # ---- blinds and deal
    if len(live_seats) == 2:
        sb_seat = dealer if dealt[dealer] else nxt(dealer)
    else:
        sb_seat = nxt(dealer)
    bb_seat = nxt(sb_seat)
    ctx["sb_seat"], ctx["bb_seat"] = sb_seat, bb_seat
    emit(Event(NEW_HAND, seat=dealer, stacks=list(stacks),
               text=f"NEW HAND {hand_no:06d}: S{sb_seat+1} SB {sb_amt}, S{bb_seat+1} BB {bb_amt}"))
    say("D", "ALL", history[-1].text)
    for s, amt in ((sb_seat, sb_amt), (bb_seat, bb_amt)):
        paid = pay(s, amt)
        emit(Event(BLIND, seat=s, amount=paid, code="b"))
    snap("blinds")

    deck = list(range(52))
    rng.shuffle(deck)
    order = []
    j = sb_seat
    for _ in range(len(live_seats)):
        order.append(j)
        j = nxt(j)
    for i in order:
        holes[i] = (deck.pop(), deck.pop())
        emit(Event(DEAL, seat=i, cards=holes[i]), to_all=False, only=i)
        say("D", f"S{i+1}", f"DEAL {cards_str(holes[i])}")
    snap("deal")

    # ---- betting
    def betting_round(street, first, cur, last_raise):
        queue = []
        j = first
        for _ in range(len(live_seats)):
            if can_act(j):
                queue.append(j)
            j = nxt(j)
        while queue and live_count() > 1:
            i = queue.pop(0)
            if not can_act(i):
                continue
            to_call = cur - bet[i]
            others = any(can_act(k) for k in range(n) if k != i)
            if not others and to_call <= 0:
                continue
            # legal actions
            can_raise = others and stacks[i] > to_call
            if to_call > 0:
                legal = (AT.FOLD, AT.CALL) + ((AT.RAISE, AT.ALL_IN) if can_raise else ())
            else:
                legal = (AT.CHECK,) + (((AT.RAISE if cur > 0 else AT.BET), AT.ALL_IN) if can_raise else ())
            max_to = bet[i] + stacks[i]
            min_to = min(cur + max(last_raise, bb_amt), max_to) if can_raise else 0
            obs = Observation(hand_no, i, holes[i], tuple(board), street, pot(), list(stacks),
                              list(bet), [dealt[k] and not folded[k] for k in range(n)],
                              dealer, sb_amt, bb_amt, min(to_call, stacks[i]), min_to, max_to,
                              legal, history, level, hand_no - 1, len(live_seats), n)
            ask = f"TO CALL {_fmt(min(to_call, stacks[i]))}" if to_call > 0 else \
                  ("CHECK OR RAISE" if cur > 0 else "CHECK OR BET")
            say("D", f"S{i+1}", f"ACTION? {ask}, POT {_fmt(pot())}")
            snap("ask", actor=i, request={"to_call": min(to_call, stacks[i]), "min_raise_to": min_to,
                                          "max_raise_to": max_to, "legal": [x.value for x in legal],
                                          "my_bet": bet[i]})
            human = getattr(agents[i], "human", False)

            # ask the bot, with the time limit
            t0 = time.perf_counter()
            try:
                act = agents[i].act(obs)
                ok = isinstance(act, Action)
            except Exception:
                act, ok = None, False
                stats[i].errors += 1
            ms = (time.perf_counter() - t0) * 1000
            stats[i].record(ms)
            if human:
                stats[i].times.pop() if stats[i].times else None
            if not ok or (not human and time_limit_ms is not None and ms > time_limit_ms):
                if ok:
                    stats[i].timeouts += 1
                act = Action(AT.CHECK if to_call <= 0 else AT.FOLD)

            # normalize to a legal move
            t = act.type
            if t == AT.FOLD and to_call <= 0:
                t = AT.CHECK
            elif t == AT.CHECK and to_call > 0:
                t = AT.FOLD
            elif t == AT.CALL and to_call <= 0:
                t = AT.CHECK
            raise_to = 0
            if t in (AT.BET, AT.RAISE, AT.ALL_IN):
                if not can_raise:
                    t = AT.CALL if to_call > 0 else AT.CHECK
                else:
                    raise_to = max_to if t == AT.ALL_IN else max(min_to, min(int(act.amount), max_to))

            # apply
            if t == AT.FOLD:
                folded[i] = True
                code, amt, text = "F", 0, "FOLD"
            elif t == AT.CHECK:
                code, amt, text = "X", 0, "CHECK"
            elif t == AT.CALL:
                amt = pay(i, to_call)
                code = "A" if stacks[i] == 0 else "C"
                text = ("ALL-IN " if code == "A" else "CALL ") + _fmt(amt)
            else:
                pay(i, raise_to - bet[i])
                amt = bet[i]
                if bet[i] > cur:
                    if bet[i] - cur >= last_raise:
                        last_raise = bet[i] - cur
                    cur = bet[i]
                    queue = []
                    j = nxt(i)
                    while j != i:
                        if can_act(j):
                            queue.append(j)
                        j = nxt(j)
                if stacks[i] == 0:
                    code, text = "A", f"ALL-IN {_fmt(amt)}"
                else:
                    code = "B" if t == AT.BET else "R"
                    text = ("BET " if code == "B" else "RAISE TO ") + _fmt(amt)
            say(f"S{i+1}", "D", f"{text}  [{ms:.3f} ms]")
            emit(Event(ACTION, seat=i, code=code, amount=amt, street=street, text=text))
            snap("action", actor=i, action={"code": code, "amount": amt, "text": text, "ms": ms})

    betting_round(0, nxt(bb_seat), bb_amt, bb_amt)
    for street, count in ((1, 3), (2, 1), (3, 1)):
        if live_count() < 2:
            break
        for k in range(n):
            bet[k] = 0
        deck.pop()  # burn
        for _ in range(count):
            board.append(deck.pop())
        name = STREET_NAMES[street]
        txt = f"{name} {cards_str(board)}" if count == 3 else \
              f"{name} {card_str(board[-1])}, BOARD {cards_str(board)}"
        emit(Event(STREET, street=street, board=tuple(board), text=txt))
        say("D", "ALL", txt)
        ctx["street"] = street
        snap("street")
        if sum(1 for k in range(n) if can_act(k)) > 1:
            betting_round(street, nxt(dealer), 0, bb_amt)

    # ---- settle: refund uncalled excess, then side pots
    contenders = [i for i in range(n) if dealt[i] and not folded[i]]
    by_total = sorted(range(n), key=lambda k: -total[k])
    excess = total[by_total[0]] - total[by_total[1]]
    if excess > 0:
        k = by_total[0]
        total[k] -= excess
        stacks[k] += excess
        emit(Event(REFUND, seat=k, amount=excess), to_all=False, only=k)
        say("D", f"S{k+1}", f"RETURN {_fmt(excess)} UNCALLED")

    scores = [-1] * n
    if len(contenders) > 1:
        for i in contenders:
            scores[i] = evaluate(list(holes[i]) + board)
        emit(Event(SHOWDOWN, hands={i: holes[i] for i in contenders}, board=tuple(board),
                   text="SHOWDOWN " + ", ".join(f"S{i+1}: {cards_str(holes[i])}" for i in contenders)))
        say("D", "ALL", history[-1].text)
        snap("showdown", showdown={i: list(holes[i]) for i in contenders},
             hand_names={i: hand_name(scores[i]) for i in contenders})

    won = [0] * n
    levels = sorted(set(t for t in total if t > 0))
    prev = 0
    for lv in levels:
        slice_ = sum(min(t, lv) - min(t, prev) for t in total)
        elig = [i for i in contenders if total[i] >= lv] or contenders
        best = max(scores[i] for i in elig)
        winners = [i for i in elig if scores[i] == best]
        share, odd = divmod(slice_, len(winners))
        for k, i in enumerate(winners):
            won[i] += share + (odd if k == 0 else 0)
        prev = lv
    winners = []
    for i in range(n):
        if won[i]:
            stacks[i] += won[i]
            what = hand_name(scores[i]) if len(contenders) > 1 else "UNCONTESTED"
            emit(Event(WIN, seat=i, amount=won[i], code="W", text=f"POT {_fmt(won[i])} TO S{i+1}, {what}"))
            say("D", "ALL", history[-1].text)
            winners.append({"seat": i, "amount": won[i], "hand": what})
    snap("win", winners=winners, showdown={i: list(holes[i]) for i in contenders} if len(contenders) > 1 else {})
    emit(Event(END_HAND, stacks=list(stacks), text=f"END HAND {hand_no:06d}"))
    say("--", "--", f"END HAND {hand_no:06d}: STACKS {stacks}")
    return stacks
