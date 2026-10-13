/* Arvo video: clean single-line animation engine (v3).
 *
 * Look: flat night background with faint grain, warm cream line art, flat accent fills.
 * Strokes are drawn as filled outlines that taper at the ends (thick middle, thin ends),
 * like a round brush with a little pressure. Points jitter by ~0.35 px, re-seeded every
 * second drawn frame (12 fps drawing -> new jitter 6x a second), so lines are alive but clean.
 *
 * Line.scene({nominal, shots, init, transparent}): `nominal` is the length (s) the timings were authored
 * for; at runtime all times scale by d / nominal. Shot = {start, end, camera(tn, f), build(tn, f)}.
 * Items (all coordinates in world px):
 *   cmds        path commands [['M',x,y],['C',x1,y1,x2,y2,x,y],['L',x,y],['Q',x1,y1,x,y],['Z']]
 *   stroke      colour (default cream) or null; width (mid, default 7); wEnd (default 0.64*width)
 *   fill, fillOpacity, fillAt, fillSnap   flat fill (fades in at fillAt unless fillSnap)
 *   at, dur     draw-on window (omit = drawn)
 *   pop         {x, y, at, dur}: scale in with overshoot around (x, y)
 *   opacity, clipW {x, y, w, h, p}: left-to-right reveal
 *   group       {type:'group', items, move:[dx,dy], rotate:{deg,x,y}, scale:{s,sy?,x,y}, clip:cmds, pop, opacity}
 *   text        {text, x, y, size, weight, fill, at, dur, mode:'words'|'type'|'fade', anchor, caret}
 *   screen: true on any item or group pins it to the screen (no camera), e.g. corner notes
 * Camera(tn) -> {x, y, s, ox, oy, dx, dy}: world (x,y) lands on screen (ox+dx, oy+dy), zoom s.
 * Line widths stay constant under zoom (one brush); text scales.
 * window.renderAt(t) draws the frame for t seconds. ?d=<len>&t=<time> for previews.
 * transparent: true skips the background (for overlays rendered with omit_background).
 * init(canvas) runs once after fonts load (canvas = the background canvas).
 */
(function () {
  "use strict";
  const W = 1920, H = 1080, FPS = 12;
  const q = new URLSearchParams(location.search);
  const C = {
    bg: "#1c2330",
    line: "#efe8d6",
    amber: "#e9b65a",
    red: "#d9534f",
    green: "#7fb08f",
    screen: "#ece5d2",
    body: "#242d3c",
  };
  const D2R = Math.PI / 180;
  const FONT = '"Shantell Sans"';

  // ---------- randomness
  function hash() {
    let h = 2166136261 >>> 0;
    for (let i = 0; i < arguments.length; i++) {
      h ^= (arguments[i] | 0) >>> 0;
      h = Math.imul(h, 16777619) >>> 0;
      h ^= h >>> 15;
    }
    return h >>> 0;
  }
  function mulberry32(a) {
    return function () {
      a |= 0; a = (a + 0x6D2B79F5) | 0;
      let t = Math.imul(a ^ (a >>> 15), 1 | a);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }
  const rnd = (...n) => mulberry32(hash(...n))();
  const sym = (...n) => rnd(...n) * 2 - 1;

  const clamp = (x, a = 0, b = 1) => Math.max(a, Math.min(b, x));
  const lerp = (a, b, p) => a + (b - a) * p;
  const ease = {
    lin: (p) => p,
    out: (p) => 1 - Math.pow(1 - p, 3),
    in: (p) => p * p * p,
    in2: (p) => p * p,
    out2: (p) => 1 - (1 - p) * (1 - p),
    inOut: (p) => (p < 0.5 ? 4 * p * p * p : 1 - Math.pow(-2 * p + 2, 3) / 2),
    back: (p) => { const c1 = 1.8, c3 = c1 + 1; return 1 + c3 * Math.pow(p - 1, 3) + c1 * Math.pow(p - 1, 2); },
    soft: (p) => { const c1 = 1.1, c3 = c1 + 1; return 1 + c3 * Math.pow(p - 1, 3) + c1 * Math.pow(p - 1, 2); },
    draw: (p) => (p < 0.5 ? 2 * p * p : 1 - Math.pow(-2 * p + 2, 2) / 2),
  };
  const smooth = (x) => { x = clamp(x); return x * x * (3 - 2 * x); };

  // ---------- geometry
  function curve(pts, closed, tension) {
    const k = (tension == null ? 1 : tension) / 6;
    const n = pts.length;
    if (n < 2) return [];
    const P = (i) => closed ? pts[(i + n) % n] : pts[Math.max(0, Math.min(n - 1, i))];
    const cmds = [["M", pts[0][0], pts[0][1]]];
    const segs = closed ? n : n - 1;
    for (let i = 0; i < segs; i++) {
      const p0 = P(i - 1), p1 = P(i), p2 = P(i + 1), p3 = P(i + 2);
      cmds.push(["C", p1[0] + (p2[0] - p0[0]) * k, p1[1] + (p2[1] - p0[1]) * k,
        p2[0] - (p3[0] - p1[0]) * k, p2[1] - (p3[1] - p1[1]) * k, p2[0], p2[1]]);
    }
    if (closed) cmds.push(["Z"]);
    return cmds;
  }
  function poly(pts, closed) {
    const cmds = [["M", pts[0][0], pts[0][1]]];
    for (let i = 1; i < pts.length; i++) cmds.push(["L", pts[i][0], pts[i][1]]);
    if (closed) cmds.push(["Z"]);
    return cmds;
  }
  function blob(cx, cy, rx, ry, seed, wob, rot) {
    wob = wob == null ? 0.03 : wob;
    const pts = [], n = 8, r0 = (rot || 0) * D2R;
    for (let i = 0; i < n; i++) {
      const a = (i / n) * Math.PI * 2 + sym(seed || 1, i, 5) * 0.04;
      const w = 1 + sym(seed || 1, i, 7) * wob;
      const x = Math.cos(a) * rx * w, y = Math.sin(a) * ry * w;
      pts.push([cx + x * Math.cos(r0) - y * Math.sin(r0), cy + x * Math.sin(r0) + y * Math.cos(r0)]);
    }
    return curve(pts, true);
  }
  function rrect(x, y, w, h, r, seed, wob) {
    const k = wob == null ? 1.4 : wob;
    const s = (i) => sym(seed || 3, i, 9) * k;
    return [
      ["M", x + r, y + s(1)],
      ["L", x + w - r, y + s(2)],
      ["Q", x + w + s(3), y + s(4), x + w + s(5), y + r],
      ["L", x + w + s(6), y + h - r],
      ["Q", x + w + s(7), y + h + s(8), x + w - r, y + h + s(9)],
      ["L", x + r, y + h + s(10)],
      ["Q", x + s(11), y + h + s(12), x + s(13), y + h - r],
      ["L", x + s(14), y + r],
      ["Q", x + s(15), y + s(16), x + r, y + s(1)],
      ["Z"],
    ];
  }
  function mapCmds(cmds, fn) {
    return cmds.map((c) => {
      const out = [c[0]];
      for (let i = 1; i < c.length; i += 2) { const p = fn(c[i], c[i + 1]); out.push(p[0], p[1]); }
      return out;
    });
  }
  function rotateCmds(cmds, cx, cy, deg) {
    const a = deg * D2R, co = Math.cos(a), si = Math.sin(a);
    return mapCmds(cmds, (x, y) => [cx + (x - cx) * co - (y - cy) * si, cy + (x - cx) * si + (y - cy) * co]);
  }
  function translateCmds(cmds, dx, dy) { return mapCmds(cmds, (x, y) => [x + dx, y + dy]); }
  function scaleCmds(cmds, cx, cy, sx, sy) { sy = sy == null ? sx : sy; return mapCmds(cmds, (x, y) => [cx + (x - cx) * sx, cy + (y - cy) * sy]); }

  function jitterCmds(cmds, amp, seed) {
    if (!amp) return cmds;
    const memo = new Map();
    return mapCmds(cmds, (x, y) => {
      const kx = Math.round(x * 4), ky = Math.round(y * 4), key = kx + "," + ky;
      let v = memo.get(key);
      if (!v) { const h = hash(seed, kx, ky); v = [x + sym(h, 1) * amp, y + sym(h, 2) * amp]; memo.set(key, v); }
      return v;
    });
  }
  function cmdsToD(cmds) {
    let s = "";
    for (const c of cmds) {
      s += c[0];
      for (let i = 1; i < c.length; i += 2) s += (i > 1 ? " " : "") + c[i].toFixed(2) + "," + c[i + 1].toFixed(2);
    }
    return s;
  }

  // Flatten commands into polylines (one per subpath), remembering command joints.
  function flatten(cmds, step) {
    step = step || 3;
    const subs = [];
    let cur = null, last = null, start = null;
    const add = (x, y) => {
      const pts = cur.pts, l = pts[pts.length - 1];
      if (l && Math.abs(l[0] - x) < 0.01 && Math.abs(l[1] - y) < 0.01) return;
      pts.push([x, y]);
    };
    const joint = () => cur.joints.push(cur.pts.length - 1);
    for (const c of cmds) {
      const op = c[0];
      if (op === "M") { cur = { pts: [], joints: [], closed: false }; subs.push(cur); add(c[1], c[2]); last = [c[1], c[2]]; start = last; continue; }
      if (!cur) continue;
      if (op === "L") {
        joint();
        const n = Math.max(1, Math.ceil(Math.hypot(c[1] - last[0], c[2] - last[1]) / step));
        for (let i = 1; i <= n; i++) add(lerp(last[0], c[1], i / n), lerp(last[1], c[2], i / n));
        last = [c[1], c[2]];
      } else if (op === "C" || op === "Q") {
        joint();
        const p0 = last;
        const cps = op === "C" ? [[c[1], c[2]], [c[3], c[4]], [c[5], c[6]]] : [[c[1], c[2]], [c[3], c[4]]];
        const end = cps[cps.length - 1];
        let len = Math.hypot(end[0] - p0[0], end[1] - p0[1]);
        let poly = 0, prev = p0;
        for (const p of cps) { poly += Math.hypot(p[0] - prev[0], p[1] - prev[1]); prev = p; }
        len = (len + poly) / 2;
        const n = Math.max(2, Math.ceil(len / step));
        for (let i = 1; i <= n; i++) {
          const t = i / n, u = 1 - t;
          if (op === "C") {
            const [a, b, d] = cps;
            add(u * u * u * p0[0] + 3 * u * u * t * a[0] + 3 * u * t * t * b[0] + t * t * t * d[0],
              u * u * u * p0[1] + 3 * u * u * t * a[1] + 3 * u * t * t * b[1] + t * t * t * d[1]);
          } else {
            const [a, d] = cps;
            add(u * u * p0[0] + 2 * u * t * a[0] + t * t * d[0], u * u * p0[1] + 2 * u * t * a[1] + t * t * d[1]);
          }
        }
        last = end;
      } else if (op === "Z") {
        if (Math.hypot(last[0] - start[0], last[1] - start[1]) > 0.5) {
          joint();
          const n = Math.max(1, Math.ceil(Math.hypot(start[0] - last[0], start[1] - last[1]) / step));
          for (let i = 1; i <= n; i++) add(lerp(last[0], start[0], i / n), lerp(last[1], start[1], i / n));
        }
        cur.closed = true;
        last = start;
      }
    }
    return subs.filter((s) => s.pts.length >= 2);
  }

  // Tapered stroke outline for one polyline. p = fraction drawn (0..1].
  function strokeOutline(sub, wMid, wEnd, p, phase) {
    let P = sub.pts;
    const n0 = P.length;
    const S = [0];
    for (let i = 1; i < n0; i++) S.push(S[i - 1] + Math.hypot(P[i][0] - P[i - 1][0], P[i][1] - P[i - 1][1]));
    const L = S[n0 - 1];
    if (L < 0.3) return "";
    let closedFull = sub.closed && p >= 1;
    if (closedFull) {
      // drop a duplicate end point that equals the start
      const a = P[0], b = P[n0 - 1];
      if (Math.hypot(a[0] - b[0], a[1] - b[1]) < 0.6) { P = P.slice(0, -1); S.pop(); }
    }
    let Lp = L;
    if (p < 1) {
      Lp = L * p;
      let k = 1;
      while (k < S.length && S[k] < Lp) k++;
      if (k >= S.length) k = S.length - 1;
      const t = (Lp - S[k - 1]) / Math.max(1e-6, S[k] - S[k - 1]);
      const e = [lerp(P[k - 1][0], P[k][0], t), lerp(P[k - 1][1], P[k][1], t)];
      P = P.slice(0, k).concat([e]);
      S.length = k; S.push(Lp);
    }
    const n = P.length;
    if (n < 2 || Lp < 0.3) return "";
    const tl = Math.min(34, Lp * 0.42);
    const wid = (i) => {
      if (closedFull) return wMid - (wMid - wEnd) * 0.35 * (0.5 + 0.5 * Math.sin((S[i] / L) * Math.PI * 4 + phase));
      const e = Math.min(S[i], Lp - S[i]);
      return wEnd + (wMid - wEnd) * smooth(e / tl);
    };
    const L1 = [], R1 = [], Ws = [];
    for (let i = 0; i < n; i++) {
      let a, b;
      if (closedFull) { a = P[(i - 1 + n) % n]; b = P[(i + 1) % n]; }
      else { a = P[Math.max(0, i - 1)]; b = P[Math.min(n - 1, i + 1)]; }
      let tx = b[0] - a[0], ty = b[1] - a[1];
      const tlen = Math.hypot(tx, ty) || 1; tx /= tlen; ty /= tlen;
      const w = wid(i) / 2; Ws.push(w);
      L1.push([P[i][0] - ty * w, P[i][1] + tx * w]);
      R1.push([P[i][0] + ty * w, P[i][1] - tx * w]);
    }
    const f = (pt) => pt[0].toFixed(2) + "," + pt[1].toFixed(2);
    let d;
    if (closedFull) {
      d = "M" + L1.map(f).join("L") + "Z M" + R1.slice().reverse().map(f).join("L") + "Z";
    } else {
      const cap = (c, w, ang, from) => {
        const out = [];
        for (let k = 1; k <= 4; k++) { const a = ang + from - k * Math.PI / 5; out.push([c[0] + Math.cos(a) * w, c[1] + Math.sin(a) * w]); }
        return out;
      };
      const te = Math.atan2(P[n - 1][1] - P[n - 2][1], P[n - 1][0] - P[n - 2][0]);
      const ts = Math.atan2(P[1][1] - P[0][1], P[1][0] - P[0][0]);
      const endCap = cap(P[n - 1], Ws[n - 1], te, Math.PI / 2);
      const startCap = cap(P[0], Ws[0], ts, -Math.PI / 2);
      d = "M" + L1.map(f).join("L") + "L" + endCap.map(f).join("L") + "L" + R1.slice().reverse().map(f).join("L") +
        "L" + startCap.map(f).join("L") + "Z";
    }
    // round joints where the line turns sharply
    for (const j of sub.joints) {
      if (j <= 0 || j >= n - 1) continue;
      const a = P[j - 1], b = P[j], c = P[j + 1];
      const a1 = Math.atan2(b[1] - a[1], b[0] - a[0]), a2 = Math.atan2(c[1] - b[1], c[0] - b[0]);
      let da = Math.abs(a2 - a1); if (da > Math.PI) da = 2 * Math.PI - da;
      if (da < 0.5) continue;
      const r = Ws[j];
      d += "M" + (b[0] + r).toFixed(2) + "," + b[1].toFixed(2);
      for (let k = 1; k <= 8; k++) { const t = k / 8 * Math.PI * 2; d += "L" + (b[0] + Math.cos(t) * r).toFixed(2) + "," + (b[1] + Math.sin(t) * r).toFixed(2); }
      d += "Z";
    }
    return d;
  }

  function ik(base, target, l1, l2, pick) {
    const dx = target[0] - base[0], dy = target[1] - base[1];
    const d = Math.hypot(dx, dy);
    const dmax = l1 + l2 - 0.5, dmin = Math.abs(l1 - l2) + 0.5;
    const dc = clamp(d, dmin, dmax);
    const a = Math.atan2(dy, dx);
    const al = Math.acos(clamp((l1 * l1 + dc * dc - l2 * l2) / (2 * l1 * dc), -1, 1));
    const j1 = [base[0] + l1 * Math.cos(a + al), base[1] + l1 * Math.sin(a + al)];
    const j2 = [base[0] + l1 * Math.cos(a - al), base[1] + l1 * Math.sin(a - al)];
    const j = pick(j1, j2) ? j1 : j2;
    const end = d > dmax ? [base[0] + Math.cos(a) * dmax, base[1] + Math.sin(a) * dmax] : target;
    return [j, end];
  }

  // Damped spring that follows target(t) (an [x, y] function), integrated from t0 at rest.
  function spring(target, t0, t, k, c) {
    k = k || 260; c = c || 14;
    const dt = 1 / 240;
    let x = target(t0).slice(), v = [0, 0];
    for (let tt = t0; tt < t - 1e-9; tt += dt) {
      const h = Math.min(dt, t - tt);
      const g = target(tt + h);
      v[0] += (k * (g[0] - x[0]) - c * v[0]) * h; v[1] += (k * (g[1] - x[1]) - c * v[1]) * h;
      x[0] += v[0] * h; x[1] += v[1] * h;
    }
    return x;
  }

  // ---------- paper
  function drawPaper(canvas) {
    const ctx = canvas.getContext("2d");
    ctx.fillStyle = C.bg; ctx.fillRect(0, 0, W, H);
    const r = mulberry32(777);
    const img = ctx.getImageData(0, 0, W, H), d = img.data;
    for (let i = 0; i < d.length; i += 4) {
      const n = (r() - 0.5) * 6;
      d[i] += n; d[i + 1] += n; d[i + 2] += n;
    }
    ctx.putImageData(img, 0, 0);
  }

  // ---------- text
  const mctx = document.createElement("canvas").getContext("2d");
  function fontStr(size, weight) { return `${weight || 500} ${size}px ${FONT}`; }
  function measure(text, size, weight) { mctx.font = fontStr(size, weight); return mctx.measureText(text).width; }

  const NS = "http://www.w3.org/2000/svg";
  function el(tag, attrs) {
    const e = document.createElementNS(NS, tag);
    for (const k in attrs) if (attrs[k] != null) e.setAttribute(k, attrs[k]);
    return e;
  }

  // ---------- scene
  function scene(def) {
    const nominal = def.nominal;
    let duration = parseFloat(q.get("d")) || def.defaultDuration || nominal;
    const amp = def.boil == null ? 0.35 : def.boil;
    document.body.insertAdjacentHTML("beforeend",
      '<canvas id="paper" width="1920" height="1080"></canvas>' +
      '<svg id="stage" xmlns="http://www.w3.org/2000/svg" width="1920" height="1080" viewBox="0 0 1920 1080"></svg>' +
      '<div class="warm"><span class="a">Aa1</span><span class="b">Aa1</span></div>');
    const svg = document.getElementById("stage");
    let clipN = 0, cam = null, seedF = 0;

    const cm = (x, y) => cam ? [(x - cam.x) * cam.s + cam.ox + cam.dx, (y - cam.y) * cam.s + cam.oy + cam.dy] : [x, y];
    const cs = () => (cam ? cam.s : 1);
    const prog = (it, tn) => it.at == null ? 1 : clamp((tn - it.at) / Math.max(1e-4, it.dur || 0.0001));

    function popTransform(pop, tn, off, e) {
      const p = clamp((tn - pop.at) / Math.max(1e-4, pop.dur));
      if (p <= 0) return null;
      const s = Math.max(0.001, (e || ease.back)(p)), c = cm(pop.x + off[0], pop.y + off[1]);
      return `translate(${c[0].toFixed(2)},${c[1].toFixed(2)}) scale(${s.toFixed(4)}) translate(${(-c[0]).toFixed(2)},${(-c[1]).toFixed(2)})`;
    }

    function drawItem(parent, it, tn, f, idx, off) {
      if (it.screen && cam) { // pinned to the screen: draw without the camera
        const saved = cam; cam = null;
        try { drawItem(parent, Object.assign({}, it, { screen: false }), tn, f, idx, off); } finally { cam = saved; }
        return;
      }
      off = off || [0, 0];
      if (it.type === "group") {
        const o2 = it.move ? [off[0] + it.move[0], off[1] + it.move[1]] : off;
        let tr = "";
        if (it.rotate) { const c = cm(it.rotate.x + o2[0], it.rotate.y + o2[1]); tr += ` rotate(${it.rotate.deg.toFixed(3)} ${c[0].toFixed(2)} ${c[1].toFixed(2)})`; }
        if (it.scale) {
          const c = cm(it.scale.x + o2[0], it.scale.y + o2[1]), sx = it.scale.s, sy = it.scale.sy == null ? sx : it.scale.sy;
          tr += ` translate(${c[0]},${c[1]}) scale(${sx} ${sy}) translate(${-c[0]},${-c[1]})`;
        }
        if (it.pop) { const pt = popTransform(it.pop, tn, o2, it.pop.ease); if (!pt) return; tr += " " + pt; }
        const g = el("g", { transform: tr || null, opacity: it.opacity != null ? it.opacity : null });
        parent.appendChild(g);
        let target = g;
        if (it.clip) {
          const id = "k" + (++clipN);
          const cp = el("clipPath", { id });
          cp.appendChild(el("path", { d: cmdsToD(mapCmds(translateCmds(it.clip, off[0], off[1]), cm)) }));
          g.appendChild(cp);
          target = el("g", { "clip-path": `url(#${id})` });
          g.appendChild(target);
        }
        it.items.forEach((c, i) => drawItem(target, c, tn, f, idx * 131 + i + 1, o2));
        return;
      }
      if (it.text != null) return drawText(parent, it, tn, f, idx, off);
      const p = prog(it, tn);
      if (p <= 0) return;
      const g = el("g", { opacity: it.opacity != null ? it.opacity : null });
      if (it.pop) { const pt = popTransform(it.pop, tn, off); if (!pt) return; g.setAttribute("transform", pt); }
      let target = g;
      if (it.clipW) {
        const id = "c" + (++clipN), cw = it.clipW, c0 = cm(cw.x + off[0], cw.y + off[1]);
        const cp = el("clipPath", { id });
        cp.appendChild(el("rect", { x: c0[0], y: c0[1], width: Math.max(0.1, cw.w * cs() * clamp(cw.p)), height: cw.h * cs() }));
        g.appendChild(cp);
        target = el("g", { "clip-path": `url(#${id})` });
        g.appendChild(target);
      }
      let cmds = it.cmds;
      if (off[0] || off[1]) cmds = translateCmds(cmds, off[0], off[1]);
      if (cam) cmds = mapCmds(cmds, cm);
      cmds = jitterCmds(cmds, it.boil == null ? amp : it.boil, hash(seedF, idx, 17));
      if (it.fill) {
        let fp = 1;
        const fillAt = it.fillAt != null ? it.fillAt : (it.at != null ? it.at + (it.dur || 0) : null);
        if (fillAt != null) fp = it.fillSnap ? (tn >= fillAt ? 1 : 0) : clamp((tn - fillAt) / 0.17 + 0.5);
        if (fp > 0) target.appendChild(el("path", { d: cmdsToD(cmds), fill: it.fill, "fill-opacity": (it.fillOpacity == null ? 1 : it.fillOpacity) * fp }));
      }
      if (it.stroke !== null) {
        const wMid = it.width || 7, wEnd = it.wEnd || wMid * 0.64;
        let d = "";
        const ph = (idx % 7) * 0.9;
        for (const sub of flatten(cmds, 3)) d += strokeOutline(sub, wMid, it.taper === false ? wMid : wEnd, ease.draw(p), ph);
        if (d) target.appendChild(el("path", { d, fill: it.stroke || C.line, "fill-opacity": it.strokeOpacity != null ? it.strokeOpacity : null }));
      }
      parent.appendChild(g);
    }

    function drawText(parent, it, tn, f, idx, off) {
      const p = prog(it, tn);
      if (p <= 0) return;
      const mode = it.mode || "words";
      let s = it.text, op = 1;
      if (mode === "words") {
        const words = it.text.split(" ");
        s = words.slice(0, Math.ceil(p * words.length - 1e-6)).join(" ");
      } else if (mode === "type") s = it.text.slice(0, Math.floor(p * it.text.length + 1e-6));
      else if (mode === "fade") op = ease.out(p);
      const ja = it.jit == null ? 0.3 : it.jit;
      const jx = sym(seedF, idx, 31) * ja, jy = sym(seedF, idx, 37) * ja;
      let x = it.x + off[0];
      const wt = it.weight || 500;
      if (it.anchor === "middle") x -= measure(it.text, it.size, wt) / 2;
      else if (it.anchor === "end") x -= measure(it.text, it.size, wt);
      const size = it.size * cs();
      const [X, Y] = cm(x, it.y + off[1]);
      const t = el("text", {
        x: (X + jx).toFixed(2), y: (Y + jy).toFixed(2), "font-family": FONT,
        "font-size": size.toFixed(2), "font-weight": wt, fill: it.fill || C.line, opacity: op * (it.opacity == null ? 1 : it.opacity),
      });
      t.textContent = s;
      parent.appendChild(t);
    }

    function renderAt(t) {
      const f = Math.round(t * FPS);
      seedF = Math.floor(f / 2);
      const tn = t * nominal / duration;
      while (svg.firstChild) svg.removeChild(svg.firstChild);
      clipN = 0;
      const shots = def.shots;
      let shot = shots[shots.length - 1];
      for (const s of shots) if (tn >= s.start && tn < s.end) { shot = s; break; }
      cam = shot.camera ? Object.assign({ x: 960, y: 540, s: 1, ox: 960, oy: 540, dx: 0, dy: 0 }, shot.camera(tn, f)) : null;
      const items = shot.build(tn, f);
      const root = el("g", {});
      svg.appendChild(root);
      items.forEach((it, i) => drawItem(root, it, tn, f, i + 1, [0, 0]));
      return f;
    }

    window.renderAt = renderAt;
    window.setDuration = (d) => { duration = d; };
    window.sceneInfo = () => ({ duration, nominal, fps: FPS });

    Promise.all([
      document.fonts.load('500 40px "Shantell Sans"'),
      document.fonts.load('650 40px "Shantell Sans"'),
    ]).then(() => document.fonts.ready).then(() => {
      if (def.transparent) {
        document.documentElement.style.background = "transparent";
        document.body.style.background = "transparent";
      } else drawPaper(document.getElementById("paper"));
      if (def.init) def.init(document.getElementById("paper"));
      const t0 = q.get("t") != null ? parseFloat(q.get("t")) : duration;
      renderAt(t0);
      window.sceneReady = true;
    }).catch((e) => { window.sceneError = String(e && e.stack || e); console.error(e); });
  }

  window.Line = {
    scene, C, D2R, ease, clamp, lerp, smooth, rnd, sym, hash, spring,
    curve, poly, blob, rrect, mapCmds, rotateCmds, translateCmds, scaleCmds, ik, measure, FPS,
  };
})();
