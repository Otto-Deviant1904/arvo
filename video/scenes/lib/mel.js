/* Mel: a stick-figure puppet (round head, short ponytail with a hair tie, lanyard + green card).
 *
 * Mel.pose(keys, tn): keyframed poses, eased per key ({t, pose, ease}); ease names from Line.ease.
 * Mel.rig(P, tn): joint positions (for springs, props, effects).
 * Mel.items(P, o): line items. o = {tn, drawAt, drawScale, blink}.
 * Pose fields:
 *   hip [x,y], spine (deg, + leans forward/right), slump (px back-bow), stretch (spine length x),
 *   headSq (head height/width: <1 squash, >1 stretch), headTilt (deg), fx (-1..1 face turn),
 *   nh/fh near/far hand targets, nf/ff near/far feet,
 *   brow (fraction of R, more negative = higher), browTilt (+ inner ends up), eyeR, ring (0/1),
 *   lid (0 open .. 1 closed), mouthC (-1..1), mouthO (0..1.6 open; >1 = yawn),
 *   ponyD [dx,dy] / cardD [dx,dy]: follow-through offsets from springs (world px),
 *   phone (0/1), phoneHand ('near'|'far'), phoneRot, phoneFree (>0.5: not in a hand), glow (0..1),
 *   breathRate (s per breath), breathAmp, knee ('up' seated | 'fwd' standing/walking)
 * o.look = {ponytail, lanyard, cap} (default Mel: ponytail + lanyard; Jake: {ponytail:false, lanyard:false, cap:true})
 * o.flip = true mirrors the figure about its hip x (faces left).
 * Mel.walk(tn, {t0, x0, ground, stride, period, steps}) -> pose fields for a side-view walk cycle (facing right).
 * Mel.follow(poseFn, t0, tn, P) sets P.ponyD / P.cardD from springs (follow-through).
 */
(function () {
  "use strict";
  const L = window.Line, C = L.C, D2R = L.D2R;
  const R = 58, SPINE = 185, NECK = 14, UARM = 104, FARM = 98, THIGH = 158, SHIN = 150;

  const EXPR = {
    tired: { brow: -0.36, browTilt: 0.25, eyeR: 5, ring: 0, lid: 0.55, mouthC: -0.35, mouthO: 0 },
    alert: { brow: -0.46, browTilt: 0.1, eyeR: 6, ring: 0, lid: 0, mouthC: 0, mouthO: 0 },
    blank: { brow: -0.42, browTilt: 0, eyeR: 6, ring: 0, lid: 0, mouthC: 0.05, mouthO: 0 },
    alarm: { brow: -0.66, browTilt: 0.8, eyeR: 5, ring: 1, lid: 0, mouthC: 0, mouthO: 0.75 },
    worried: { brow: -0.6, browTilt: 0.9, eyeR: 5, ring: 1, lid: 0, mouthC: -0.6, mouthO: 0.35 },
    relieved: { brow: -0.44, browTilt: 0.1, eyeR: 5.5, ring: 0, lid: 0.2, mouthC: 0.9, mouthO: 0 },
    smile: { brow: -0.48, browTilt: 0.05, eyeR: 6, ring: 0, lid: 0, mouthC: 0.95, mouthO: 0 },
    sad: { brow: -0.4, browTilt: 1.0, eyeR: 5, ring: 0, lid: 0.35, mouthC: -0.85, mouthO: 0 },
    focused: { brow: -0.36, browTilt: -0.15, eyeR: 5.5, ring: 0, lid: 0.15, mouthC: -0.1, mouthO: 0 },
  };
  const DEF = { stretch: 1, headSq: 1, ponyD: [0, 0], cardD: [0, 0], phoneFree: 0, phoneHand: "near", breathRate: 3.3, breathAmp: 1, slump: 0, knee: "up", phone: 0, glow: 0 };

  function mix(a, b, p) {
    const out = {};
    for (const k in a) {
      const va = a[k], vb = b[k] == null ? va : b[k];
      if (Array.isArray(va)) out[k] = va.map((v, i) => L.lerp(v, vb[i], p));
      else if (typeof va === "number") out[k] = L.lerp(va, vb, p);
      else out[k] = p < 0.5 ? va : vb;
    }
    for (const k in b) if (!(k in out)) out[k] = b[k];
    return out;
  }
  function pose(keys, tn) {
    let P;
    if (tn <= keys[0].t) P = keys[0].pose;
    else {
      P = keys[keys.length - 1].pose;
      for (let i = 1; i < keys.length; i++) {
        if (tn < keys[i].t) {
          const a = keys[i - 1], b = keys[i];
          const e = (L.ease[b.ease || "inOut"] || L.ease.inOut)((tn - a.t) / (b.t - a.t));
          P = mix(a.pose, b.pose, e);
          break;
        }
      }
    }
    return Object.assign({}, DEF, P);
  }
  const expr = (name, extra) => Object.assign({}, EXPR[name], extra || {});
  const add = (a, b) => [a[0] + b[0], a[1] + b[1]];
  const sub = (a, b) => [a[0] - b[0], a[1] - b[1]];
  const mul = (a, s) => [a[0] * s, a[1] * s];

  function rig(P, tn) {
    P = Object.assign({}, DEF, P);
    const breath = Math.sin((tn || 0) * 2 * Math.PI / P.breathRate);
    const spineLen = SPINE * P.stretch * (1 + 0.008 * breath * P.breathAmp);
    const sp = P.spine * D2R;
    const H = P.hip;
    const u = [Math.sin(sp), -Math.cos(sp)];
    const back = [-Math.cos(sp), -Math.sin(sp)];
    const fwd = [-back[0], -back[1]];
    const S = add(H, mul(u, spineLen));
    const ht = (P.spine + P.headTilt) * D2R;
    const uh = [Math.sin(ht), -Math.cos(ht)];
    const rx = R / Math.sqrt(P.headSq), ry = R * Math.sqrt(P.headSq);
    const HC = add(S, mul(uh, ry + NECK));
    const cardAnchor = add(add(S, mul(sub(H, S), 0.3)), mul(fwd, 20));
    return { P, H, S, HC, u, back, fwd, uh, ht, rx, ry, cardAnchor, R };
  }

  function items(P, o) {
    o = o || {};
    const tn = o.tn || 0;
    const g = rig(P, tn);
    P = g.P;
    const { H, S, HC, u, back, fwd, uh, ht, rx, ry } = g;
    const out = [];
    let clock = o.drawAt;
    const ds = o.drawScale || 1;
    const timed = (it, dur) => {
      if (clock != null) { it.at = clock; it.dur = dur * ds; clock += dur * ds * 0.8; }
      out.push(it);
      return it;
    };
    const toWorld = (x, y) => {
      x *= rx / R; y *= ry / R;
      return [HC[0] + x * Math.cos(ht) - y * Math.sin(ht), HC[1] + x * Math.sin(ht) + y * Math.cos(ht)];
    };
    const W = (pts) => pts.map((p) => toWorld(p[0], p[1]));
    const neckTop = add(HC, mul(uh, -ry));
    const Sa = add(S, mul(sub(H, S), 0.07));
    const arm = (hand) => {
      const [E, Hd] = L.ik(Sa, hand, UARM, FARM, (j1, j2) => j1[1] > j2[1]);
      return L.curve([Sa, E, Hd], false, 0.9);
    };
    const leg = (foot) => {
      const [K, A] = L.ik(H, foot, THIGH, SHIN, P.knee === "fwd" ? (j1, j2) => j1[0] > j2[0] : (j1, j2) => j1[1] < j2[1]);
      const c = L.curve([H, K, A], false, 0.7);
      c.push(["L", A[0] + 30, A[1] + 1]);
      return c;
    };

    // head (filled with the background colour so lines behind it are hidden)
    timed({ cmds: L.blob(HC[0], HC[1], rx, ry, 41, 0.02, P.spine + P.headTilt), fill: C.bg }, 0.3);
    const look = Object.assign({ ponytail: true, lanyard: true, cap: false }, o.look || {});
    if (look.ponytail) {
      // ponytail: tip lags behind the head (ponyD from a spring)
      const side = P.fx >= -0.2 ? 1 : -1;
      const px = (x) => -side * x;
      const pd = P.ponyD;
      const pw = (pt, k) => [pt[0] + pd[0] * k, pt[1] + pd[1] * k];
      const pony = W([[px(0.8 * R), -0.62 * R], [px(1.12 * R), -0.66 * R], [px(1.36 * R), -0.42 * R], [px(1.42 * R), -0.02 * R], [px(1.2 * R), -0.2 * R], [px(0.99 * R), -0.2 * R]]);
      const pk = [0, 0.3, 0.7, 1, 0.75, 0.15];
      timed({ cmds: L.curve(pony.map((pt, i) => pw(pt, pk[i])), false, 0.9), width: 6.5 }, 0.14);
      const strand = W([[px(1.08 * R), -0.46 * R], [px(1.24 * R), -0.3 * R], [px(1.3 * R), -0.12 * R]]);
      timed({ cmds: L.curve(strand.map((pt, i) => pw(pt, [0.4, 0.7, 0.85][i])), false), width: 4.2 }, 0.05);
      timed({ cmds: L.curve(W([[px(0.97 * R), -0.68 * R], [px(1.02 * R), -0.5 * R], [px(1.06 * R), -0.3 * R]]), false), width: 8.5, wEnd: 7 }, 0.04);
    }
    if (look.cap) {
      timed({ cmds: L.curve(W([[-0.94 * R, -0.36 * R], [-0.84 * R, -0.74 * R], [-0.4 * R, -1.06 * R], [0.2 * R, -1.1 * R], [0.7 * R, -0.86 * R], [0.94 * R, -0.42 * R],
        [0, -0.54 * R]]), true, 0.9), fill: C.screen, width: 6.5 }, 0.12);
      timed({ cmds: L.curve(W([[0.56 * R, -0.5 * R], [1.1 * R, -0.54 * R], [1.56 * R, -0.42 * R]]), false), width: 7 }, 0.06);
      timed({ cmds: L.curve(W([[-0.96 * R, -0.3 * R], [-1.12 * R, -0.14 * R], [-1.06 * R, 0.0]]), false), width: 4.5 }, 0.03);
    }

    const headItems = out.length;
    // body
    const mid = add(mul(add(S, H), 0.5), mul(back, P.slump));
    timed({ cmds: L.curve([neckTop, S, mid, H], false, 0.8) }, 0.22);
    // lanyard: the card hangs and swings (cardD from a spring)
    const cardTop = add(g.cardAnchor, P.cardD);
    const lanyTop = add(add(S, mul(u, 8)), mul(fwd, 5));
    const cardRot = Math.atan2(P.cardD[0], 60) / D2R * -0.6;
    if (look.lanyard) {
      timed({ cmds: L.curve([lanyTop, add(mul(add(lanyTop, cardTop), 0.5), mul(fwd, 5)), cardTop], false), width: 4.2 }, 0.1);
      timed({ cmds: L.rotateCmds(L.rrect(cardTop[0] - 13, cardTop[1], 26, 34, 5, 12), cardTop[0], cardTop[1], cardRot), fill: C.green, width: 4.2 }, 0.08);
    }

    // limbs
    timed({ cmds: leg(P.ff) }, 0.16);
    timed({ cmds: arm(P.fh) }, 0.15);
    timed({ cmds: leg(P.nf) }, 0.16);
    timed({ cmds: arm(P.nh) }, 0.15);

    // phone in hand + its light on her face
    if (P.phone > 0.5 && P.phoneFree < 0.5) {
      const pc = add(P.phoneHand === "far" ? P.fh : P.nh, [8, -14]);
      timed({ cmds: L.rotateCmds(L.rrect(pc[0] - 16, pc[1] - 29, 32, 58, 7, 21), pc[0], pc[1], P.phoneRot), fill: C.screen, width: 5.5 }, 0.08);
      if (P.glow > 0.01) {
        const sgn = Math.sign(P.fx || 1);
        const gl = { cmds: L.poly([add(pc, [-6, -26]), add(pc, [-6, 26]), toWorld(0.55 * R * sgn, 0.7 * R), toWorld(0.55 * R * sgn, -0.75 * R)], true),
          stroke: null, fill: C.line, fillOpacity: 0.075 * P.glow, boil: 0 };
        if (clock != null) gl.fillAt = clock + 0.05;
        out.push(gl);
      }
    }

    // face
    const face = [];
    const ox = P.fx * R * 0.42;
    const spread = R * 0.27 * (1 - 0.42 * Math.abs(P.fx));
    const ey = -R * 0.06;
    [ox - spread, ox + spread].forEach((ex, i) => {
      const inner = i === 0 ? 1 : -1;
      if (o.blink || P.lid > 0.85) {
        face.push({ cmds: L.curve(W([[ex - 8, ey], [ex, ey + 3], [ex + 8, ey]]), false), width: 5 });
      } else if (P.ring > 0.5) {
        face.push({ cmds: L.blob(...toWorld(ex, ey), 11 * rx / R, 12 * ry / R, 50 + i, 0.03), width: 4.6, taper: false });
        face.push({ cmds: L.blob(...toWorld(ex + P.fx * 2, ey + 1), 4.3, 4.3, 60 + i, 0.02), fill: C.line, stroke: null });
      } else if (P.lid > 0.3) {
        const r = P.eyeR;
        face.push({ cmds: L.curve(W([[ex - r - 1.5, ey - 1], [ex - r * 0.75, ey + r * 0.7], [ex, ey + r], [ex + r * 0.75, ey + r * 0.7], [ex + r + 1.5, ey - 1]]), true), fill: C.line, width: 2.5, taper: false });
      } else {
        face.push({ cmds: L.blob(...toWorld(ex, ey), P.eyeR, P.eyeR * 1.08, 70 + i, 0.03), fill: C.line, stroke: null });
      }
      const by = R * P.brow, bt = P.browTilt * 7;
      face.push({ cmds: L.curve(W([[ex - inner * 11, by + bt * 0.6], [ex, by - 2 - bt * 0.1], [ex + inner * 11, by - bt]]), false), width: 5.2, wEnd: 3 });
    });
    const mx = ox + P.fx * 4, my = R * 0.4;
    if (P.mouthO > 0.3) face.push({ cmds: L.blob(...toWorld(mx - (P.mouthO > 1 ? 5 : 0), my + (P.mouthO > 1 ? 3 : 0)), 5 + 5 * Math.min(1, P.mouthO), 6 + 7 * P.mouthO, 80, 0.05), width: 4.8, taper: false });
    else face.push({ cmds: L.curve(W([[mx - 11, my - P.mouthC * 2], [mx, my + P.mouthC * 8], [mx + 11, my - P.mouthC * 2]]), false), width: 5, wEnd: 3 });
    const fg = { type: "group", items: face };
    if (o.drawAt != null) fg.pop = { x: HC[0], y: HC[1], at: o.drawAt + 0.3 * ds, dur: 0.1 };
    out.splice(headItems, 0, fg);

    out.rig = g;
    if (o.flip) {
      const hx = H[0];
      const mir = (it) => {
        if (it.type === "group") { it.items.forEach(mir); if (it.pop) it.pop.x = 2 * hx - it.pop.x; return; }
        if (it.cmds) it.cmds = L.mapCmds(it.cmds, (x, y) => [2 * hx - x, y]);
      };
      out.forEach(mir);
    }
    return out;
  }

  // Side-view walk cycle (facing right). Returns pose fields; blend with Mel.mix for starts/stops.
  function walk(tn, w) {
    const T = w.period || 0.92, Ls = w.stride || 118, v = 2 * Ls / T;
    const maxT = w.steps != null ? w.steps * T / 2 : Infinity;
    const el = Math.min(Math.max(0, tn - w.t0), maxT);
    const ph = (el / T) % 1;
    const hx = w.x0 + v * el;
    const hy = w.ground - (w.hipH || 292) + 4 * Math.cos(4 * Math.PI * ph);
    const foot = (u) => {
      u = ((u % 1) + 1) % 1;
      if (u < 0.5) return [Ls / 2 - Ls * (u / 0.5), 0];
      const k = (u - 0.5) / 0.5, e = 0.5 - 0.5 * Math.cos(Math.PI * k);
      return [-Ls / 2 + Ls * e, -28 * Math.sin(Math.PI * k)];
    };
    const fn = foot(ph), ff = foot(ph + 0.5);
    const sw = (fx) => -fx * 0.42;
    return {
      hip: [hx, hy], nf: [hx + fn[0], w.ground + fn[1]], ff: [hx + ff[0], w.ground + ff[1]],
      nh: [hx + 10 + sw(ff[0]) * 1.3, hy + 14 - Math.abs(sw(ff[0])) * 0.3], fh: [hx + 10 + sw(fn[0]) * 1.3, hy + 10 - Math.abs(sw(fn[0])) * 0.3],
      spine: 5, slump: 0, knee: "fwd", moving: el < maxT && tn > w.t0,
    };
  }

  // Follow-through: ponytail tip and lanyard card lag behind the body (springs integrated from t0).
  // poseFn(t) -> pose; returns P0 with ponyD / cardD set.
  function follow(poseFn, t0, tn, P0, k) {
    k = k || {};
    const head = (t) => rig(poseFn(t), t).HC;
    const card = (t) => rig(poseFn(t), t).cardAnchor;
    const g = rig(P0, tn);
    const ph = L.spring(head, t0, tn, k.pony || 300, k.ponyC || 13), pc = L.spring(card, t0, tn, k.card || 150, k.cardC || 8);
    const lim = (v, m) => { const l = Math.hypot(v[0], v[1]); return l > m ? [v[0] / l * m, v[1] / l * m] : v; };
    P0.ponyD = lim([(ph[0] - g.HC[0]) * 1.6, (ph[1] - g.HC[1]) * 1.6], 46);
    P0.cardD = lim([pc[0] - g.cardAnchor[0], (pc[1] - g.cardAnchor[1]) * 0.6], 26);
    return P0;
  }

  window.Mel = { items, pose, rig, expr, EXPR, R, mix, walk, follow };
})();
