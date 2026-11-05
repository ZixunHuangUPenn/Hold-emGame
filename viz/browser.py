"""Backend for the static site (GitHub Pages), run in the browser by Pyodide.

The page normally talks to viz/server.py, which blocks a thread until the human
acts. Pyodide has no threads, so here every request simulates the table from
hand one with fixed seeds and the recorded human actions, and returns only the
frames asked for. A whole table takes a fraction of a second, so this stays fast.

The dealer and agents are the same code as eval/. The 1 ms limit is off: the
engine runs on WebAssembly here, so think times do not match the event.
"""
import itertools, json, random, time, traceback

from agents.base import Agent
from engine.protocol import Action, ActionType
from engine.tournament import TournamentConfig, run_table
from agents.registry import LEAD
from viz.server import BOTS, POINTS, Game


class _WindowFull(BaseException):
    """Enough frames for this request. BaseException so the engine's
    `except Exception` around bot calls does not swallow it."""


class _NeedAction(BaseException):
    """The recorded human actions ran out."""


class _ReplayHuman(Agent):
    name = "you"
    human = True

    def __init__(self, actions):
        self.actions = iter(actions)

    def act(self, obs):
        try:
            return next(self.actions)
        except StopIteration:
            raise _NeedAction from None


class _SimGame(Game):
    """Game that records page states instead of sleeping between updates."""

    def __init__(self, session, start, count):
        s = session
        super().__init__(n=s.n, mode=s.mode, lineup=list(s.lineup), human_seat=s.human_seat,
                         speed=1.0, show_all=s.show_all, seed=s.seed)
        self.id, self.start_frame, self.count = s.id, start, count
        self.frame, self.frames, self._ms = 0, [], 0

    def _wait(self, ms):
        self._ms = ms

    def _update(self, kind, d):
        self._ms = 0
        super()._update(kind, d)
        i, self.frame = self.frame, self.frame + 1
        if i >= self.start_frame:
            st = self.state()
            st["version"] = i
            self.frames.append({"state": st, "ms": self._ms})
            if len(self.frames) >= self.count:
                raise _WindowFull


class Session:
    def __init__(self, n=8, mode="watch", lineup=None, human_seat=0, show_all=True, seed=None):
        self.n = 6 if int(n) == 6 else 8
        self.mode = "play" if mode == "play" else "watch"
        self.human_seat = int(human_seat) % self.n
        self.show_all = bool(show_all)
        self.seed = random.randrange(2 ** 31) if seed is None else seed
        self.id = f"{time.time():.3f}"
        self.actions = []
        default = [LEAD, "tag", "station", "maniac", "nit", "pushfold", "monte", "tag"]
        chosen = [x if x in BOTS else "tag" for x in (lineup or [])] or default
        self.lineup = (chosen + ["tag"] * self.n)[:self.n]

    def frames(self, start, count):
        g = _SimGame(self, start, count)
        agents = [_ReplayHuman(self.actions) if i == g.human_seat else BOTS[b]()
                  for i, b in enumerate(g.lineup)]
        cfg = TournamentConfig(n_seats=self.n, points=POINTS[self.n], time_limit_ms=None)
        # Bots seed themselves with random.Random(); replays must reproduce them.
        seeds, real = itertools.count(self.seed + 1), random.Random
        random.Random = lambda x=None: real(next(seeds) if x is None else x)
        status, error = "done", None
        try:
            run_table(agents, cfg, g.rng, log=g._log, on_update=g._update)
        except _WindowFull:
            status = "more"
        except _NeedAction:
            status = "human"
        except Exception:
            status, error = "error", traceback.format_exc()
        finally:
            random.Random = real
        return {"frames": g.frames, "status": status, "error": error}


_session = None


def handle(request):
    """JSON string in, JSON string out: the only entry point the page uses."""
    global _session
    q = json.loads(request)
    m = q["method"]
    if m == "bots":
        out = sorted(BOTS)
    elif m == "new":
        _session = Session(**q["args"])
        out = {"ok": True, "id": _session.id}
    elif m == "frames":
        out = _session.frames(q["start"], q["count"])
    elif m == "action":
        _session.actions.append(Action(ActionType(q["type"]), int(q.get("amount") or 0)))
        out = {"ok": True}
    elif m == "show_all":
        _session.show_all = bool(q["value"])
        out = {"ok": True}
    else:
        raise ValueError(f"unknown method {m}")
    return json.dumps(out)
