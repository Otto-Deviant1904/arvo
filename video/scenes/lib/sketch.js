/* Arvo video: hand-drawn scene engine.
 *
 * A scene page calls Sketch.scene({defaultDuration}, build). build(S) returns a list
 * of items in paint order. Each item has `at` and `dur` as FRACTIONS of the reveal
 * span (revealFrac x scene duration, default 0.7 x d), so timing scales with length.
 *
 * window.renderAt(t) draws the deterministic frame for time t (seconds). The rough
 * seed changes every 1/12 s frame, so lines "boil". No requestAnimationFrame.
 *
 * URL params: ?d=<seconds> scene length, ?t=<seconds> frame to show on load
 * (default: the end state), ?r=<0..1> reveal fraction.
 */
(function () {
  "use strict";
  const W = 1920, H = 1080, FPS = 12;
  const q = new URLSearchParams(location.search);

  const C = {
    paper: "#F5F2EA",
    card: "#FFFDF7",
    ink: "#1F2A30",
    muted: "#5E6A72",
    faint: "#9AA4A9",
    green: "#2F6B5A",
    greenSoft: "rgba(47,107,90,0.16)",
    red: "#A3201B",
    redHl: "rgba(255,99,77,0.42)",
    amber: "#8A5A00",
  };
  const FONTS = { hand: '"Caveat"', body: '"Patrick Hand"' };

  // ---------- deterministic randomness
  function hash() {
    let h = 2166136261 >>> 0;
    for (let i = 0; i < arguments.length; i++) {
      h ^= (arguments[i] | 0) >>> 0;
      h = Math.imul(h, 16777619) >>> 0;
      h ^= h >>> 13;
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
  const ease = {
    out: (p) => 1 - Math.pow(1 - p, 3),
    inOut: (p) => (p < 0.5 ? 4 * p * p * p : 1 - Math.pow(-2 * p + 2, 3) / 2),
    back: (p) => { const c1 = 1.9, c3 = c1 + 1; return 1 + c3 * Math.pow(p - 1, 3) + c1 * Math.pow(p - 1, 2); },
    lin: (p) => p,
  };

  // ---------- text measurement
  const mctx = document.createElement("canvas").getContext("2d");
  function fontStr(font, size, weight) { return `${weight || 400} ${size}px ${FONTS[font] || font}`; }
  function measure(text, font, size, weight) { mctx.font = fontStr(font, size, weight); return mctx.measureText(text).width; }
  function wrap(text, font, size, weight, maxWidth) {
    const out = [];
    for (const para of String(text).split("\n")) {
      const words = para.split(/ +/);
      let line = "";
      for (const w of words) {
        const cand = line ? line + " " + w : w;
        if (line && measure(cand, font, size, weight) > maxWidth) { out.push(line); line = w; }
        else line = cand;
      }
      out.push(line);
    }
    return out;
  }

  // ---------- paper
  function drawPaper(canvas, seed) {
    const ctx = canvas.getContext("2d");
    const r = mulberry32(seed || 20261013);
    ctx.fillStyle = C.paper; ctx.fillRect(0, 0, W, H);
    for (let i = 0; i < 46; i++) {
      const x = r() * W, y = r() * H, rad = 90 + r() * 300, a = 0.02 + 0.03 * r();
      const g = ctx.createRadialGradient(x, y, 0, x, y, rad);
      g.addColorStop(0, r() < 0.55 ? `rgba(150,125,85,${a})` : `rgba(255,255,250,${a * 1.6})`);
      g.addColorStop(1, "rgba(0,0,0,0)");
      ctx.fillStyle = g; ctx.fillRect(x - rad, y - rad, rad * 2, rad * 2);
    }
    ctx.lineCap = "round";
    for (let i = 0; i < 700; i++) {
      const x = r() * W, y = r() * H, len = 6 + r() * 26, ang = r() * Math.PI;
      ctx.strokeStyle = `rgba(110,92,64,${0.025 + 0.05 * r()})`;
      ctx.lineWidth = 0.6 + r() * 0.8;
      ctx.beginPath(); ctx.moveTo(x, y);
      ctx.quadraticCurveTo(x + Math.cos(ang) * len * 0.5 + sym(i, 1) * 3, y + Math.sin(ang) * len * 0.5 + sym(i, 2) * 3,
        x + Math.cos(ang) * len, y + Math.sin(ang) * len);
      ctx.stroke();
    }
    const img = ctx.getImageData(0, 0, W, H), d = img.data;
    for (let i = 0; i < d.length; i += 4) {
      const n = (r() - 0.5) * 13;
      d[i] += n; d[i + 1] += n; d[i + 2] += n * 0.9;
    }
    ctx.putImageData(img, 0, 0);
    const v = ctx.createRadialGradient(W / 2, H / 2, H * 0.42, W / 2, H / 2, H * 1.02);
    v.addColorStop(0, "rgba(0,0,0,0)"); v.addColorStop(1, "rgba(95,75,45,0.13)");
    ctx.fillStyle = v; ctx.fillRect(0, 0, W, H);
  }

  // ---------- helpers for rough shapes
  function roundRectPath(x, y, w, h, r) {
    return `M${x + r},${y} L${x + w - r},${y} Q${x + w},${y} ${x + w},${y + r} L${x + w},${y + h - r} ` +
      `Q${x + w},${y + h} ${x + w - r},${y + h} L${x + r},${y + h} Q${x},${y + h} ${x},${y + h - r} ` +
      `L${x},${y + r} Q${x},${y} ${x + r},${y} Z`;
  }

  const NS = "http://www.w3.org/2000/svg";
  function el(tag, attrs) {
    const e = document.createElementNS(NS, tag);
    for (const k in attrs) e.setAttribute(k, attrs[k]);
    return e;
  }

  // Reveal a rough <g> progressively along its stroke paths; solid fills fade in.
  function applyDraw(node, p) {
    // Chromium restarts the dash pattern at every subpath, so split "M..M.." paths into
    // one element per subpath and reveal them one after another. Rough emits the fill
    // (hachure) first and the outline last: draw the outline first.
    const groups = [], fills = [];
    for (const pa of Array.from(node.querySelectorAll("path"))) {
      const f = pa.getAttribute("fill");
      if (f && f !== "none") { fills.push(pa); continue; }
      const parts = (pa.getAttribute("d") || "").split(/(?=M)/).filter((s) => s.trim());
      if (parts.length < 2) { groups.push([pa]); continue; }
      const g = [];
      for (const part of parts) {
        const c = pa.cloneNode(false);
        c.setAttribute("d", part);
        pa.parentNode.insertBefore(c, pa);
        g.push(c);
      }
      pa.remove();
      groups.push(g);
    }
    const strokes = groups.reverse().flat();
    const lens = strokes.map((pa) => pa.getTotalLength());
    const total = lens.reduce((a, b) => a + b, 0) || 1;
    let drawn = p * total, acc = 0;
    strokes.forEach((pa, i) => {
      const len = lens[i], vis = clamp(drawn - acc, 0, len);
      acc += len;
      if (vis <= 0.01) { pa.setAttribute("display", "none"); return; }
      if (vis < len) { pa.setAttribute("stroke-dasharray", `${vis} ${len + 2}`); pa.setAttribute("stroke-dashoffset", "0"); }
    });
    const fp = clamp((p - 0.55) / 0.45);
    for (const pa of fills) pa.setAttribute("opacity", fp);
  }

  // ---------- the scene
  function scene(opts, build) {
    opts = opts || {};
    let duration = parseFloat(q.get("d")) || opts.defaultDuration || 8;
    const revealFrac = parseFloat(q.get("r")) || opts.revealFrac || 0.7;
    const boil = opts.boil == null ? 1 : opts.boil;

    document.body.insertAdjacentHTML("beforeend",
      '<canvas id="paper" width="1920" height="1080"></canvas>' +
      '<svg id="stage" xmlns="http://www.w3.org/2000/svg" width="1920" height="1080" viewBox="0 0 1920 1080"></svg>' +
      '<div class="warm"><span class="c">Aa1</span><span class="c4">Aa1</span><span class="p">Aa1</span></div>');
    const svg = document.getElementById("stage");
    const rc = rough.svg(svg);
    let items = [];
    const byId = {};

    // Text layout: lines, char offsets, line widths.
    function layoutText(it) {
      it.font = it.font || "body";
      it.size = it.size || 48;
      it.weight = it.weight || (it.font === "hand" ? 700 : 400);
      it.lh = it.lh || Math.round(it.size * 1.3);
      it.lines = it.lines || (it.maxWidth ? wrap(it.text, it.font, it.size, it.weight, it.maxWidth) : String(it.text).split("\n"));
      it.widths = it.lines.map((l) => measure(l, it.font, it.size, it.weight));
      it.total = it.lines.reduce((a, l) => a + l.length, 0);
      it.wordEnds = [];
      let off = 0;
      it.lines.forEach((l) => {
        const re = /\S+/g; let m;
        while ((m = re.exec(l))) it.wordEnds.push(off + m.index + m[0].length);
        off += l.length;
      });
      return it;
    }
    function lineX(it, li) {
      const a = it.anchor || "start";
      if (a === "middle") return it.x - it.widths[li] / 2;
      if (a === "end") return it.x - it.widths[li];
      return it.x;
    }
    // Rectangles (per line) covering `phrase` inside text item `it`.
    function phraseRects(it, phrase, padX, top, bottom) {
      const joined = it.lines.join(" ");
      const start = joined.indexOf(phrase);
      if (start < 0) throw new Error("phrase not found: " + phrase);
      const end = start + phrase.length;
      const rects = [];
      let off = 0;
      it.lines.forEach((l, li) => {
        const ls = off, le = off + l.length;
        const a = Math.max(start, ls), b = Math.min(end, le);
        if (b > a) {
          const x0 = lineX(it, li) + measure(l.slice(0, a - ls), it.font, it.size, it.weight);
          const w = measure(l.slice(a - ls, b - ls), it.font, it.size, it.weight);
          const base = it.y + li * it.lh;
          rects.push({ x: x0 - padX, y: base - it.size * top, w: w + 2 * padX, h: it.size * (top + bottom), line: li });
        }
        off = le + 1;
      });
      return rects;
    }

    const api = {
      C, W, H, FPS, ease, measure, wrap, roundRectPath, rnd, sym,
      get duration() { return duration; },
      text(o) { return layoutText(Object.assign({ type: "text" }, o)); },
      phraseRects,
      // Sequence children inside [at, at+dur]: each gets an equal slice unless it has w (weight).
      seq(at, dur, children, overlap) {
        overlap = overlap || 0;
        const tw = children.reduce((a, c) => a + (c.w || 1), 0);
        let acc = 0;
        children.forEach((c) => {
          const share = (c.w || 1) / tw;
          c.at = at + dur * acc; c.dur = dur * share * (1 + overlap);
          acc += share;
        });
        return children;
      },
    };

    function renderText(it, p, f, idx, layer) {
      if (p <= 0 && it.reveal !== "none") return;
      let n = it.total, opacity = 1;
      const mode = it.reveal || "type";
      if (mode === "type") n = Math.floor(p * it.total + 1e-6);
      else if (mode === "words") {
        const k = Math.ceil(p * it.wordEnds.length - 1e-6);
        n = k <= 0 ? 0 : it.wordEnds[Math.min(k, it.wordEnds.length) - 1];
      } else if (mode === "fade") opacity = ease.out(p);
      const g = el("g", { opacity: opacity });
      if (mode === "pop") {
        const s = ease.back(p);
        const cx = it.popX != null ? it.popX : it.x, cy = it.popY != null ? it.popY : it.y;
        g.setAttribute("transform", `translate(${cx},${cy}) scale(${Math.max(0.001, s)}) translate(${-cx},${-cy})`);
        g.setAttribute("opacity", clamp(p * 4));
      }
      const amp = (it.jitter == null ? 0.9 : it.jitter) * boil;
      const ramp = (it.rotJitter == null ? 1.1 : it.rotJitter) * boil;
      let remaining = n, caret = null;
      it.lines.forEach((line, li) => {
        if (remaining <= 0 && !(li === 0 && n === 0)) return;
        const s = line.slice(0, Math.max(0, Math.min(line.length, remaining)));
        remaining -= line.length;
        const x = lineX(it, li), y = it.y + li * it.lh;
        if (s.length) {
          const t = el("text", {
            x: x, y: y, "font-family": FONTS[it.font] || it.font, "font-size": it.size,
            "font-weight": it.weight, fill: it.fill || C.ink,
          });
          if (it.letterSpacing) t.setAttribute("letter-spacing", it.letterSpacing);
          const dys = [], rots = [];
          let prev = 0;
          for (let c = 0; c < s.length; c++) {
            const o = sym(f, idx, li, c, 11) * amp;
            dys.push((o - prev).toFixed(2)); prev = o;
            rots.push((sym(f, idx, li, c, 23) * ramp).toFixed(2));
          }
          t.setAttribute("dy", dys.join(" "));
          t.setAttribute("rotate", rots.join(" "));
          t.textContent = s;
          g.appendChild(t);
        }
        if (s.length < line.length || remaining <= 0) {
          caret = { x: x + measure(s, it.font, it.size, it.weight), y: y };
        }
      });
      layer.appendChild(g);
      if (it.caret && caret) {
        const tNow = it._t, tEnd = it._end, until = it._caretUntil;
        const typing = p > 0 && p < 1;
        const blinkOn = Math.floor(tNow * 2.4) % 2 === 0;
        if (typing || (p >= 1 && tNow < until && blinkOn) || (p <= 0 && blinkOn)) {
          const node = rc.line(caret.x + 6, caret.y - it.size * 0.78, caret.x + 6 + sym(f, idx, 5), caret.y + it.size * 0.12,
            { stroke: it.caretColor || C.green, strokeWidth: 4, roughness: 0.6, seed: 1 + (hash(f, idx, 77) % 2147483646) });
          layer.appendChild(node);
        }
      }
    }

    function renderRough(it, p, f, idx, layer) {
      if (p <= 0) return;
      const seed = 1 + (hash(boil ? f : 0, idx, 3) % 2147483646);
      const o = Object.assign({ roughness: 1.15, bowing: 0.8, stroke: C.ink, strokeWidth: 3 }, it.opts || {}, { seed });
      let args = it.args;
      const mode = it.reveal || "draw";
      if (mode === "grow" && it.shape === "line") {
        const [x1, y1, x2, y2] = args, e = ease.out(p);
        args = [x1, y1, x1 + (x2 - x1) * e, y1 + (y2 - y1) * e];
      }
      if (mode === "sweep" && it.shape === "rectangle") {
        const [x, y, w, h] = args;
        args = [x, y, Math.max(1, w * ease.inOut(p)), h];
      }
      const node = rc[it.shape](...args, o);
      if (mode === "fade") node.setAttribute("opacity", ease.out(p));
      if (mode === "pop") {
        const s = ease.back(p), cx = it.popX, cy = it.popY;
        node.setAttribute("transform", `translate(${cx},${cy}) scale(${Math.max(0.001, s)}) translate(${-cx},${-cy})`);
      }
      layer.appendChild(node);
      if (mode === "draw" && p < 1) applyDraw(node, ease.inOut(p));
    }

    function renderItem(it, t, f, idx, layer, R) {
      const s = it.at * R, e = (it.at + it.dur) * R;
      const p = it.dur > 0 ? clamp((t - s) / (e - s)) : (t >= s ? 1 : 0);
      it._t = t; it._end = e; it._caretUntil = (it.caretUntil != null ? it.caretUntil * R : e + 0.6);
      if (it.type === "text") return renderText(it, p, f, idx, layer);
      if (it.type === "rough") return renderRough(it, p, f, idx, layer);
      if (it.type === "group") {
        if (p <= 0 && it.at != null && it.dur != null && it.reveal) return;
        const g = el("g", {});
        let tr = it.transform || "";
        if (it.reveal === "pop") {
          const sc = ease.back(p);
          tr += ` translate(${it.popX},${it.popY}) scale(${Math.max(0.001, sc)}) translate(${-it.popX},${-it.popY})`;
        }
        if (tr) g.setAttribute("transform", tr);
        it.children.forEach((c, ci) => renderItem(c, t, f, idx * 101 + ci + 1, g, R));
        layer.appendChild(g);
      }
    }

    function renderAt(t) {
      const f = Math.round(t * FPS);
      const R = revealFrac * duration;
      while (svg.firstChild) svg.removeChild(svg.firstChild);
      items.forEach((it, i) => renderItem(it, t, f, i + 1, svg, R));
      return f;
    }

    window.renderAt = renderAt;
    window.setDuration = (d) => { duration = d; };
    window.sceneInfo = () => ({ duration, revealFrac, fps: FPS });

    const fontsReady = Promise.all([
      document.fonts.load('700 40px "Caveat"'),
      document.fonts.load('400 40px "Caveat"'),
      document.fonts.load('400 40px "Patrick Hand"'),
    ]).then(() => document.fonts.ready);

    fontsReady.then(() => {
      drawPaper(document.getElementById("paper"), opts.paperSeed);
      items = build(api);
      items.forEach((it) => { if (it.type === "text" && !it.lines) layoutText(it); });
      const t0 = q.get("t") != null ? parseFloat(q.get("t")) : duration;
      renderAt(t0);
      window.sceneReady = true;
    }).catch((e) => { window.sceneError = String(e); console.error(e); });
  }

  window.Sketch = { scene, C, FONTS };
})();
