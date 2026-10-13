/* Arvo video: reusable doodle props in the line style (depends on line.js).
 * Every function returns an array of line items (or one group item) in world px.
 * Optional `t` = {at, dur} draws the prop on; omit for fully drawn.
 *
 *   Props.tag(x, y, text, {size, fill, angle, string})   luggage tag hanging from (x, y), swings by angle
 *   Props.clock(cx, cy, r, hourDeg, minDeg)               wall clock; 0 deg = 12 o'clock
 *   Props.laptopSide(x, y, s)                             laptop on a table seen from the side (lid towards the user on the left)
 *   Props.laptopFront(x, y, w, h)                         laptop from the front; screen = (x, y, w, h)
 *   Props.padlock(cx, cy, s, open, fill)                  open 0..1 lifts the shackle
 *   Props.envelope(cx, cy, w, h, rot)
 *   Props.building(x, y, w, h, {floors, cols})            x, y = top-left; ground at y + h
 *   Props.coin(cx, cy, r)
 *   Props.jar(cx, bottomY, w, h)
 *   Props.paper(x, y, w, h, {lines, rot, fill})
 *   Props.calendar(x, y, w, h)                            desk calendar frame (rings + stand); page drawn by caller
 *   Props.door(x, y, w, h)                                front door; ground at y + h
 *   Props.car(x, groundY, s)                              small hatchback facing right; x = rear
 *   Props.scissors(cx, cy, s, openDeg, rot)
 *   Props.cross(cx, cy, w, h, t1, t2)                     red scribbled cross, strokes drawn on at t1 / t2
 *   Props.chair(x, groundY, s, facing)                    side-view chair; facing 1 = seat to the right
 */
(function () {
  "use strict";
  const L = window.Line, C = L.C, D2R = L.D2R;
  const T = (it, t, k, n) => {
    if (t && t.at != null) { const d = t.dur || 0.4; it.at = t.at + d * (k / n); it.dur = d / n * 1.3; }
    return it;
  };

  function tag(x, y, text, o) {
    o = o || {};
    const size = o.size || 40, wt = o.weight || 650;
    const tw = L.measure(text, size, wt), w = tw + size * 1.3, h = size * 1.55, str = o.string == null ? 46 : o.string;
    const top = y + str;
    const items = [
      { cmds: L.curve([[x, y], [x + 2, y + str * 0.5], [x, top + 10]]), width: 4, wEnd: 2.6 },
      { cmds: [["M", x - w / 2 + 16, top], ["L", x + w / 2 - 6, top + 2], ["Q", x + w / 2 + 2, top + 2, x + w / 2 + 2, top + 12],
        ["L", x + w / 2, top + h - 8], ["Q", x + w / 2, top + h + 1, x + w / 2 - 10, top + h], ["L", x - w / 2 + 16, top + h - 1],
        ["L", x - w / 2, top + h * 0.5], ["Z"]], fill: o.fill || C.amber, width: 5.5 },
      { cmds: L.blob(x - w / 2 + 20, top + h * 0.5, 5, 5, 3, 0.05), width: 3.5, taper: false },
      { text, x: x + 9, y: top + h * 0.5 + size * 0.36, size, weight: wt, fill: o.ink || C.bg, anchor: "middle", jit: 0.2 },
    ];
    return { type: "group", rotate: { deg: o.angle || 0, x, y }, items };
  }

  function clock(cx, cy, r, hourDeg, minDeg, t) {
    const items = [];
    items.push(T({ cmds: L.blob(cx, cy, r, r, 11, 0.012), fill: C.bg, width: 7 }, t, 0, 4));
    for (let i = 0; i < 12; i++) {
      const a = (i * 30 - 90) * D2R, l = i % 3 === 0 ? 0.16 : 0.08;
      items.push(T({ cmds: L.poly([[cx + Math.cos(a) * r * (0.84 - l), cy + Math.sin(a) * r * (0.84 - l)], [cx + Math.cos(a) * r * 0.84, cy + Math.sin(a) * r * 0.84]]),
        width: i % 3 === 0 ? 5.5 : 4, wEnd: 3, taper: false }, t, 1, 4));
    }
    const hand = (deg, len, w) => { const a = (deg - 90) * D2R; return L.poly([[cx - Math.cos(a) * r * 0.08, cy - Math.sin(a) * r * 0.08], [cx + Math.cos(a) * r * len, cy + Math.sin(a) * r * len]]); };
    items.push(T({ cmds: hand(hourDeg, 0.48), width: 8.5, wEnd: 5 }, t, 2, 4));
    items.push(T({ cmds: hand(minDeg, 0.7), width: 6, wEnd: 3.5 }, t, 3, 4));
    items.push({ cmds: L.blob(cx, cy, 6, 6, 5, 0.02), fill: C.line, stroke: null });
    return items;
  }

  function laptopSide(x, y, s, t) {
    s = s || 1;
    // base on the table (y = table top), lid tilted back towards the left (the user sits on the left)
    return [
      T({ cmds: L.rrect(x, y - 12 * s, 210 * s, 12 * s, 5 * s, 7, 0.6), fill: C.body, width: 6 }, t, 0, 2),
      T({ cmds: [["M", x + 196 * s, y - 14 * s], ["L", x + 246 * s, y - 168 * s], ["Q", x + 250 * s, y - 178 * s, x + 240 * s, y - 180 * s], ["L", x + 226 * s, y - 182 * s],
        ["Q", x + 218 * s, y - 182 * s, x + 216 * s, y - 172 * s], ["L", x + 178 * s, y - 16 * s], ["Z"]], fill: C.body, width: 6 }, t, 1, 2),
    ];
  }

  function laptopFront(x, y, w, h, t) {
    const b = 20;
    return [
      T({ cmds: L.rrect(x - b, y - b, w + 2 * b, h + 2 * b + 6, 22, 51, 0.8), width: 7.5 }, t, 0, 3),
      T({ cmds: L.curve([[x + w / 2 - 22, y - b / 2], [x + w / 2 + 22, y - b / 2]]), width: 4.5 }, t, 1, 3),
      T({ cmds: [["M", x - b - 70, y + h + b + 8], ["L", x + w + b + 70, y + h + b + 8], ["Q", x + w + b + 100, y + h + b + 26, x + w + b + 70, y + h + b + 34],
        ["L", x - b - 70, y + h + b + 34], ["Q", x - b - 100, y + h + b + 26, x - b - 70, y + h + b + 8], ["Z"]], width: 7 }, t, 2, 3),
      T({ cmds: L.curve([[x + w / 2 - 90, y + h + b + 8], [x + w / 2 - 80, y + h + b + 18], [x + w / 2 + 80, y + h + b + 18], [x + w / 2 + 90, y + h + b + 8]]), width: 5 }, t, 3, 3),
    ];
  }

  function padlock(cx, cy, s, open, fill, t) {
    s = s || 1; open = open || 0;
    const w = 96 * s, h = 76 * s, lift = 34 * s * open;
    const sh = [[cx - w * 0.3, cy - h * 0.5], [cx - w * 0.31, cy - h * 0.95 - lift], [cx, cy - h * 1.22 - lift], [cx + w * 0.31, cy - h * 0.95 - lift], [cx + w * 0.3, cy - h * 0.5 - lift * 0.6]];
    return [
      T({ cmds: L.curve(sh), width: 8, wEnd: 6.5 }, t, 0, 2),
      T({ cmds: L.rrect(cx - w / 2, cy - h / 2, w, h, 12 * s, 9, 0.7), fill: fill || C.bg, width: 7 }, t, 1, 2),
      { cmds: L.blob(cx, cy - 4 * s, 7 * s, 7 * s, 3, 0.03), fill: fill ? C.bg : C.line, stroke: null },
      { cmds: L.poly([[cx, cy], [cx, cy + 16 * s]]), stroke: fill ? C.bg : C.line, width: 6 * s, wEnd: 4 * s },
    ];
  }

  function envelope(cx, cy, w, h, rot, t) {
    const x = cx - w / 2, y = cy - h / 2;
    const items = [
      T({ cmds: L.rrect(x, y, w, h, 6, 13, 0.6), fill: C.screen, width: 5.5 }, t, 0, 2),
      T({ cmds: L.poly([[x + 4, y + 4], [cx, cy + h * 0.12], [x + w - 4, y + 4]]), stroke: C.bg, width: 4.5 }, t, 1, 2),
    ];
    return rot ? { type: "group", rotate: { deg: rot, x: cx, y: cy }, items } : items;
  }

  function building(x, y, w, h, o, t) {
    o = o || {};
    const floors = o.floors || 4, cols = o.cols || 3;
    const items = [T({ cmds: L.rrect(x, y, w, h, 6, 21, 1.2), fill: C.body, width: 7 }, t, 0, 3)];
    const mx = w * 0.14, my = h * 0.08, gw = (w - 2 * mx) / cols, gh = (h * 0.8 - my) / floors;
    for (let f = 0; f < floors; f++) for (let c = 0; c < cols; c++) {
      const wx = x + mx + c * gw + gw * 0.18, wy = y + my + f * gh + gh * 0.2;
      items.push(T({ cmds: L.rrect(wx, wy, gw * 0.64, gh * 0.56, 4, 30 + f * 7 + c, 0.5), width: 4.5, taper: false, fill: o.lit && (f + c) % 3 === 0 ? C.amber : null, fillOpacity: 0.85 }, t, 1, 3));
    }
    const dw = w * 0.2;
    items.push(T({ cmds: L.poly([[x + w / 2 - dw / 2, y + h], [x + w / 2 - dw / 2, y + h - h * 0.13], [x + w / 2 + dw / 2, y + h - h * 0.13], [x + w / 2 + dw / 2, y + h]]), width: 5.5 }, t, 2, 3));
    return items;
  }

  function coin(cx, cy, r, t) {
    return [
      T({ cmds: L.blob(cx, cy, r, r, 17, 0.015), fill: C.amber, width: 6 }, t, 0, 2),
      T({ cmds: L.blob(cx, cy, r * 0.68, r * 0.68, 18, 0.02), stroke: C.bg, strokeOpacity: 0.55, width: 3.5, taper: false }, t, 1, 2),
    ];
  }

  function jar(cx, by, w, h, t) {
    const x0 = cx - w / 2, x1 = cx + w / 2, nk = w * 0.36;
    return [
      T({ cmds: L.curve([[cx - nk, by - h], [cx - nk, by - h * 0.9], [x0 + 6, by - h * 0.78], [x0, by - h * 0.5], [x0 + 4, by - 18], [cx - w * 0.3, by], [cx + w * 0.3, by],
        [x1 - 4, by - 18], [x1, by - h * 0.5], [x1 - 6, by - h * 0.78], [cx + nk, by - h * 0.9], [cx + nk, by - h]], false, 0.8), width: 7 }, t, 0, 2),
      T({ cmds: L.rrect(cx - nk - 10, by - h - 18, 2 * nk + 20, 18, 6, 4, 0.5), fill: C.body, width: 6 }, t, 1, 2),
    ];
  }

  function paper(x, y, w, h, o, t) {
    o = o || {};
    const lines = o.lines == null ? 4 : o.lines, f = 18;
    const items = [T({ cmds: [["M", x, y], ["L", x + w - f, y], ["L", x + w, y + f], ["L", x + w, y + h], ["L", x, y + h], ["Z"]], fill: o.fill || C.screen, width: 5 }, t, 0, 2)];
    items.push(T({ cmds: L.poly([[x + w - f, y], [x + w - f, y + f], [x + w, y + f]]), width: 4, taper: false }, t, 1, 2));
    for (let i = 0; i < lines; i++) {
      const ly = y + h * 0.22 + i * h * 0.16, lw = (i === 0 ? 0.45 : 0.72 - (i % 2) * 0.16) * w;
      items.push(T({ cmds: L.poly([[x + w * 0.14, ly], [x + w * 0.14 + lw, ly]]), stroke: C.bg, strokeOpacity: i === 0 ? 0.8 : 0.4, width: i === 0 ? 5 : 3.5, taper: false }, t, 1, 2));
    }
    return o.rot ? { type: "group", rotate: { deg: o.rot, x: x + w / 2, y: y + h / 2 }, items } : items;
  }

  function calendar(x, y, w, h, t) {
    return [
      T({ cmds: [["M", x - 14, y + h + 22], ["L", x + 10, y - 4], ["L", x + w - 10, y - 4], ["L", x + w + 14, y + h + 22], ["Z"]], fill: C.body, width: 6.5 }, t, 0, 2),
      ...[0.25, 0.5, 0.75].map((k) => T({ cmds: L.blob(x + w * k, y + 4, 9, 13, 7 + k * 10, 0.05), width: 5, taper: false }, t, 1, 2)),
    ];
  }

  function door(x, y, w, h, t) {
    return [
      T({ cmds: L.poly([[x, y + h], [x, y], [x + w, y], [x + w, y + h]]), width: 7 }, t, 0, 3),
      T({ cmds: L.rrect(x + 16, y + 16, w - 32, h - 16, 6, 23, 0.8), fill: C.body, width: 6 }, t, 1, 3),
      T({ cmds: L.rrect(x + w * 0.3, y + h * 0.14, w * 0.4, h * 0.2, 8, 24, 0.6), fill: C.amber, fillOpacity: 0.85, width: 5 }, t, 2, 3),
      { cmds: L.blob(x + w - 40, y + h * 0.56, 7, 7, 25, 0.03), fill: C.line, stroke: null },
    ];
  }

  function car(x, gy, s, t) {
    s = s || 1;
    const P = (px, py) => [x + px * s, gy - py * s];
    const body = L.curve([P(8, 34), P(4, 80), P(30, 128), P(120, 150), P(250, 150), P(310, 108), P(390, 96), P(412, 70), P(410, 34)], false, 0.7);
    const items = [
      T({ cmds: body.concat([["L", ...P(380, 32)]]), fill: C.body, width: 7 }, t, 0, 5),
      T({ cmds: L.curve([P(52, 32), P(150, 30), P(290, 30), P(330, 32)]), width: 6.5 }, t, 1, 5),
      T({ cmds: [["M", ...P(50, 104)], ["L", ...P(120, 136)], ["L", ...P(186, 136)], ["L", ...P(186, 104)], ["Z"]], fill: C.screen, fillOpacity: 0.18, width: 5 }, t, 2, 5),
      T({ cmds: [["M", ...P(202, 104)], ["L", ...P(202, 136)], ["L", ...P(244, 136)], ["L", ...P(290, 104)], ["Z"]], fill: C.screen, fillOpacity: 0.18, width: 5 }, t, 2, 5),
      T({ cmds: L.poly([P(196, 100), P(196, 46)]), width: 4.5, taper: false }, t, 3, 5),
      T({ cmds: L.poly([P(236, 84), P(256, 84)]), width: 5 }, t, 3, 5),
      { cmds: L.blob(...P(404, 82), 9, 7, 7, 0.05), fill: C.amber, stroke: null },
    ];
    [[90, 34], [326, 34]].forEach(([wx, wy], i) => {
      items.push(T({ cmds: L.blob(...P(wx, wy), 34 * s, 34 * s, 40 + i, 0.02), fill: C.bg, width: 7 }, t, 4, 5));
      items.push(T({ cmds: L.blob(...P(wx, wy), 12 * s, 12 * s, 42 + i, 0.03), width: 4.5, taper: false }, t, 4, 5));
    });
    return items;
  }

  function scissors(cx, cy, s, openDeg, rot) {
    s = s || 1;
    const lever = (sgn) => {
      const a = (rot + sgn * openDeg / 2) * D2R, co = Math.cos(a), si = Math.sin(a);
      const R = (px, py) => [cx + (px * co - py * si) * s, cy + (px * si + py * co) * s];
      return [
        { cmds: [["M", ...R(0, -5)], ["Q", ...R(50, -7), ...R(100, 0)], ["Q", ...R(50, 5), ...R(0, 6)], ["Z"]], fill: C.screen, width: 5 },
        { cmds: L.poly([R(0, 0), R(-30, 0)]), width: 6.5 },
        { cmds: L.blob(...R(-48, 0), 18 * s, 12 * s, 9 + sgn, 0.04, rot + sgn * openDeg / 2), width: 6 },
      ];
    };
    return [...lever(1), ...lever(-1), { cmds: L.blob(cx, cy, 4.5 * s, 4.5 * s, 3, 0.02), fill: C.bg, stroke: null }];
  }

  function cross(cx, cy, w, h, t1, t2) {
    const a = { cmds: L.curve([[cx - w / 2, cy - h / 2 + 6], [cx - w * 0.1, cy - h * 0.08], [cx + w / 2, cy + h / 2]]), stroke: C.red, width: 13, wEnd: 6, boil: 0.5 };
    const b = { cmds: L.curve([[cx + w / 2 - 4, cy - h / 2], [cx + w * 0.06, cy - h * 0.04], [cx - w / 2 + 6, cy + h / 2 - 4]]), stroke: C.red, width: 13, wEnd: 6, boil: 0.5 };
    if (t1 != null) { a.at = t1; a.dur = 0.16; }
    if (t2 != null) { b.at = t2; b.dur = 0.16; }
    return [a, b];
  }

  function chair(x, gy, s, facing, t) {
    s = s || 1; const f = facing || 1;
    const P = (px, py) => [x + f * px * s, gy - py * s];
    return [
      T({ cmds: L.poly([P(-10, 0), P(-6, 150), P(-12, 330)]), width: 7 }, t, 0, 3),
      T({ cmds: L.poly([P(-8, 150), P(110, 152)]), width: 7.5 }, t, 1, 3),
      T({ cmds: L.poly([P(104, 150), P(108, 0)]), width: 7 }, t, 2, 3),
    ];
  }

  window.Props = { tag, clock, laptopSide, laptopFront, padlock, envelope, building, coin, jar, paper, calendar, door, car, scissors, cross, chair };
})();
