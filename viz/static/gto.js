// Preflop GTO helpers shared by the trainer (gto.html) and the table viewer (index.html).
//
// - Range charts (100bb, no ante, ~2.5x opens): approximations of published solver
//   output, written in the usual range notation. They are NOT solved here.
// - Push/fold: a real heads-up Nash solver (fictitious play) over the 169x169
//   all-in equity table precompute/hu_equity.json.
// - advise(state): preflop recommendation for the human seat in the table viewer.
(function (root) {
  "use strict";
  const R = "AKQJT98765432";                       // grid order: A first
  const RV = r => 12 - R.indexOf(r);                // A=12 .. 2=0

  // ---------------------------------------------------------------- hands
  const HANDS = [];                                 // 169 names, row-major 13x13
  for (let i = 0; i < 13; i++) for (let j = 0; j < 13; j++)
    HANDS.push(i === j ? R[i] + R[j] : j > i ? R[i] + R[j] + "s" : R[j] + R[i] + "o");
  const IDX = Object.fromEntries(HANDS.map((h, k) => [h, k]));
  const COMBOS = h => h.length === 2 ? 6 : h[2] === "s" ? 4 : 12;
  const TOTAL = 1326;

  // "Ah","Kd" -> "AKo"
  function handOf(cards) {
    let [a, b] = cards;
    if (RV(a[0]) < RV(b[0])) [a, b] = [b, a];
    if (a[0] === b[0]) return a[0] + b[0];
    return a[0] + b[0] + (a[1] === b[1] ? "s" : "o");
  }

  // ---------------------------------------------------------------- range notation
  // "22+, 77-55, A2s+, A5s-A2s, KJo+, AJo-ATo, T9s@50"   (@NN = frequency in %)
  function parseRange(str) {
    const out = new Map();
    const add = (h, f) => out.set(h, Math.min(1, (out.get(h) || 0) + f));
    for (let tok of str.split(",")) {
      tok = tok.trim();
      if (!tok) continue;
      let f = 1;
      const at = tok.indexOf("@");
      if (at >= 0) { f = +tok.slice(at + 1) / 100; tok = tok.slice(0, at); }
      if (tok.includes("-")) {
        const [a, b] = tok.split("-");
        if (a[0] === a[1]) {                        // pairs 77-55
          for (let r = RV(b[0]); r <= RV(a[0]); r++) add(R[12 - r] + R[12 - r], f);
        } else {                                    // A5s-A2s: same top card, kicker range
          const hi = a[0], sfx = a.slice(2);
          for (let r = RV(b[1]); r <= RV(a[1]); r++) add(hi + R[12 - r] + sfx, f);
        }
      } else if (tok.endsWith("+")) {
        tok = tok.slice(0, -1);
        if (tok[0] === tok[1]) {                    // 22+
          for (let r = RV(tok[0]); r <= 12; r++) add(R[12 - r] + R[12 - r], f);
        } else {                                    // A2s+: kicker up to one below the top card
          const hi = tok[0], sfx = tok.slice(2);
          for (let r = RV(tok[1]); r < RV(hi); r++) add(hi + R[12 - r] + sfx, f);
        }
      } else add(tok, f);
    }
    for (const h of out.keys()) if (!(h in IDX)) throw new Error("bad hand " + h);
    return out;
  }

  // ---------------------------------------------------------------- positions
  const POS8 = ["UTG", "UTG1", "LJ", "HJ", "CO", "BTN", "SB", "BB"];
  const positions = n => POS8.slice(8 - n);         // 6-max: LJ HJ CO BTN SB BB
  const POS_CN = {UTG: "枪口", UTG1: "枪口+1", LJ: "低位", HJ: "劫位", CO: "关煞位", BTN: "庄位", SB: "小盲", BB: "大盲"};

  // ---------------------------------------------------------------- charts (100bb)
  const RFI = {
    UTG:  "66+,55@75,44@50,33@25,A9s+,A8s@50,A5s-A4s,A3s@50,KTs+,K9s@25,QTs+,JTs,T9s@50,98s@25,AJo+,ATo@25,KQo,KJo@25",
    UTG1: "55+,44@75,33@50,22@25,A8s+,A7s@50,A5s-A3s,A2s@50,K9s+,QTs+,Q9s@25,J9s+,T9s,98s@50,87s@25,ATo+,KJo+,KTo@25,QJo@50",
    LJ:   "33+,22@50,A2s+,K9s+,K8s@50,Q9s+,J9s+,T9s,98s,87s@50,76s@25,ATo+,A9o@25,KJo+,KTo@50,QJo,QTo@25,JTo@25",
    HJ:   "22+,A2s+,K7s+,K6s@50,Q9s+,Q8s@50,J9s+,J8s@25,T8s+,97s+,87s,76s@75,65s@50,54s@25,A9o+,A8o@25,KTo+,K9o@25,QTo+,JTo@75",
    CO:   "22+,A2s+,K6s+,K5s@50,Q8s+,Q7s@50,J8s+,T8s+,T7s@50,97s+,87s,86s@50,76s,75s@25,65s,54s@50,A8o+,A7o@50,A5o@50,KTo+,K9o@50,QTo+,JTo,T9o@50",
    BTN:  "22+,A2s+,K2s+,Q4s+,Q3s@50,J6s+,J5s@50,T6s+,96s+,85s+,75s+,64s+,54s,53s@50,A2o+,K8o+,K7o@50,Q9o+,Q8o@50,J9o+,J8o@25,T8o+,98o,87o@50",
    SB:   "22+,A2s+,K2s+,Q2s+,J5s+,T6s+,96s+,85s+,75s+,64s+,54s,A2o+,K7o+,Q9o+,J9o+,T9o,98o@50",
  };
  // facing one open: [3-bet range, call range]. A hand's call share is capped at 1 - its 3-bet share.
  const VS_OPEN = {
    "IP:EP":  ["QQ+,AKs,AKo@75,A5s@50,A4s@25,KQs@25",
               "JJ-77,66@50,AQs-ATs,AKo@25,AQo@50,KQs,KJs,QJs,JTs,T9s@50"],
    "IP:MP":  ["JJ+,AQs+,AKo,A5s-A4s@50,KQs@50,AJs@25",
               "TT-66,55@50,AJs-ATs,A9s@25,KQs,KJs,KTs@50,QJs,QTs@50,JTs,T9s,98s@50,AQo@50"],
    "IP:CO":  ["TT+,AJs+,ATs@50,A5s-A3s,KQs,KJs@50,QJs@25,76s@25,65s@25,AQo+,AJo@25",
               "99-44,33@50,ATs-A6s,KTs-K9s,QTs+,Q9s@50,J9s+,T8s+,98s,87s,76s,AJo,KQo@75,KJo@25,QJo@25"],
    "SB:EP":  ["JJ+,TT@75,AQs+,AJs@50,AKo,AQo@25,KQs@50,A5s@50,A4s@25", ""],
    "SB:MP":  ["TT+,99@50,AJs+,ATs@50,A5s-A4s,A3s@50,KQs,KJs@50,QJs@50,AQo+,AJo@25", ""],
    "SB:CO":  ["88+,A9s+,A5s-A2s,A8s@50,KTs+,K9s@50,QTs+,JTs,T9s@50,AJo+,ATo@50,KQo,KJo@25", ""],
    "SB:BTN": ["77+,66@50,A8s+,A5s-A2s,A7s@50,K9s+,K8s@50,Q9s+,J9s+,T9s,98s@50,87s@25,ATo+,A9o@50,KJo+,KTo@50,QJo@50", ""],
    "BB:EP":  ["QQ+,AKs,AKo@75,A5s@50,A4s@25,KQs@25",
               "JJ-22,A2s+,K6s+,Q8s+,J8s+,T8s+,97s+,86s+,75s+,65s,54s,AKo,AQo-ATo,A9o@50,KQo,KJo,KTo@50,QJo,QTo@50,JTo"],
    "BB:MP":  ["JJ+,AQs+,AKo,A5s-A4s@50,KQs@50,K9s@25,76s@25",
               "TT-22,A2s+,K5s+,Q7s+,J7s+,T7s+,96s+,85s+,74s+,64s+,54s,43s@50,AQo-A9o,A8o@50,KQo-KTo,K9o@50,QJo-QTo,JTo,T9o@50"],
    "BB:CO":  ["TT+,AJs+,A5s-A3s,KQs,KJs@50,AQo+,J9s@25,65s@50,54s@25",
               "99-22,A2s+,K2s+,Q5s+,J7s+,T6s+,96s+,85s+,74s+,64s+,53s+,43s,AJo-A5o,A4o@50,KQo-K9o,K8o@50,QJo-Q9o,JTo-J9o,T9o,98o@50,87o@25"],
    "BB:BTN": ["99+,88@50,ATs+,A5s-A2s@75,KTs+,K5s-K4s@50,QJs,QTs@50,J9s@50,T8s@50,97s@50,86s@25,65s@50,54s@50,AJo+,ATo@50,KQo,KJo@25",
               "88-22,A2s+,K2s+,Q2s+,J4s+,T6s+,95s+,85s+,74s+,63s+,53s+,42s+,32s@50,A2o+,K5o+,K4o@50,Q7o+,J7o+,T7o+,97o+,86o+,76o,65o@50"],
    "BB:SB":  ["88+,A9s+,A5s-A2s@50,KTs+,K6s-K2s@25,QJs,Q8s@25,J9s@50,T8s@50,97s@50,86s@50,75s@50,64s@50,ATo+,KJo+,QJo@50,A5o@50,K9o@25",
               "77-22,A2s+,K2s+,Q2s+,J2s+,T4s+,95s+,84s+,73s+,63s+,52s+,42s+,32s,A2o+,K2o+,Q4o+,J6o+,T6o+,96o+,86o+,75o+,65o,54o@50"],
  };
  // you opened and got 3-bet: [4-bet range, call range]
  const VS_3BET = {
    EP:  ["KK+,QQ@50,AKs,AKo@50,A5s@25",
          "QQ,JJ-88,77@50,AKo,AQs-AJs,ATs@50,KQs,KJs@50,QJs@50,JTs@50,A5s"],
    MP:  ["QQ+,AKs,AKo@75,A5s@50,A4s@25",
          "JJ-77,66@50,AQs-ATs,A9s@25,KQs-KJs,KTs@50,QJs,QTs@50,JTs,T9s@50,98s@25,AKo,AQo@50,A5s,A4s"],
    CO:  ["QQ+,JJ@25,AKs,AQs@25,AKo,A5s-A4s@50",
          "JJ-66,55@50,AQs-A9s,KQs-KTs,QJs-QTs,JTs,T9s,98s@50,87s@50,AQo,AJo@50,KQo@50,A5s-A4s"],
    BTN: ["JJ+,AQs+,AKo,A5s-A3s@50,K9s@25,AJo@25,KQo@25",
          "TT-44,AJs-A2s,KJs-K9s,QTs+,Q9s@50,J9s+,T8s+,98s,87s,76s,65s@50,AQo-AJo,KQo@75,KJo@25"],
    SB:  ["JJ+,AQs+,AKo,A5s-A2s@50,K9s@25,AQo@50",
          "TT-22,AJs-A2s,KTs+,K9s@50,QTs+,J9s+,T8s+,97s+,86s+,76s,65s,54s@50,AQo-ATo,KQo,KJo@50,QJo@25"],
  };
  const COLD_4BET = ["QQ+,AKs,AKo@50,A5s@25", "JJ@50,TT@25,AQs@50,AKo@50"];
  const VS_ISO = ["QQ+,AKs,AKo@50", "JJ-22,AQs-A9s,A5s-A4s,KQs-KTs,QJs-QTs,JTs,T9s,98s,87s,76s,65s,AKo@50,AQo,KQo@50"];
  const VS_4BET = ["KK+,AKs,QQ@50,AKo@50,A5s@25", "QQ,JJ,TT@50,AKo,AQs@50"];

  const cat = p => (p === "UTG" || p === "UTG1") ? "EP" : (p === "LJ" || p === "HJ") ? "MP" : p;

  const cache = new Map();
  const parsed = s => { if (!cache.has(s)) cache.set(s, parseRange(s)); return cache.get(s); };

  // A spot is {kind, hero, vs}; returns {raise: Map, call: Map, labels} or null
  function chart(spot) {
    const {kind, hero, vs} = spot;
    let r = "", c = "", labels = {raise: "加注", call: "跟注", fold: "弃牌"};
    if (kind === "rfi") {
      if (!RFI[hero]) return null;
      r = RFI[hero]; labels.raise = "开池加注";
    } else if (kind === "vsopen") {
      const hc = hero === "SB" || hero === "BB" ? hero : "IP";
      let vc = cat(vs);
      if (hc === "IP" && vc === "BTN") return null;   // nobody but the blinds acts after BTN
      const key = hc + ":" + vc;
      if (!VS_OPEN[key]) return null;
      [r, c] = VS_OPEN[key]; labels.raise = "3-bet";
    } else if (kind === "vs3bet") {
      const k = cat(hero);
      if (!VS_3BET[k]) return null;
      [r, c] = VS_3BET[k]; labels.raise = "4-bet";
    } else if (kind === "cold4bet") { [r, c] = COLD_4BET; labels.raise = "4-bet"; }
    else if (kind === "vs4bet") { [r, c] = VS_4BET; labels.raise = "5-bet 全下"; }
    else if (kind === "vsiso") { [r, c] = VS_ISO; labels.raise = "再加注"; }
    else return null;
    return {raise: parsed(r), call: parsed(c), labels};
  }

  // strategy of one hand class in a chart: {r, c, f}
  function freqs(ch, hand) {
    const r = ch.raise.get(hand) || 0;
    const c = Math.min(1 - r, ch.call.get(hand) || 0);
    return {r, c, f: Math.max(0, 1 - r - c)};
  }
  function totals(ch, strat) {
    let r = 0, c = 0;
    for (const h of HANDS) { const s = strat ? strat(h) : freqs(ch, h); r += s.r * COMBOS(h); c += s.c * COMBOS(h); }
    return {r: r / TOTAL, c: c / TOTAL, f: 1 - (r + c) / TOTAL};
  }

  // ---------------------------------------------------------------- equity table
  let EQ = null, W = null, VSRAND = null;          // EQ[i][j] equity of class i vs class j
  const comboList = h => {
    const a = h[0], b = h[1], S = "shdc", out = [];
    if (h.length === 2) { for (let x = 0; x < 4; x++) for (let y = x + 1; y < 4; y++) out.push([a + S[x], b + S[y]]); }
    else if (h[2] === "s") { for (let x = 0; x < 4; x++) out.push([a + S[x], b + S[x]]); }
    else { for (let x = 0; x < 4; x++) for (let y = 0; y < 4; y++) if (x !== y) out.push([a + S[x], b + S[y]]); }
    return out;
  };
  const COMBO_LIST = HANDS.map(comboList);
  // combos of class j left once these exact cards are out
  const live = (j, cards) => COMBO_LIST[j].reduce((n, c) => n + (cards.includes(c[0]) || cards.includes(c[1]) ? 0 : 1), 0);

  function setEquity(data) {
    const order = data.hands.map(h => IDX[h]);
    EQ = Array.from({length: 169}, () => new Float64Array(169));
    for (let a = 0; a < 169; a++) for (let b = 0; b < 169; b++) EQ[order[a]][order[b]] = data.eq[a][b] / 1000;
    // W[i][j]: expected live combos of j given a random combo of i (card removal)
    W = Array.from({length: 169}, () => new Float64Array(169));
    for (let i = 0; i < 169; i++) {
      const ci = COMBO_LIST[i];
      for (let j = 0; j < 169; j++) {
        let s = 0;
        for (const c of ci) s += live(j, c);
        W[i][j] = s / ci.length;
      }
    }
    VSRAND = HANDS.map((h, i) => {
      let s = 0, w = 0;
      for (let j = 0; j < 169; j++) { s += W[i][j] * EQ[i][j]; w += W[i][j]; }
      return s / w;
    });
  }
  let eqPromise = null;
  function loadEquity(url) {
    if (EQ) return Promise.resolve(true);
    if (!eqPromise) eqPromise = fetch(url || "hu_equity.json").then(r => r.json()).then(d => { setEquity(d); return true; })
      .catch(() => { eqPromise = null; return false; });
    return eqPromise;
  }

  // exact cards vs a weighted range of classes: {eq, combos}
  function equityVsRange(cards, range) {
    const i = IDX[handOf(cards)];
    let s = 0, w = 0;
    for (let j = 0; j < 169; j++) {
      const f = range[j];
      if (!f) continue;
      const n = live(j, cards) * f;
      s += n * EQ[i][j]; w += n;
    }
    return {eq: w ? s / w : 0.5, combos: w};
  }

  // ---------------------------------------------------------------- heads-up push/fold solver
  // SB has posted 0.5bb, BB 1bb, effective stack S bb. SB shoves or folds; BB calls or folds.
  // Fictitious play: each iteration both players best-respond to the other's AVERAGE strategy,
  // and the averages converge to a Nash equilibrium.
  class PushFoldSolver {
    constructor(S) {
      this.S = S; this.t = 0;
      this.push = new Float64Array(169).fill(0.5);     // average strategies
      this.call = new Float64Array(169).fill(0.5);
      this.history = [];
      this.prior = HANDS.map(h => COMBOS(h));
    }
    // SB EV (bb, relative to folding = -0.5) of shoving each class against call strategy c
    sbPushEV(c) {
      const S = this.S, out = new Float64Array(169);
      for (let i = 0; i < 169; i++) {
        let ev = 0, w = 0;
        for (let j = 0; j < 169; j++) {
          const n = W[i][j];
          ev += n * ((1 - c[j]) * 1 + c[j] * (EQ[i][j] * 2 * S - S));
          w += n;
        }
        out[i] = ev / w;
      }
      return out;
    }
    // BB EV of calling each class against push strategy p (folding = -1); null where SB never shoves
    bbCallEV(p) {
      const S = this.S, out = new Float64Array(169);
      for (let j = 0; j < 169; j++) {
        let ev = 0, w = 0;
        for (let i = 0; i < 169; i++) {
          const n = W[j][i] * p[i];
          ev += n * (EQ[j][i] * 2 * S - S);
          w += n;
        }
        out[j] = w ? ev / w : -1;
      }
      return out;
    }
    // SB's expected value (bb per hand) when SB plays p and BB plays c
    value(p, c) {
      const S = this.S;
      let v = 0, z = 0;
      for (let i = 0; i < 169; i++) for (let j = 0; j < 169; j++) {
        const n = this.prior[i] * W[i][j];
        const shove = (1 - c[j]) * 1 + c[j] * (EQ[i][j] * 2 * S - S);
        v += n * (p[i] * shove + (1 - p[i]) * -0.5);
        z += n;
      }
      return v / z;
    }
    step(k = 1) {
      for (let s = 0; s < k; s++) {
        this.t++;
        const a = 1 / (this.t + 1);
        const pe = this.sbPushEV(this.call), ce = this.bbCallEV(this.push);
        for (let i = 0; i < 169; i++) {
          this.push[i] += a * ((pe[i] > -0.5 ? 1 : 0) - this.push[i]);
          this.call[i] += a * ((ce[i] > -1 ? 1 : 0) - this.call[i]);
        }
      }
      const ex = this.exploitability();
      this.history.push([this.t, ex]);
      return ex;
    }
    // how much a best responder gains on average (bb per hand) against the current averages
    exploitability() {
      const pe = this.sbPushEV(this.call), ce = this.bbCallEV(this.push);
      const brP = Array.from(pe, v => v > -0.5 ? 1 : 0), brC = Array.from(ce, v => v > -1 ? 1 : 0);
      const v = this.value(this.push, this.call);
      return Math.max(0, ((this.value(brP, this.call) - v) + (v - this.value(this.push, brC))) / 2);
    }
    solve(maxIter = 400, tol = 0.002) {
      while (this.t < maxIter) if (this.step(20) < tol) break;
      return this;
    }
  }
  const nashCache = new Map();
  function nash(S) {
    const key = Math.round(S * 2) / 2;
    if (!nashCache.has(key)) {
      const s = new PushFoldSolver(key).solve();
      // the averages keep a trace of the 50% starting point: snap near-pure hands
      for (const a of [s.push, s.call]) for (let i = 0; i < 169; i++) a[i] = a[i] < 0.03 ? 0 : a[i] > 0.97 ? 1 : a[i];
      nashCache.set(key, s);
    }
    return nashCache.get(key);
  }

  // ---------------------------------------------------------------- push/fold for any seat
  // Shove share (of 1326 combos) at 10bb by players left behind; scaled for other depths.
  // Approximate multi-way Nash; the SB (one player behind) uses the solver above.
  const PUSH10 = {2: 34, 3: 26, 4: 21, 5: 17, 6: 14, 7: 12};
  let ORDER = null;                                  // classes, best shove first
  function shoveOrder() {
    if (ORDER) return ORDER;
    // equity vs random and vs a tight calling range (top 15%), averaged
    const byRand = HANDS.map((h, i) => i).sort((a, b) => VSRAND[b] - VSRAND[a]);
    const top = new Float64Array(169);
    let acc = 0;
    for (const i of byRand) { if (acc < 0.15 * TOTAL) top[i] = 1; acc += COMBOS(HANDS[i]); }
    const score = HANDS.map((h, i) => {
      let s = 0, w = 0;
      for (let j = 0; j < 169; j++) if (top[j]) { s += W[i][j] * EQ[i][j]; w += W[i][j]; }
      return (VSRAND[i] + s / w) / 2;
    });
    ORDER = HANDS.map((h, i) => i).sort((a, b) => score[b] - score[a]);
    return ORDER;
  }
  function topPercent(pct) {                         // Float64Array of frequencies
    const out = new Float64Array(169), goal = pct / 100 * TOTAL;
    let acc = 0;
    for (const i of shoveOrder()) {
      const n = COMBOS(HANDS[i]);
      if (acc >= goal) break;
      out[i] = Math.min(1, (goal - acc) / n);
      acc += n;
    }
    return out;
  }
  function pushPercent(behind, S) {
    const base = PUSH10[Math.min(7, Math.max(2, behind))];
    return Math.max(3, Math.min(100, base * Math.pow(10 / Math.max(S, 1), 0.65)));
  }
  function pushRange(pos, behind, S) {
    if (!EQ) return null;
    if (behind <= 1) return Float64Array.from(nash(S).push);
    return topPercent(pushPercent(behind, S));
  }

  // ---------------------------------------------------------------- live advice for the table viewer
  // Seats clockwise from the small blind; names from the end of POS8 (BTN, CO, HJ, ...).
  function seatPositions(st) {
    const n = st.n, dealt = st.seats.map(s => s.dealt);
    const order = [];
    for (let k = 0, i = st.sb_seat; k < n; k++, i = (i + 1) % n) if (dealt[i]) order.push(i);
    const pos = {};
    if (order.length === 2) { pos[order[0]] = "SB"; pos[order[1]] = "BB"; return {pos, order}; }
    pos[order[0]] = "SB"; pos[order[1]] = "BB";
    const rest = order.slice(2), names = POS8.slice(0, 6).slice(6 - rest.length);
    rest.forEach((s, k) => pos[s] = names[k]);
    return {pos, order};
  }

  function rangeFromChart(ch, which) {               // Float64Array of one action's frequencies
    return Float64Array.from(HANDS, h => { const f = freqs(ch, h); return which === "r" ? f.r : f.c; });
  }

  function advise(st) {
    const me = st.human_seat, req = st.request;
    if (me == null || !req || st.street !== 0) return null;
    const seat = st.seats[me];
    if (!seat.cards || seat.cards.length !== 2) return null;
    if (st.variant && st.variant !== "holdem")
      return {unsupported: "GTO 翻前建议目前只支持德州扑克（这一手是 " + (st.variant_title || st.variant) + "）"};
    const {pos, order} = seatPositions(st);
    const bb = st.bb, hero = pos[me], hand = handOf(seat.cards);
    const start = i => st.seats[i].stack + st.seats[i].bet;          // chips at the start of the hand (preflop)
    const acts = st.preflop || [];
    let top = bb, raises = [], limpers = [];
    for (const a of acts) {
      if (a.to > top) { raises.push(a); top = a.to; }
      else if ((a.code === "C") && !raises.length) limpers.push(a);
    }
    const others = st.seats.map((s, i) => i).filter(i => i !== me && st.seats[i].dealt && !st.seats[i].folded);
    const effChips = Math.min(start(me), Math.max(...others.map(start)));
    const eff = effChips / bb;
    const pre = order.length > 2 ? [...order.slice(2), order[0], order[1]] : order;   // preflop action order
    const behind = pre.length - 1 - pre.indexOf(me);                  // players left to act after me preflop
    const base = {hero, hand, eff, cards: seat.cards};
    const pot = st.pot, toCall = req.to_call;

    // facing an all-in (or a call that puts us all-in): compare equity with the price
    const last = raises[raises.length - 1];
    const allIn = last && (st.seats[last.seat].stack === 0 || toCall >= seat.stack);
    if (allIn) {
      if (!EQ) return {...base, title: "面对全下", note: "胜率表还在加载…", freqs: null};
      const vpos = pos[last.seat], vS = start(last.seat) / bb;
      let vr, desc;
      if (raises.length === 1) {
        const vBehind = pre.length - 1 - pre.indexOf(last.seat);
        if (vS <= 25) { vr = pushRange(vpos, vBehind, Math.max(vS, 1)); desc = `${vpos} ${vS.toFixed(0)}bb 推全下范围`; }
        else { const ch = chart({kind: "rfi", hero: vpos}); vr = ch ? rangeFromChart(ch, "r") : topPercent(20); desc = `${vpos} 开池范围`; }
      } else {
        const pct = Math.max(4, Math.min(25, 32 - vS * 0.7));
        vr = topPercent(pct); desc = `再加注全下（估计前 ${pct.toFixed(0)}%）`;
      }
      const {eq} = equityVsRange(seat.cards, vr);
      const call = Math.min(toCall, seat.stack);
      const need = call / (pot + call);
      const m = eq - need, c = m > 0.02 ? 1 : m < -0.02 ? 0 : (m + 0.02) / 0.04;
      return {...base, title: `面对 ${vpos} 全下`, spot: null,
        note: `你的胜率 ${(eq * 100).toFixed(1)}%（对 ${desc}），跟注需要 ${(need * 100).toFixed(1)}%`,
        freqs: {r: 0, c, f: 1 - c}, labels: {raise: "加注", call: "跟注", fold: "弃牌"}, computed: true,
        multiway: others.length > 1};
    }

    // short-stacked and first in: push or fold
    if (!raises.length && !limpers.length && hero !== "BB" && eff <= 15 && EQ) {
      const pr = pushRange(hero, behind, eff), i = IDX[hand];
      const pct = HANDS.reduce((a, h, k) => a + pr[k] * COMBOS(h), 0) / TOTAL * 100;
      return {...base, title: `${hero} 推或弃 · ${eff.toFixed(1)}bb`,
        note: behind <= 1 ? "小盲对大盲：下面是实时求解的单挑纳什均衡" : `近似纳什推全下范围：约前 ${pct.toFixed(0)}% 的手牌`,
        freqs: {r: pr[i], c: 0, f: 1 - pr[i]}, labels: {raise: "全下", call: "跟注", fold: "弃牌"}, shove: true,
        spot: {kind: "push", hero, behind, S: eff}, computed: behind <= 1};
    }

    let spot, heur = "";
    if (!raises.length) {
      if (hero === "BB") {
        const ch = {raise: parsed("99+,ATs+,KJs+,AQo+,KQo@50"), call: parsed("22+,A2s+,K2s+,Q2s+,J2s+,T2s+,92s+,82s+,72s+,62s+,52s+,42s+,32s,A2o+,K2o+,Q2o+,J2o+,T2o+,92o+,82o+,72o+,62o+,52o+,42o+,32o"), labels: {raise: "加注", call: "过牌", fold: "弃牌"}};
        return {...base, title: limpers.length ? "大盲 · 面对平跟" : "大盲 · 无人加注", note: "可以免费看翻牌，强牌加注隔离（启发式）",
          freqs: freqs(ch, hand), labels: ch.labels, chart: ch, heuristic: true};
      }
      if (limpers.length) {
        const i = Math.max(0, POS8.indexOf(hero) - 2), iso = RFI[POS8[i]];
        const late = ["CO", "BTN", "SB"].includes(hero);
        const ch = {raise: parsed(iso), call: parsed(late ? "22-66,A2s-A9s,K9s,Q9s+,J9s+,T8s+,97s+,86s+,75s+,64s+,54s" : ""),
          labels: {raise: "加注隔离", call: "平跟", fold: "弃牌"}};
        return {...base, title: `${hero} · 面对 ${limpers.length} 个平跟`, note: "启发式：用更紧的开池范围加注隔离",
          freqs: freqs(ch, hand), labels: ch.labels, chart: ch, heuristic: true};
      }
      spot = {kind: "rfi", hero};
    } else if (raises.length === 1 && acts.some(a => a.seat === me)) {
      spot = {kind: "vsiso", hero, vs: pos[raises[0].seat]};         // we limped, then someone raised
      heur = "启发式：GTO 很少平跟，被加注后多用跟注/弃牌，强牌再加注";
    } else if (raises.length === 1) {
      spot = {kind: "vsopen", hero, vs: pos[raises[0].seat]};
      if (acts.some(a => a.code === "C" && acts.indexOf(a) > acts.indexOf(raises[0]))) heur = "有人跟注：按单一加注近似（可以多做 squeeze）";
    } else if (raises.length === 2) {
      spot = raises[0].seat === me ? {kind: "vs3bet", hero, vs: pos[raises[1].seat]} : {kind: "cold4bet", hero};
    } else spot = {kind: "vs4bet", hero};
    const ch = chart(spot);
    if (!ch) return {...base, title: "没有对应的范围表", note: "", freqs: null};
    let note = heur;
    if (eff < 40) note = (note ? note + "；" : "") + `范围表按 100bb 计算，现在有效筹码只有 ${eff.toFixed(0)}bb，应更紧、更多直接全下`;
    return {...base, title: spotTitle(spot), note, freqs: freqs(ch, hand), labels: ch.labels, chart: ch, spot};
  }

  function spotTitle(s) {
    if (s.kind === "rfi") return `${s.hero} 开池（无人入池）`;
    if (s.kind === "vsopen") return `${s.hero} 面对 ${s.vs} 开池`;
    if (s.kind === "vs3bet") return `${s.hero} 开池后面对 ${s.vs} 3-bet`;
    if (s.kind === "cold4bet") return `${s.hero} 面对加注和 3-bet`;
    if (s.kind === "vs4bet") return `${s.hero} 面对 4-bet`;
    if (s.kind === "vsiso") return `${s.hero} 平跟后面对 ${s.vs} 加注`;
    if (s.kind === "push") return `${s.hero} 推或弃 · ${s.S}bb`;
    return "";
  }

  // grade an action against a strategy: best / ok / inaccurate / wrong
  function grade(f, act) {
    const p = act === "r" ? f.r : act === "c" ? f.c : f.f;
    const best = Math.max(f.r, f.c, f.f);
    if (p >= best - 1e-9) return {code: "best", text: "最佳", p};
    if (p >= 0.25) return {code: "ok", text: "可以（混合策略）", p};
    if (p > 0) return {code: "inacc", text: "不精确", p};
    return {code: "wrong", text: "错误", p};
  }

  // ---------------------------------------------------------------- 13x13 grid
  const COLORS = {r: "#e0603f", a: "#b3183a", c: "#2fbf71", f: "#2c4f80"};
  function cellBG(f, shove) {
    const r = f.r * 100, c = f.c * 100;
    const rc = shove ? COLORS.a : COLORS.r;
    return `linear-gradient(90deg,${rc} 0 ${r}%,${COLORS.c} ${r}% ${r + c}%,${COLORS.f} ${r + c}% 100%)`;
  }
  // strat(hand) -> {r,c,f}; opts.highlight = hand name; opts.cls = extra class
  function gridHTML(strat, opts = {}) {
    let h = `<div class="gto-grid ${opts.cls || ""}">`;
    for (const name of HANDS) {
      const f = strat(name);
      const hl = name === opts.highlight ? " hl" : "";
      const title = `${name}  ${opts.labels ? opts.labels.raise : "加注"} ${Math.round(f.r * 100)}%` +
        (f.c ? ` · ${opts.labels ? opts.labels.call : "跟注"} ${Math.round(f.c * 100)}%` : "") + ` · 弃牌 ${Math.round(f.f * 100)}%`;
      h += `<div class="gc${hl}" data-h="${name}" title="${title}" style="background:${cellBG(f, opts.shove)}"><span>${name}</span></div>`;
    }
    return h + "</div>";
  }
  const GRID_CSS = `.gto-grid{display:grid;grid-template-columns:repeat(13,1fr);gap:2px;user-select:none}
.gto-grid .gc{aspect-ratio:1/1;position:relative;border-radius:3px;display:flex;align-items:flex-start;justify-content:flex-start;
  font-size:clamp(7px,0.9vw,12px);font-weight:700;color:#fff;text-shadow:0 1px 2px rgba(0,0,0,.8);overflow:hidden;cursor:default}
.gto-grid .gc span{padding:2px 3px;letter-spacing:-.02em}
.gto-grid .gc.hl{outline:2px solid #fff;outline-offset:-1px;box-shadow:0 0 12px rgba(255,255,255,.7);z-index:1}
.gto-grid.dimmed .gc:not(.hl){filter:saturate(.75) brightness(.8)}`;

  root.GTO = {HANDS, IDX, COMBOS, TOTAL, R, handOf, parseRange, POS8, POS_CN, positions, RFI, VS_OPEN, VS_3BET,
    chart, freqs, totals, spotTitle, grade, gridHTML, cellBG, COLORS, GRID_CSS, loadEquity, setEquity,
    equityVsRange, PushFoldSolver, nash, pushRange, pushPercent, topPercent, advise, seatPositions,
    hasEquity: () => !!EQ};
})(typeof window !== "undefined" ? window : globalThis);
