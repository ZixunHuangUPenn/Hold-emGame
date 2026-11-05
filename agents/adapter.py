"""PLACEHOLDER: fill in at the event, once the official Agent interface is known.

The official starter kit gives an Agent template. This file should be the only
place that knows its format: convert the official game state into our
engine.protocol.Observation, call OurAgent.act(), convert our Action back.

Sketch:

    from agents.ours.agent import OurAgent
    from engine.protocol import Observation, Action, ActionType

    class OfficialBot(<official Agent base class>):
        def __init__(self):
            self.inner = OurAgent()
            self.inner.reset(seat=0, n=8)          # call again when a new table starts

        def <official callback for events>(self, msg):
            self.inner.on_event(to_our_event(msg))

        def <official act method>(self, state):
            obs = to_observation(state)            # map field by field
            a = self.inner.act(obs)
            return to_official_action(a, state)    # raise-to vs raise-by: check the docs!

Checklist at the event:
  - cards: what encoding? (ours: 0..51, rank = c % 13, suit = c // 13)
  - bet amounts: "raise to" or "raise by"?
  - is there an all-in action or just a max raise?
  - which seat am I, and how do I learn a new table started (bots are reset per table)?
  - wrap everything in try/except and return check/fold on any error
"""
