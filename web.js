// Stands in for viz/server.py on static hosting: answers the page's /api/* calls
// from a Python worker and plays the returned frames back on a timer.
(() => {
  const WINDOW = 200, LOW_WATER = 50;
  const worker = new Worker(window.POKER_WORKER_URL);
  const pending = new Map();
  let nextRid = 0;

  const overlay = document.createElement("div");
  overlay.style.cssText = "position:fixed;inset:0;z-index:9999;display:flex;align-items:center;" +
    "justify-content:center;text-align:center;padding:24px;background:#07090c;color:#e8edf3;" +
    "font:16px/1.6 system-ui,sans-serif";
  overlay.textContent = "Loading the Python poker engine (about 10 MB on the first visit)...";
  document.addEventListener("DOMContentLoaded", () => document.body.appendChild(overlay));

  worker.onmessage = ({ data }) => {
    const p = pending.get(data.rid);
    pending.delete(data.rid);
    if (data.error) p.reject(new Error(data.error));
    else p.resolve(JSON.parse(data.result));
  };
  const send = (message) => new Promise((resolve, reject) => {
    const rid = nextRid++;
    pending.set(rid, { resolve, reject });
    worker.postMessage({ rid, ...message });
  });
  const call = (request) => send({ request });

  const ready = send({ boot: window.POKER_ZIP_URL, request: { method: "bots" } }).then(
    (bots) => { overlay.remove(); return bots; },
    (e) => { overlay.textContent = `Could not load the poker engine: ${e.message}`; throw e; });

  let cur = null, curFrame = 0, queue = [], nextFrame = 0, exhausted = false;
  let loading = false, token = 0, timer = null, version = 0;
  let paused = false, speed = 1, showAll = true, errorText = null;

  function restartFrom(frame) {
    token++;
    queue = []; nextFrame = frame; exhausted = false; loading = false;
    clearTimeout(timer); timer = null;
  }

  async function fetchMore() {
    if (loading || exhausted) return;
    loading = true;
    const t = token;
    try {
      const r = await call({ method: "frames", start: nextFrame, count: WINDOW });
      if (t !== token) return;
      queue.push(...r.frames);
      nextFrame += r.frames.length;
      exhausted = r.status !== "more";
      if (r.error) { errorText = r.error; version++; }
    } catch (e) {
      if (t !== token) return;
      errorText = String(e); exhausted = true; version++;
    }
    loading = false;
    kick();
  }

  function kick() { if (timer === null) tick(); }

  function tick() {
    timer = null;
    if (paused || (cur && cur.request)) return;
    if (!queue.length) { fetchMore(); return; }
    const f = queue.shift();
    cur = f.state; curFrame = f.state.version; version++;
    if (queue.length < LOW_WATER) fetchMore();
    if (!cur.request) timer = setTimeout(tick, f.ms / Math.max(speed, 0.05));
  }

  window.staticApi = async (path, body) => {
    if (path === "/api/bots") return ready;
    await ready;
    if (path === "/api/state") {
      if (!cur) return { id: null };
      return { ...cur, version, paused, speed, show_all: showAll, error: errorText || cur.error };
    }
    if (path === "/api/new") {
      restartFrom(0);
      cur = null; errorText = null; paused = false; showAll = true;
      speed = body.speed || speed;
      const r = await call({ method: "new", args: { n: body.n, mode: body.mode, lineup: body.lineup,
        human_seat: body.human_seat, show_all: true } });
      fetchMore();
      return r;
    }
    if (path === "/api/action") {
      if (!cur || !cur.request) return { error: "not your turn" };
      cur = { ...cur, request: null }; version++;
      exhausted = false;
      await call({ method: "action", type: body.type, amount: body.amount });
      fetchMore();
      return { ok: true };
    }
    if (path === "/api/control") {
      if ("paused" in body) { paused = !!body.paused; if (!paused) kick(); }
      if ("speed" in body) speed = Math.max(0.1, +body.speed);
      if ("show_all" in body && cur && cur.mode === "watch") {
        showAll = !!body.show_all;
        restartFrom(curFrame);
        await call({ method: "show_all", value: showAll });
        fetchMore();
      }
      version++;
      return { ok: true };
    }
    return { error: "not found" };
  };
})();
