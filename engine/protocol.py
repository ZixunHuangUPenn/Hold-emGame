"""Messages between the dealer and the bots.

Mirrors the site's Exhibit D message trace:
  bc  dealer -> ALL      broadcast (new hand, blinds, board, actions, showdown, pot awarded)
  dl  dealer -> one bot  private (hole cards, uncalled bet returned)
  rq  dealer -> one bot  action request ("ACTION? TO CALL 100, POT 300")  -> Agent.act(obs)
  rp  bot -> dealer      reply (an Action), with think time
  sep                    end of hand

Action codes follow the exhibits: b blind, X check, C call, B bet, R raise (to),
A all-in, F fold, W win. Bet/raise amounts are "raise TO" (total this street).

The official Agent interface is only revealed at the event. Everything here is
OUR internal format; at the event, write a thin adapter (agents/adapter.py)
that converts the official objects to and from these.
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Tuple


class ActionType(str, Enum):
    FOLD = "F"
    CHECK = "X"
    CALL = "C"
    BET = "B"
    RAISE = "R"
    ALL_IN = "A"


@dataclass(frozen=True)
class Action:
    type: ActionType
    amount: int = 0          # for BET / RAISE: total bet this street ("raise to")

    def __str__(self):
        if self.type in (ActionType.BET, ActionType.RAISE):
            return f"{self.type.name} TO {self.amount}"
        return self.type.name


FOLD = Action(ActionType.FOLD)
CHECK = Action(ActionType.CHECK)
CALL = Action(ActionType.CALL)
ALL_IN = Action(ActionType.ALL_IN)
def RAISE_TO(x): return Action(ActionType.RAISE, int(x))
def BET_TO(x): return Action(ActionType.BET, int(x))


# Event types (Event.type)
NEW_HAND = "new_hand"    # bc: dealer, sb_seat, bb_seat, sb, bb, stacks
BLIND = "blind"          # bc: seat, amount
DEAL = "deal"            # dl: cards (only sent to the owner)
ACTION = "action"        # bc: seat, code (F/X/C/B/R/A), amount (raise-to or call amount), street
STREET = "street"        # bc: street (1 flop, 2 turn, 3 river), board
REFUND = "refund"        # dl: seat, amount (uncalled bet returned)
SHOWDOWN = "showdown"    # bc: hands {seat: cards}
WIN = "win"              # bc: seat, amount, hand name
END_HAND = "end_hand"    # sep: stacks
ELIMINATED = "eliminated"  # bc: seat, place


@dataclass
class Event:
    type: str
    seat: Optional[int] = None
    amount: int = 0
    code: str = ""
    street: int = 0
    cards: Tuple[int, ...] = ()
    board: Tuple[int, ...] = ()
    hands: Optional[dict] = None
    stacks: Optional[List[int]] = None
    text: str = ""


STREET_NAMES = ["PREFLOP", "FLOP", "TURN", "RIVER"]


@dataclass
class Observation:
    """Everything a bot may see when the dealer asks it to act."""
    hand_no: int
    seat: int
    hole: Tuple[int, ...]
    board: Tuple[int, ...]
    street: int                  # 0 preflop .. 3 river
    pot: int                     # all chips committed this hand
    stacks: List[int]            # chips behind, per seat (0 = busted or all-in)
    bets: List[int]              # chips put in on this street, per seat
    in_hand: List[bool]          # not folded and was dealt in
    dealer: int
    sb: int
    bb: int
    to_call: int
    min_raise_to: int            # 0 if raising is not allowed
    max_raise_to: int            # = my bet + my stack (all-in)
    legal: Tuple[ActionType, ...]
    history: List[Event]         # this hand's public events so far (plus my deal)
    level: int                   # blind level index
    hands_played: int            # at this table
    players_left: int            # seats with chips at the start of this hand
    n_seats: int

    @property
    def my_stack(self): return self.stacks[self.seat]
    @property
    def my_bet(self): return self.bets[self.seat]
