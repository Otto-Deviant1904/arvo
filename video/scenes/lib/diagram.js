/* Arvo video: shared helpers for the diagram scenes (s01, s09, s10, s11, s12, s14).
 * Builds on lib/line.js (Line) and lib/mel.js (Mel); does not change them.
 *
 * Timing:   D.key(tn, [[t, v, ease], ...])  keyframes (numbers or arrays)
 *           D.settle(tn, t0, f, d)          0 -> 1 with overshoot and settle (damped spring)
 *           D.wob(tn, t0, amp, f, d)        damped wobble around 0 (follow-through, impact shake)
 *           D.p(tn, t0, dur, ease)          clamped, eased progress
 * Shapes:   D.place(items, {x, y, s, sx, sy, rot, px, py})  local -> world (line widths stay one brush)
 *           squash on text: group scale {s: sx, sy, x, y} (line.js)
 *           D.gem(o), D.guard(o), D.gear(...), D.cross(...), D.tick(...), D.flag(...), D.lock(...), ...
 * Mel:      D.follow(poseFn, t0, tn, P0)    ponytail / lanyard springs (as in s02)
 */
(function () {
  "use strict";
  const L = window.Line, C = L.C, D2R = L.D2R;
  const D = {};

  // ---------------- timing
  D.p = (tn, t0, dur, e) => { const p = L.clamp((tn - t0) / Math.max(1e-4, dur)); return e ? (typeof e === "function" ? e : L.ease[e])(p) : p; };
  D.key = function (tn, keys) {
    if (tn <= keys[0][0]) return keys[0][1];
    for (let i = 1; i < keys.length; i++) {
      if (tn < keys[i][0]) {
        const a = keys[i - 1], b = keys[i];
        const ef = typeof b[2] === "function" ? b[2] : (L.ease[b[2] || "inOut"] || L.ease.inOut);
        const e = ef((tn - a[0]) / (b[0] - a[0]));
        return Array.isArray(a[1]) ? a[1].map((v, j) => L.lerp(v, b[1][j], e)) : L.lerp(a[1], b[1], e);
      }
    }
    return keys[keys.length - 1][1];
  };
  D.settle = function (tn, t0, f, d) {
    const t = tn - t0;
    if (t <= 0) return 0;
    f = f || 2.2; d = d || 7;
    return 1 - Math.exp(-d * t) * Math.cos(2 * Math.PI * f * t);
  };
  D.wob = function (tn, t0, amp, f, d) {
    const t = tn - t0;
    if (t <= 0) return 0;
    return amp * Math.exp(-(d || 5) * t) * Math.sin(2 * Math.PI * (f || 2.5) * t);
  };
  // pop scale with squash: returns {s, sx, sy}; 0 before t0
  D.popS = function (tn, t0, o) {
    o = o || {};
    const s = Math.max(0, D.settle(tn, t0, o.f || 2.3, o.d || 8));
    const w = D.wob(tn, t0 + 0.05, o.sq == null ? 0.16 : o.sq, o.f2 || 3.2, o.d2 || 7);
    return { s, sx: s * (1 + w), sy: s * (1 - w) };
  };
  D.within = (tn, times, d) => times.some((t0) => tn >= t0 && tn < t0 + d);

  // ---------------- geometry
  function bake(items, dx, dy) {
    dx = dx || 0; dy = dy || 0;
    return items.map((it) => {
      if (it.type === "group") {
        const mx = dx + (it.move ? it.move[0] : 0), my = dy + (it.move ? it.move[1] : 0);
        const g = Object.assign({}, it, { items: bake(it.items, mx, my) });
        delete g.move;
        // clip / pop / rotate / scale refer to the parent's frame plus this group's move
        if (it.clip) g.clip = L.translateCmds(it.clip, dx, dy);
        if (it.pop) g.pop = Object.assign({}, it.pop, { x: it.pop.x + mx, y: it.pop.y + my });
        if (it.rotate) g.rotate = Object.assign({}, it.rotate, { x: it.rotate.x + mx, y: it.rotate.y + my });
        if (it.scale) g.scale = Object.assign({}, it.scale, { x: it.scale.x + mx, y: it.scale.y + my });
        return g;
      }
      if (!dx && !dy) return it;
      if (it.text != null) return Object.assign({}, it, { x: it.x + dx, y: it.y + dy });
      const o = Object.assign({}, it, { cmds: L.translateCmds(it.cmds, dx, dy) });
      if (it.pop) o.pop = Object.assign({}, it.pop, { x: it.pop.x + dx, y: it.pop.y + dy });
      if (it.clipW) o.clipW = Object.assign({}, it.clipW, { x: it.clipW.x + dx, y: it.clipW.y + dy });
      return o;
    });
  }
  function mapItems(items, f, k) {
    const fp = (x, y) => f([x, y]);
    return items.map((it) => {
      if (it.type === "group") {
        const g = Object.assign({}, it, { items: mapItems(it.items, f, k) });
        if (it.clip) g.clip = L.mapCmds(it.clip, fp);
        if (it.pop) { const p = f([it.pop.x, it.pop.y]); g.pop = Object.assign({}, it.pop, { x: p[0], y: p[1] }); }
        if (it.rotate) { const p = f([it.rotate.x, it.rotate.y]); g.rotate = Object.assign({}, it.rotate, { x: p[0], y: p[1] }); }
        if (it.scale) { const p = f([it.scale.x, it.scale.y]); g.scale = Object.assign({}, it.scale, { x: p[0], y: p[1] }); }
        return g;
      }
      if (it.text != null) { const p = f([it.x, it.y]); return Object.assign({}, it, { x: p[0], y: p[1], size: it.size * k }); }
      const o = Object.assign({}, it, { cmds: L.mapCmds(it.cmds, fp) });
      if (it.pop) { const p = f([it.pop.x, it.pop.y]); o.pop = Object.assign({}, it.pop, { x: p[0], y: p[1] }); }
      return o;
    });
  }
  D.aff = function (o) {
    const s = o.s == null ? 1 : o.s;
    const sx = (o.sx == null ? 1 : o.sx) * s, sy = (o.sy == null ? 1 : o.sy) * s;
    const r = (o.rot || 0) * D2R, co = Math.cos(r), si = Math.sin(r);
    const px = o.px || 0, py = o.py || 0, X = o.x || 0, Y = o.y || 0;
    const f = ([x, y]) => { const u = (x - px) * sx, v = (y - py) * sy; return [X + u * co - v * si, Y + u * si + v * co]; };
    f.k = Math.sqrt(Math.abs(sx * sy));
    return f;
  };
  // local items -> world. The local pivot (px, py) lands on (x, y).
  D.place = function (items, o) { const f = D.aff(o); return mapItems(bake(items), f, f.k); };
  D.mapItems = (items, f, k) => mapItems(bake(items), f, k == null ? 1 : k);
  D.bake = bake;

  D.circle = (x, y, r, seed) => L.blob(x, y, r, r, seed || 5, 0.015);
  D.rect = (x, y, w, h, r, seed) => L.rrect(x, y, w, h, r == null ? 14 : r, seed || 7, 1.2);
  D.line = (pts) => L.curve(pts, false, 0.6);
  // a wavy "text line" for paper props
  D.scribble = function (x, y, w, seed, amp) {
    const pts = [], n = Math.max(3, Math.round(w / 22));
    for (let i = 0; i <= n; i++) pts.push([x + (w * i) / n, y + Math.sin(i * 1.9 + (seed || 0)) * (amp == null ? 3 : amp)]);
    return L.curve(pts, false, 0.8);
  };

  // ---------------- props
  // cross (two strokes drawn on from p0)
  D.cross = function (x, y, r, color, t0, o) {
    o = o || {};
    const w = o.width || 13, d = o.dur || 0.14;
    return [
      { cmds: L.curve([[x - r, y - r], [x - r * 0.05, y + r * 0.02], [x + r, y + r]]), stroke: color, width: w, wEnd: w * 0.55, at: t0, dur: d },
      { cmds: L.curve([[x + r * 0.96, y - r * 1.02], [x + r * 0.02, y - r * 0.02], [x - r * 0.98, y + r]]), stroke: color, width: w, wEnd: w * 0.55, at: t0 + d * 1.15, dur: d },
    ];
  };
  D.tick = function (x, y, r, color, t0, o) {
    o = o || {};
    const w = o.width || 13;
    return [{ cmds: L.curve([[x - r, y - r * 0.05], [x - r * 0.62, y + r * 0.28], [x - r * 0.3, y + r * 0.62], [x + r * 0.3, y - r * 0.2], [x + r * 1.05, y - r * 0.95]], false, 0.5),
      stroke: color, width: w, wEnd: w * 0.55, at: t0, dur: o.dur || 0.22 }];
  };
  D.flag = function (x, y, h, tn, o) {
    o = o || {};
    const top = y - h, wa = o.wave == null ? 4 : o.wave, w = Math.sin(tn * 6 + (o.ph || 0)) * wa, fw = o.fw || h * 0.6, fh = o.fh || h * 0.38;
    return [
      { cmds: L.curve([[x, y], [x + 1, y - h * 0.5], [x, top]]), width: o.width || 6 },
      { cmds: [["M", x, top], ["C", x + fw * 0.3, top - fh * 0.22 + w * 0.3, x + fw * 0.65, top + fh * 0.18 + w * 0.6, x + fw, top - fh * 0.05 + w],
        ["L", x + fw * 0.97, top + fh + w], ["C", x + fw * 0.65, top + fh * 1.18 + w * 0.6, x + fw * 0.32, top + fh * 0.76 + w * 0.3, x + 1, top + fh], ["Z"]],
        fill: C.red, width: (o.width || 6) * 0.85 },
    ];
  };
  D.lock = function (x, y, s, color, o) {
    o = o || {};
    const bw = 64 * s, bh = 52 * s, open = o.open || 0;
    const sh = L.curve([[x - bw * 0.3, y - bh * 0.5], [x - bw * 0.31, y - bh * 1.05], [x, y - bh * 1.32], [x + bw * 0.31, y - bh * 1.05], [x + bw * 0.3, y - bh * 0.5 - open * 26 * s]], false, 0.9);
    return [
      { cmds: L.translateCmds(sh, 0, -open * 18 * s), stroke: o.stroke || color, width: (o.width || 7) },
      { cmds: L.rrect(x - bw / 2, y - bh / 2, bw, bh, 9 * s, 44, 0.8), fill: color, stroke: o.stroke || color, width: (o.width || 7) * 0.8 },
      { cmds: L.blob(x, y - 2 * s, 6 * s, 6 * s, 45, 0.02), fill: o.hole || C.bg, stroke: null },
      { cmds: L.poly([[x, y + 2 * s], [x, y + 13 * s]]), stroke: o.hole || C.bg, width: 5 * s, taper: false },
    ];
  };
  // gear with n teeth, outer radius r; rot in degrees
  D.gear = function (cx, cy, r, n, rot, o) {
    o = o || {};
    const pts = [], ht = o.ht || r * 0.2, a0 = rot * D2R;
    for (let i = 0; i < n; i++) {
      const a = a0 + (i / n) * Math.PI * 2, da = (Math.PI * 2) / n;
      const ri = r - ht;
      [[ri, -0.5], [ri, -0.26], [r, -0.17], [r, 0.17], [ri, 0.26]].forEach(([rr, f]) => {
        pts.push([cx + Math.cos(a + f * da) * rr, cy + Math.sin(a + f * da) * rr]);
      });
    }
    return [
      { cmds: L.poly(pts, true), fill: o.fill || C.bg, fillOpacity: o.fillOpacity, width: o.width || 6, boil: 0.25 },
      { cmds: L.blob(cx, cy, r * 0.3, r * 0.3, 9, 0.01), width: (o.width || 6) * 0.8, fill: o.hub || null },
    ].concat([0, 1, 2].map((k) => {
      const a = a0 + (k / 3) * Math.PI * 2 + 0.5, rr = (r - ht) * 0.62;
      return { cmds: L.blob(cx + Math.cos(a) * rr, cy + Math.sin(a) * rr, r * 0.1, r * 0.1, 30 + k, 0.02), width: 4.2, taper: false };
    }));
  };
  D.cloud = function (x, y, s, o) {
    o = o || {};
    const P = (u, v) => [x + u * s, y + v * s];
    const cmds = [["M", ...P(-1.3, 0.5)], ["C", ...P(-1.75, 0.5), ...P(-1.8, -0.15), ...P(-1.2, -0.12)],
      ["C", ...P(-1.15, -0.75), ...P(-0.35, -0.85), ...P(-0.15, -0.4)], ["C", ...P(0.1, -1.05), ...P(1.1, -0.95), ...P(1.05, -0.2)],
      ["C", ...P(1.65, -0.25), ...P(1.75, 0.5), ...P(1.25, 0.5)], ["Z"]];
    return [{ cmds, fill: o.fill || C.bg, fillOpacity: o.fillOpacity, width: o.width || 7 }];
  };
  D.bars = function (x, y, s, lit, o) {
    o = o || {};
    const out = [];
    for (let i = 0; i < 4; i++) {
      const h = (18 + i * 16) * s, bx = x + i * 26 * s;
      out.push({ cmds: L.rrect(bx, y - h, 16 * s, h, 4 * s, 60 + i, 0.6), fill: i < lit ? C.line : C.bg, width: o.width || 5.5 });
    }
    return out;
  };
  D.magnifier = function (x, y, r, o) {
    o = o || {};
    const a = (o.handle == null ? 45 : o.handle) * D2R;
    return [
      { cmds: L.blob(x, y, r, r, 81, 0.012), fill: C.line, fillOpacity: o.glass == null ? 0.07 : o.glass, width: o.width || 8 },
      { cmds: L.poly([[x + Math.cos(a) * (r + 4), y + Math.sin(a) * (r + 4)], [x + Math.cos(a) * (r + 62), y + Math.sin(a) * (r + 62)]]), width: (o.width || 8) * 1.7, wEnd: (o.width || 8) * 1.3 },
      { cmds: L.curve([[x - r * 0.55, y - r * 0.2], [x - r * 0.45, y - r * 0.5], [x - r * 0.18, y - r * 0.6]]), width: 4.5, strokeOpacity: 0.7 },
    ];
  };
  // four-point twinkle star
  D.star = function (x, y, s, o) {
    o = o || {};
    const c = o.color || C.line, w = o.width || 3.8;
    return [{ cmds: L.poly([[x - s, y], [x + s, y]]), stroke: c, width: w, wEnd: w * 0.6 },
      { cmds: L.poly([[x, y - s], [x, y + s]]), stroke: c, width: w, wEnd: w * 0.6 }];
  };

  // ---------------- the arvo icon: a low afternoon sun over a tiny invoice sheet
  // (x, y) = centre of the sheet's top edge; s = scale; rise 0..1 = sun up; tn for ray shimmer
  D.sunSheet = function (x, y, s, tn, o) {
    o = o || {};
    const rise = o.rise == null ? 1 : o.rise, sheet = o.sheet == null ? 1 : o.sheet;
    const out = [];
    const sw = 130 * s, sh = 156 * s, R = 50 * s;
    const sy = y + 10 * s - rise * 30 * s;
    // sun (behind the sheet); rays slowly turn and breathe
    if (rise > 0) {
      const g = [];
      const rays = 9, rot = tn * 9;
      for (let i = 0; i < rays; i++) {
        const a = (-180 + 10 + (i * 160) / (rays - 1) + Math.sin(tn * 0.7) * 2) * D2R;
        const k = 1 + 0.08 * Math.sin(tn * 3.1 + i * 1.3);
        const r0 = R + 14 * s, r1 = R + (30 + (i % 2) * 10) * s * k * rise;
        g.push({ cmds: L.poly([[x + Math.cos(a) * r0, sy + Math.sin(a) * r0], [x + Math.cos(a) * r1, sy + Math.sin(a) * r1]]), stroke: C.amber, width: 6 * Math.max(0.6, s), wEnd: 3.5 });
      }
      void rot;
      g.push({ cmds: L.blob(x, sy, R, R, 17, 0.015), fill: C.amber, stroke: C.amber, width: 5 });
      out.push({ type: "group", items: g, clip: [["M", x - 400 * s, y - 400 * s], ["L", x + 400 * s, y - 400 * s], ["L", x + 400 * s, y + 4 * s], ["L", x - 400 * s, y + 4 * s], ["Z"]] });
    }
    if (sheet > 0) {
      const fold = 30 * s, x0 = x - sw / 2, x1 = x + sw / 2;
      const body = [["M", x0, y], ["L", x1 - fold, y], ["L", x1, y + fold], ["L", x1, y + sh], ["L", x0, y + sh], ["Z"]];
      const g = [
        { cmds: body, fill: C.bg, width: 6.5 },
        { cmds: L.poly([[x1 - fold, y], [x1 - fold + 2, y + fold - 2], [x1, y + fold]]), width: 5 },
        { cmds: D.scribble(x0 + 20 * s, y + 46 * s, 62 * s, 1, 2 * s), width: 4.6 },
        { cmds: D.scribble(x0 + 20 * s, y + 74 * s, 86 * s, 2, 2 * s), width: 4.6 },
        { cmds: D.scribble(x0 + 20 * s, y + 102 * s, 74 * s, 3, 2 * s), width: 4.6 },
        { cmds: L.poly([[x0 + 58 * s, y + 132 * s], [x1 - 18 * s, y + 132 * s]]), stroke: C.amber, width: 6, taper: false },
      ];
      out.push({ type: "group", items: g });
    }
    return out;
  };

  // ---------------- Gemma, the gem character
  // o: {x, y = centre, r = half width, sx, sy, rot, px, py (pivot, local), look [-1..1, -1..1], blink,
  //     mood: 'smile' | 'flat' | 'wince' | 'oops' | 'happy' | 'o', arms: {l, r} world hand targets, legs, tn}
  D.GEM = [[-0.56, -0.62], [0.56, -0.62], [1, -0.16], [0, 0.98], [-1, -0.16]];
  D.gem = function (o) {
    const r = o.r || 90, tn = o.tn || 0;
    const P = (x, y) => [x * r, y * r];
    const body = [];
    const out = [];
    const outline = D.GEM.map(([x, y]) => P(x, y));
    const legs = o.legs ? 0.32 : 0;
    if (legs) {
      const lk = o.legKick || 0;
      [[-1, 0], [1, 1]].forEach(([sd, i]) => {
        const hx = sd * 0.16, kk = i === 1 ? lk : 0;
        body.push({ cmds: L.curve([P(hx, 0.78), P(hx + sd * 0.04, 0.98 + legs * 0.5), P(hx + sd * 0.06 + kk * 0.1, 0.98 + legs - kk * 0.08)]), width: 6 });
        body.push({ cmds: L.curve([P(hx + sd * 0.06 + kk * 0.1, 0.98 + legs - kk * 0.08), P(hx + sd * 0.22 + kk * 0.1, 0.98 + legs - kk * 0.1)]), width: 6 });
      });
    }
    body.push({ cmds: L.poly(outline, true), fill: C.bg, stroke: null, boil: 0.2 });
    body.push({ cmds: L.poly(outline, true), fill: C.amber, fillOpacity: o.tint == null ? 0.16 : o.tint, width: 7 });
    body.push({ cmds: L.poly([P(-0.97, -0.16), P(0.97, -0.16)]), width: 5 });
    body.push({ cmds: L.poly([P(-0.2, -0.6), P(-0.42, -0.18)]), width: 4.4 });
    body.push({ cmds: L.poly([P(0.2, -0.6), P(0.42, -0.18)]), width: 4.4 });
    body.push({ cmds: L.poly([P(-0.42, -0.14), P(-0.08, 0.86)]), width: 4, strokeOpacity: 0.4 });
    body.push({ cmds: L.poly([P(0.42, -0.14), P(0.08, 0.86)]), width: 4, strokeOpacity: 0.4 });
    // face
    const lk = o.look || [0, 0];
    const ex = 0.19, ey = 0.1 + lk[1] * 0.05, ox = lk[0] * 0.07;
    const mood = o.mood || "smile";
    [-1, 1].forEach((sd) => {
      const cx = sd * ex + ox, cy = ey;
      if (mood === "wince") {
        body.push({ cmds: L.poly([P(cx - sd * 0.07, cy - 0.06), P(cx + sd * 0.05, cy), P(cx - sd * 0.07, cy + 0.06)]), width: 5, taper: false });
      } else if (mood === "happy") {
        body.push({ cmds: L.curve([P(cx - 0.07, cy + 0.03), P(cx, cy - 0.05), P(cx + 0.07, cy + 0.03)]), width: 5.5 });
      } else if (o.blink) {
        body.push({ cmds: L.curve([P(cx - 0.07, cy), P(cx, cy + 0.025), P(cx + 0.07, cy)]), width: 5 });
      } else {
        const er = (o.eyeR || 0.072) * r;
        body.push({ cmds: L.blob(cx * r, cy * r, er, er * 1.1, 70 + sd, 0.03), fill: C.line, stroke: null });
      }
    });
    if (o.brows) {
      const b = o.brows; // + = worried (inner up)
      [-1, 1].forEach((sd) => body.push({ cmds: L.poly([P(sd * ex + ox - 0.08, ey - 0.16 + sd * b * 0.04), P(sd * ex + ox + 0.08, ey - 0.16 - sd * b * 0.04)]), width: 4.5 }));
    }
    const my = 0.33 + lk[1] * 0.03, mx = ox * 0.8;
    if (mood === "o") body.push({ cmds: L.blob(mx * r, my * r, 0.06 * r, 0.075 * r, 80, 0.04), width: 4.6, taper: false });
    else if (mood === "oops") body.push({ cmds: L.curve([P(mx - 0.11, my + 0.02), P(mx - 0.05, my - 0.02), P(mx, my + 0.02), P(mx + 0.05, my - 0.02), P(mx + 0.11, my + 0.02)]), width: 4.6 });
    else if (mood === "flat") body.push({ cmds: L.poly([P(mx - 0.08, my), P(mx + 0.08, my)]), width: 4.8 });
    else if (mood === "wince") body.push({ cmds: L.curve([P(mx - 0.1, my + 0.03), P(mx, my - 0.03), P(mx + 0.1, my + 0.03)]), width: 4.8 });
    else body.push({ cmds: L.curve([P(mx - 0.11, my - 0.02), P(mx, my + 0.07), P(mx + 0.11, my - 0.02)]), width: 5 });
    // sparkle (secondary motion)
    if (o.sparkle !== false) {
      const u = ((tn + (o.ph || 0)) % 2.6) / 2.6;
      const k = u < 0.2 ? Math.sin((u / 0.2) * Math.PI) : 0;
      if (k > 0.02) body.push(...D.star(0.78 * r, -0.8 * r, 14 * k + 2, { width: 4 }));
    }
    const f = D.aff({ x: o.x, y: o.y, sx: o.sx, sy: o.sy, rot: o.rot, px: o.px, py: o.py });
    const placed = mapItems(body, f, f.k);
    // arms (world coords, drawn behind body)
    if (o.arms) {
      ["l", "r"].forEach((side) => {
        const h = o.arms[side];
        if (!h) return;
        const sd = side === "l" ? -1 : 1;
        const sh = f(P(sd * 0.9, -0.08));
        const mid = [(sh[0] + h[0]) / 2 + sd * 10, (sh[1] + h[1]) / 2 + 16];
        out.push({ cmds: L.curve([sh, mid, h], false, 0.9), width: 6.5 });
      });
    }
    out.push(...placed);
    out.rig = { f, top: f(P(0, -0.62)), tip: f(P(0, 0.98)), shoulderL: f(P(-0.9, -0.08)), shoulderR: f(P(0.9, -0.08)), eyes: f(P(ox, ey)) };
    return out;
  };

  // ---------------- the guardrail: a fence post with eyebrows (and a clipboard)
  // o: {x, y = ground centre, h, w, rot (lean), sx, sy, stern 0..1, look, blink, mouth (-1 frown .. 1 smile),
  //     arms: {l, r} world hand targets, clip (bool): clipboard in left hand}
  D.guard = function (o) {
    const h = o.h || 300, w = o.w || 96;
    const body = [];
    // rail stubs behind the post
    [[-0.74, 0], [-0.34, 1]].forEach(([fy, i]) => {
      const y0 = fy * h, rh = 30, x0 = w / 2 - 6, x1 = w / 2 + 84;
      const zig = [[x1, y0], [x1 - 10, y0 + rh * 0.3], [x1 + 4, y0 + rh * 0.6], [x1 - 6, y0 + rh]];
      body.push({ cmds: L.poly([[x0, y0], ...zig, [x0, y0 + rh]], true), fill: C.bg, width: 5.5 });
      void i;
    });
    const top = -h, pt = -h - w * 0.42;
    const post = [[-w / 2, 0], [-w / 2, top], [0, pt], [w / 2, top], [w / 2, 0]];
    body.push({ cmds: L.poly(post, true), fill: C.body, width: 7 });
    body.push({ cmds: L.curve([[-w * 0.22, -h * 0.42], [-w * 0.18, -h * 0.3], [-w * 0.24, -h * 0.16]]), width: 4, strokeOpacity: 0.45 });
    body.push({ cmds: L.curve([[w * 0.2, -h * 0.22], [w * 0.24, -h * 0.12], [w * 0.19, -h * 0.04]]), width: 4, strokeOpacity: 0.45 });
    body.push({ cmds: L.blob(w * 0.18, -h * 0.5, 5, 7, 3, 0.05), width: 3.8, strokeOpacity: 0.45 });
    // face
    const lk = o.look || [0, 0];
    const fy = -h * 0.78 + lk[1] * 4, ox = lk[0] * 9;
    const st = o.stern == null ? 1 : o.stern;
    [-1, 1].forEach((sd) => {
      const ex = sd * w * 0.2 + ox;
      if (o.blink) body.push({ cmds: L.poly([[ex - 8, fy], [ex + 8, fy]]), width: 5 });
      else body.push({ cmds: L.blob(ex, fy, 6.5, 7.2, 90 + sd, 0.03), fill: C.line, stroke: null });
      // brows: stern = inner ends pulled down hard
      const inner = [ex - sd * 13, fy - 15 + st * 9 - (1 - st) * 2], outer = [ex + sd * 13, fy - 22 - st * 4];
      body.push({ cmds: L.curve([inner, [ex, (inner[1] + outer[1]) / 2 - 2], outer]), width: 8, wEnd: 4.5 });
    });
    const m = o.mouth == null ? -0.4 : o.mouth, my = fy + 34;
    body.push({ cmds: L.curve([[ox - 14, my - m * 3], [ox, my + m * 7], [ox + 14, my - m * 3]]), width: 5 });
    const f = D.aff({ x: o.x, y: o.y, sx: o.sx, sy: o.sy, rot: o.rot });
    const out = [];
    const placed = mapItems(body, f, f.k);
    out.push(...placed);
    if (o.arms) {
      ["l", "r"].forEach((side) => {
        const hd = o.arms[side];
        if (!hd) return;
        const sd = side === "l" ? -1 : 1;
        const sh = f([sd * w * 0.5, -h * 0.46]);
        const mid = [(sh[0] + hd[0]) / 2 + sd * 6, (sh[1] + hd[1]) / 2 + 20];
        out.push({ cmds: L.curve([sh, mid, hd], false, 0.9), width: 6.5 });
      });
    }
    out.rig = { f, head: f([0, fy]), top: f([0, pt]) };
    return out;
  };

  // a rubber stamp; (x, y) = bottom centre of the stamp face
  D.stamp = function (x, y, rot, o) {
    o = o || {};
    const it = [
      { cmds: L.rrect(x - 44, y - 30, 88, 30, 6, 51, 0.8), fill: C.body, width: 6 },
      { cmds: L.poly([[x - 40, y - 2], [x + 40, y - 2]]), stroke: C.red, width: 7, taper: false },
      { cmds: L.poly([[x, y - 30], [x, y - 72]]), width: 11, taper: false },
      { cmds: L.blob(x, y - 88, 21, 19, 52, 0.03), fill: C.body, width: 6 },
    ];
    return [{ type: "group", rotate: { deg: rot || 0, x, y: y - 40 }, items: it }];
  };

  // ---------------- Mel follow-through (copied from s02 so the motion matches)
  D.follow = function (poseFn, t0, tn, P0) {
    const head = (t) => Mel.rig(poseFn(t), t).HC;
    const card = (t) => Mel.rig(poseFn(t), t).cardAnchor;
    const g = Mel.rig(P0, tn);
    const ph = L.spring(head, t0, tn, 300, 13), pc = L.spring(card, t0, tn, 150, 8);
    const lim = (v, m) => { const l = Math.hypot(v[0], v[1]); return l > m ? [v[0] / l * m, v[1] / l * m] : v; };
    P0.ponyD = lim([(ph[0] - g.HC[0]) * 1.6, (ph[1] - g.HC[1]) * 1.6], 46);
    P0.cardD = lim([pc[0] - g.cardAnchor[0], (pc[1] - g.cardAnchor[1]) * 0.6], 26);
    return P0;
  };

  // big number text that counts up; returns the string
  D.count = function (tn, t0, dur, target, fmt) {
    const p = L.clamp((tn - t0) / dur);
    const v = target * L.ease.out(p);
    return fmt ? fmt(v, p) : String(Math.round(v));
  };

  window.Diagram = D;
})();
