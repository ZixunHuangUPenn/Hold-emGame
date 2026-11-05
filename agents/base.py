"""Agent interface (our internal version; adapt to the official one at the event).

The dealer calls:
  reset(seat, n_seats)   at the start of every table (bots are reset per table)
  on_event(event)        for every broadcast, and your private deal / refund
  act(obs) -> Action     when it is your turn; must return within 1 ms
"""
from engine.protocol import Action, ActionType, CHECK, FOLD


class Agent:
    name = "base"

    def reset(self, seat, n_seats):
        self.seat = seat
        self.n_seats = n_seats

    def on_event(self, event):
        pass

    def act(self, obs) -> Action:
        return CHECK if ActionType.CHECK in obs.legal else FOLD


def safe_default(obs):
    """What the dealer does on a timeout: check if possible, else fold."""
    return CHECK if ActionType.CHECK in obs.legal else FOLD
