"""Every bot by name.

agents/ours/ is private and kept out of the public repository (.gitignore).
Without it, everything runs with the baselines only and "tag" takes its seat.
"""
from agents.baselines import REGISTRY

BOTS = dict(REGISTRY)
try:
    from agents.ours.agent import OurAgent
except ModuleNotFoundError as e:
    if e.name not in ("agents.ours", "agents.ours.agent"):
        raise                       # ours exists but is broken: do not hide that
    OurAgent = None
else:
    BOTS["ours"] = OurAgent

LEAD = "ours" if OurAgent else "tag"   # the seat our bot normally takes
