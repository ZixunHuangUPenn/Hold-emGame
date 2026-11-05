"""Local table viewer: watch agents play, or take a seat and play against them.

  python -m viz.server            then open http://127.0.0.1:8765
  python -m viz.server --port 9000

Pure standard library. The game runs in a background thread using the same
engine as eval/ (engine.tournament.run_table); the page polls /api/state.
"""
import argparse, json, os, queue, random, threading, time
from collections import deque
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

from engine.cards import RANKS, SUITS
from engine.protocol import Action, ActionType
from engine.tournament import TournamentConfig, run_table
from agents.base import Agent
from agents.registry import BOTS, LEAD

STATIC = os.path.join(os.path.dirname(__file__), "static")
POINTS = {6: [100, 60, 40, 25, 10, 0], 8: [100, 60, 40, 30, 20, 10, 5, 0]}
# ms at 1x speed after each kind of update
DELAY = {"blinds": 350, "deal": 650, "ask": 280, "action": 650, "street": 900,
         "showdown": 1400, "win": 2400, "eliminated": 1200}


def card(c):
    return RANKS[c % 13] + SUITS[c // 13]


class StopGame(BaseException):
    """Raised inside the game thread to end it (BaseException so the engine's
    `except Exception` around bot calls does not swallow it)."""


class HumanAgent(Agent):
    name = "you"
    human = True

    def __init__(self):
        self.q = queue.Queue()

    def act(self, obs):
        a = self.q.get()
        if a is None:
            raise StopGame
        return a


class Game:
    def __init__(self, n=8, mode="watch", lineup=None, human_seat=0, speed=1.0,
                 show_all=True, seed=None):
        self.n, self.mode, self.speed, self.show_all = n, mode, speed, show_all
        self.human_seat = human_seat if mode == "play" else None
        default = [LEAD, "tag", "station", "maniac", "nit", "pushfold", "monte", "tag"]
        self.lineup = (lineup or default)[:n]
        while len(self.lineup) < n:
            self.lineup.append("tag")
        self.names = []
        count = {}
        for i, b in enumerate(self.lineup):
            if i == self.human_seat:
                self.names.append("YOU")
                continue
            count[b] = count.get(b, 0) + 1
            self.names.append(b.upper() + (f"-{count[b]}" if self.lineup.count(b) > 1 else ""))
        self.rng = random.Random(seed)
        self.lock = threading.Lock()
        self.version = 0
        self.id = f"{time.time():.3f}"
        self.paused = False
        self.stopped = False
        self.log = deque(maxlen=400)
        self.last = [None] * n
        self.revealed = set()
        self.winners = []
        self.eliminated = {}
        self.results = None
        self.request = None
        self.raw = None
        self.human = None
        self.thread = None
        self.error = None

    # ----------------------------------------------------------- lifecycle
    def start(self):
        agents = []
        for i, b in enumerate(self.lineup):
            if i == self.human_seat:
                self.human = HumanAgent()
                agents.append(self.human)
            else:
                agents.append(BOTS[b]())
        self.thread = threading.Thread(target=self._run, args=(agents,), daemon=True)
        self.thread.start()

    def stop(self):
        self.stopped = True
        if self.human:
            self.human.q.put(None)

    def _run(self, agents):
        cfg = TournamentConfig(n_seats=self.n, points=POINTS[self.n])
        try:
            run_table(agents, cfg, self.rng, log=self._log, on_update=self._update)
        except StopGame:
            return
        except Exception as e:  # show engine errors in the page instead of dying silently
            import traceback
            self.error = traceback.format_exc()
            self._bump()

    # ----------------------------------------------------------- engine hooks
    def _log(self, frm, to, text):
        if frm == "--":
            self.log.append(f"──── {text}")
        else:
            self.log.append(f"{frm:>3s} → {to:<3s} {text}")

    def _wait(self, ms):
        end = time.time() + ms / 1000
        while True:
            if self.stopped:
                raise StopGame
            if self.paused:
                time.sleep(0.05)
                end = time.time() + ms / 1000
                continue
            left = end - time.time()
            if left <= 0:
                return
            time.sleep(min(left, 0.05))

    def _update(self, kind, d):
        if self.stopped:
            raise StopGame
        with self.lock:
            if kind == "eliminated":
                self.eliminated[d["seat"]] = d
            elif kind == "finished":
                self.results = d
                self.request = None
            else:
                if kind == "blinds":
                    self.last = [None] * self.n
                    self.revealed = set()
                    self.winners = []
                if kind == "street":
                    # keep folds and all-ins visible, clear the rest (as on TV)
                    self.last = [l if l and l["code"] in "FA" else None for l in self.last]
                if kind == "action":
                    self.last[d["actor"]] = d["action"]
                if kind in ("showdown", "win") and d.get("showdown"):
                    self.revealed = set(int(k) for k in d["showdown"])
                if kind == "win":
                    self.winners = d["winners"]
                self.request = d.get("request") if kind == "ask" and d["actor"] == self.human_seat else None
                self.raw = (kind, d)
            self.version += 1
        if kind == "ask" and d.get("actor") == self.human_seat:
            return                       # the human agent blocks on its own
        if kind == "finished":
            return
        human_out = self.human_seat is not None and self.raw and \
            self.raw[1]["stacks"][self.human_seat] == 0 and self.human_seat in self.eliminated
        speed = self.speed * (4 if human_out else 1)
        self._wait(DELAY.get(kind, 300) / max(speed, 0.05))

    def _bump(self):
        with self.lock:
            self.version += 1

    # ----------------------------------------------------------- page state
    def _visible_log(self):
        """In play mode the trace must not leak other seats' hole cards."""
        lines = list(self.log)[-160:]
        if self.mode == "watch" and self.show_all:
            return lines
        me = f"S{self.human_seat + 1}" if self.human_seat is not None else None
        out = []
        for l in lines:
            parts = l.split()
            if len(parts) >= 4 and parts[0] == "D" and parts[3] == "DEAL" and parts[2] != me:
                l = f"{parts[0]:>3s} → {parts[2]:<3s} DEAL ?? ??"
            out.append(l)
        return out

    def state(self):
        with self.lock:
            kind, d = self.raw if self.raw else ("none", None)
            cfg = TournamentConfig()
            seats = []
            for i in range(self.n):
                s = {"name": self.names[i], "bot": "you" if i == self.human_seat else self.lineup[i],
                     "is_human": i == self.human_seat, "stack": 2000, "bet": 0, "folded": False,
                     "dealt": False, "cards": None, "has_cards": False, "last": self.last[i],
                     "winner": None, "out": i in self.eliminated,
                     "place": self.eliminated.get(i, {}).get("place")}
                if d:
                    s["stack"], s["bet"] = d["stacks"][i], d["bets"][i]
                    s["folded"], s["dealt"] = d["folded"][i], d["dealt"][i]
                    has = bool(d["holes"][i]) and d["dealt"][i] and not d["folded"][i]
                    s["has_cards"] = has
                    visible = (self.mode == "watch" and self.show_all) or i == self.human_seat \
                        or i in self.revealed
                    if d["holes"][i] and visible and (has or i == self.human_seat):
                        s["cards"] = [card(c) for c in d["holes"][i]]
                for w in self.winners:
                    if w["seat"] == i:
                        s["winner"] = w
                seats.append(s)
            out = {
                "id": self.id, "version": self.version, "mode": self.mode, "n": self.n,
                "human_seat": self.human_seat, "paused": self.paused, "speed": self.speed,
                "show_all": self.show_all, "kind": kind, "seats": seats,
                "log": self._visible_log(), "request": self.request, "error": self.error,
                "hands_per_level": cfg.hands_per_level, "max_hands": cfg.max_hands,
                "blinds": cfg.blinds, "results": None,
            }
            if d:
                out.update({
                    "hand_no": d["hand_no"], "level": d["level"], "sb": d["sb"], "bb": d["bb"],
                    "street": d["street"], "board": [card(c) for c in d["board"]], "pot": d["pot"],
                    "dealer": d["dealer"], "sb_seat": d["sb_seat"], "bb_seat": d["bb_seat"],
                    "actor": d.get("actor") if kind in ("ask", "action") else None,
                    "hand_names": d.get("hand_names"),
                })
            if self.results:
                r = self.results
                out["results"] = sorted(
                    [{"seat": i, "name": self.names[i], "place": r["place"][i], "points": r["points"][i],
                      "stack": r["stacks"][i]} for i in range(self.n)], key=lambda x: x["place"])
            return out


GAME = {"g": None}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def do_GET(self):
        path = self.path.split("?")[0]
        if path in ("/", "/index.html"):
            with open(os.path.join(STATIC, "index.html"), "rb") as f:
                return self._send(200, f.read(), "text/html; charset=utf-8")
        if path == "/api/bots":
            return self._send(200, sorted(BOTS))
        if path == "/api/state":
            g = GAME["g"]
            return self._send(200, g.state() if g else {"id": None})
        self._send(404, {"error": "not found"})

    def do_POST(self):
        path = self.path.split("?")[0]
        b = self._body()
        g = GAME["g"]
        if path == "/api/new":
            if g:
                g.stop()
            n = 6 if int(b.get("n", 8)) == 6 else 8
            lineup = [x if x in BOTS else "tag" for x in b.get("lineup", [])] or None
            g = Game(n=n, mode=b.get("mode", "watch"), lineup=lineup,
                     human_seat=int(b.get("human_seat", 0)) % n, speed=float(b.get("speed", 1)),
                     show_all=bool(b.get("show_all", True)))
            GAME["g"] = g
            g.start()
            return self._send(200, {"ok": True, "id": g.id})
        if not g:
            return self._send(400, {"error": "no game"})
        if path == "/api/action":
            if g.human is None or g.request is None:
                return self._send(409, {"error": "not your turn"})
            try:
                t = ActionType(b.get("type"))
            except ValueError:
                return self._send(400, {"error": "bad action"})
            with g.lock:
                g.request = None
            g.human.q.put(Action(t, int(b.get("amount") or 0)))
            return self._send(200, {"ok": True})
        if path == "/api/control":
            if "paused" in b:
                g.paused = bool(b["paused"])
            if "speed" in b:
                g.speed = max(0.1, float(b["speed"]))
            if "show_all" in b:
                g.show_all = bool(b["show_all"])
            g._bump()
            return self._send(200, {"ok": True})
        self._send(404, {"error": "not found"})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--host", default="127.0.0.1")
    a = ap.parse_args()
    srv = ThreadingHTTPServer((a.host, a.port), Handler)
    print(f"Poker table viewer: http://{a.host}:{a.port}   (Ctrl+C to stop)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
