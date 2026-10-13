"""Record the live screen clips for the Arvo video (s06_demo_text, s07_demo_photo, s08_demo_voice).

Needs `python -m arvo serve` on 127.0.0.1:8765 (real Gemma runs), /usr/bin/chromium and system ffmpeg.
No Playwright browser or ffmpeg download: frames come from CDP Page.startScreencast and are stitched
into a constant 30 fps H.264 MP4 with the system ffmpeg, timed by each frame's own timestamp.

    uv run --with playwright python video/record_clips.py                 # all three clips
    uv run --with playwright python video/record_clips.py --only s07_demo_photo

Writes video/clips/<id>.mp4, video/clips/<id>.events.json ([{t, label, box?}], t in seconds from the
first frame, box = [x, y, w, h] in viewport pixels at that moment, held still >= 2.5 s for doodles)
and three check stills per clip in video/build/stills/.
"""
import argparse
import asyncio
import base64
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parent.parent
VIDEO = ROOT / "video"
CLIPS = VIDEO / "clips"
FRAMES = VIDEO / "build" / "frames"
STILLS = VIDEO / "build" / "stills"
W, H = 1920, 1080

# A visible fake cursor (headless screencasts have none) with a soft ring on mousedown.
# window.print is stubbed so the invoice window opened by "Print invoice" stays on screen.
CURSOR_JS = r"""
(() => {
  try { window.print = () => {}; } catch (_) {}
  let cur = null;
  const css = `
    #__fc{position:fixed;left:0;top:0;width:28px;height:28px;z-index:2147483647;pointer-events:none;
      opacity:0;transition:opacity .15s;will-change:transform}
    #__fc svg{display:block;transform-origin:4px 3px;transition:transform .12s;
      filter:drop-shadow(0 1px 2px rgba(0,0,0,.35))}
    #__fc.down svg{transform:scale(.85)}
    .__fr{position:fixed;left:0;top:0;width:46px;height:46px;margin:-23px 0 0 -23px;border-radius:50%;
      border:3px solid rgba(47,107,90,.8);background:rgba(47,107,90,.14);z-index:2147483646;
      pointer-events:none;animation:__fr .6s ease-out forwards}
    @keyframes __fr{from{transform:scale(.25);opacity:1}to{transform:scale(1.3);opacity:0}}`;
  const install = () => {
    if (document.getElementById('__fc') || !document.documentElement) return;
    const st = document.createElement('style');
    st.textContent = css;
    document.documentElement.appendChild(st);
    cur = document.createElement('div');
    cur.id = '__fc';
    cur.innerHTML = '<svg width="28" height="28" viewBox="0 0 28 28"><path d="M4 3 L4 22.5 L9 17.8 L12.6 25.4 L16 23.9 L12.5 16.5 L19.4 16.5 Z" fill="#17232A" stroke="#fff" stroke-width="1.7" stroke-linejoin="round"/></svg>';
    document.documentElement.appendChild(cur);
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', install);
  else install();
  addEventListener('mousemove', (e) => {
    install();
    if (!cur) return;
    cur.style.transform = `translate(${e.clientX - 4}px, ${e.clientY - 3}px)`;
    cur.style.opacity = '1';
  }, true);
  addEventListener('mousedown', (e) => {
    install();
    if (cur) cur.classList.add('down');
    const r = document.createElement('div');
    r.className = '__fr';
    r.style.left = e.clientX + 'px';
    r.style.top = e.clientY + 'px';
    document.documentElement.appendChild(r);
    setTimeout(() => r.remove(), 700);
  }, true);
  addEventListener('mouseup', () => { if (cur) cur.classList.remove('down'); }, true);
})();
"""

SMOOTH_SCROLL_JS = r"""
async ({ top, ms }) => {
  const maxTop = document.documentElement.scrollHeight - innerHeight;
  top = Math.max(0, Math.min(maxTop, Math.round(top)));
  const start = scrollY, d = top - start, t0 = performance.now();
  if (!d) return top;
  await new Promise((res) => {
    const step = (now) => {
      const p = Math.min(1, (now - t0) / ms);
      const e = p < 0.5 ? 4 * p * p * p : 1 - Math.pow(-2 * p + 2, 3) / 2;
      window.scrollTo({ top: start + d * e, behavior: 'instant' });
      if (p < 1) requestAnimationFrame(step); else res();
    };
    requestAnimationFrame(step);
  });
  return top;
}
"""

# Where an element should land: 'center' if it fits, else its top a margin below the viewport top.
TARGET_TOP_JS = r"""
([sel, align, margin]) => {
  const el = typeof sel === 'string' ? document.querySelector(sel) : sel;
  const r = el.getBoundingClientRect();
  if (align === 'center' && r.height < innerHeight - 2 * margin) return scrollY + r.top - (innerHeight - r.height) / 2;
  return scrollY + r.top - margin;
}
"""


class Recorder:
    """Collects CDP screencast frames (with their own timestamps) and key-moment events for one clip."""

    def __init__(self, clip_id: str):
        self.id = clip_id
        self.dir = FRAMES / clip_id
        shutil.rmtree(self.dir, ignore_errors=True)
        self.dir.mkdir(parents=True)
        self.frames: list[tuple[float, Path]] = []
        self.events: list[tuple[float, str, list | None]] = []
        self.cdp = None
        self.end = None
        self._tasks = set()
        self.skew = None

    async def attach(self, page) -> None:
        cdp = await page.context.new_cdp_session(page)
        self.cdp = cdp
        cdp.on("Page.screencastFrame", lambda p: self._spawn(cdp, p))
        await cdp.send("Page.startScreencast", {"format": "jpeg", "quality": 90, "everyNthFrame": 1,
                                                "maxWidth": W, "maxHeight": H})

    def _spawn(self, cdp, p) -> None:
        now = time.time()
        ts = float((p.get("metadata") or {}).get("timestamp") or now)
        if self.skew is None:
            self.skew = now - ts
        path = self.dir / f"f{len(self.frames):06d}.jpg"
        path.write_bytes(base64.b64decode(p["data"]))
        self.frames.append((ts, path))
        t = asyncio.ensure_future(self._ack(cdp, p["sessionId"]))
        self._tasks.add(t)
        t.add_done_callback(self._tasks.discard)

    @staticmethod
    async def _ack(cdp, sid) -> None:
        try:
            await cdp.send("Page.screencastFrameAck", {"sessionId": sid})
        except Exception:
            pass

    async def detach(self) -> None:
        if not self.cdp:
            return
        try:
            await self.cdp.send("Page.stopScreencast")
        except Exception:
            pass
        await asyncio.sleep(0.15)
        try:
            await self.cdp.detach()
        except Exception:
            pass
        self.cdp = None

    async def stop(self) -> None:
        self.end = time.time()
        await self.detach()

    def mark(self, label: str, box: list | None = None) -> None:
        self.events.append((time.time(), label, box))
        print(f"  [{self.id}] {label}" + (f" box={box}" if box else ""), flush=True)

    def encode(self) -> Path:
        frames = sorted(self.frames, key=lambda f: f[0])
        if not frames:
            raise SystemExit(f"{self.id}: no frames captured")
        t0 = frames[0][0]
        end = self.end - (self.skew or 0.0)  # wall clock -> frame clock
        lines = ["ffconcat version 1.0"]
        for i, (ts, path) in enumerate(frames):
            nxt = frames[i + 1][0] if i + 1 < len(frames) else max(end, ts + 1 / 30)
            # framerate 1000: millisecond timestamps (the image2 default of 1/25 s rounds and drifts)
            lines += [f"file '{path.name}'", "option framerate 1000", f"duration {max(nxt - ts, 0.0005):.6f}"]
        lines += [f"file '{frames[-1][1].name}'", "option framerate 1000"]
        total = max(end, frames[-1][0] + 1 / 30) - t0
        lst = self.dir / "frames.ffconcat"
        lst.write_text("\n".join(lines) + "\n")
        CLIPS.mkdir(parents=True, exist_ok=True)
        out = CLIPS / f"{self.id}.mp4"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst),
                        # JPEG frames are full-range BT.601: convert to limited-range BT.709 and tag it
                        "-vf", "fps=30,scale=in_range=full:out_range=limited:in_color_matrix=bt601"
                               ":out_color_matrix=bt709,format=yuv420p",
                        "-c:v", "libx264", "-crf", "18", "-preset", "medium", "-r", "30",
                        "-color_range", "tv", "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
                        "-t", f"{total:.3f}", "-an", "-movflags", "+faststart", str(out)], check=True)
        ev = []
        for wall, label, box in self.events:
            e = {"t": max(0.0, round(wall - (self.skew or 0.0) - t0, 2)), "label": label}
            if box:
                e["box"] = box
            ev.append(e)
        (CLIPS / f"{self.id}.events.json").write_text(json.dumps(ev, indent=2) + "\n")
        print(f"  [{self.id}] {len(frames)} frames, {end - t0:.1f} s, clock skew {self.skew:+.3f} s -> {out}", flush=True)
        return out


class Driver:
    """Human-paced mouse, typing and scrolling on one page."""

    def __init__(self, page, rec: Recorder):
        self.page = page
        self.rec = rec
        self.x, self.y = W * 0.62, H * 0.55

    async def pause(self, s: float) -> None:
        await asyncio.sleep(s)

    async def park(self, x: float, y: float) -> None:
        self.x, self.y = x, y
        await self.page.mouse.move(x, y)

    async def glide(self, x: float, y: float, dur: float = 0.75, steps: int = 25) -> None:
        x0, y0 = self.x, self.y
        for i in range(1, steps + 1):
            p = i / steps
            e = 4 * p ** 3 if p < 0.5 else 1 - (-2 * p + 2) ** 3 / 2  # ease in-out
            await self.page.mouse.move(x0 + (x - x0) * e, y0 + (y - y0) * e)
            await asyncio.sleep(dur / steps)
        self.x, self.y = x, y

    async def point(self, locator, fx: float = 0.5, fy: float = 0.5, dx: float = 0, dur: float = 0.75):
        box = await locator.bounding_box()
        if not box:
            raise SystemExit(f"{self.rec.id}: element not visible for pointing")
        x = box["x"] + (box["width"] * fx if dx == 0 else dx)
        y = box["y"] + box["height"] * fy
        if not (0 <= x < W and 0 <= y < H):
            raise SystemExit(f"{self.rec.id}: target at ({x:.0f}, {y:.0f}) is outside the viewport")
        await self.glide(x, y, dur=dur)
        return x, y

    @staticmethod
    def _clip(x: float, y: float, w: float, h: float) -> list | None:
        """[x, y, w, h] clipped to the viewport; None when the element is off screen."""
        x0, y0, x1, y1 = max(0, x), max(0, y), min(W, x + w), min(H, y + h)
        return [round(x0), round(y0), round(x1 - x0), round(y1 - y0)] if x1 > x0 and y1 > y0 else None

    @staticmethod
    async def box(locator) -> list | None:
        if not await locator.count():
            return None
        b = await locator.first.bounding_box(timeout=5000)
        return Driver._clip(b["x"], b["y"], b["width"], b["height"]) if b else None

    @staticmethod
    async def text_box(locator) -> list | None:
        """Tight box around an element's text (a table cell is often much taller than its number)."""
        if not await locator.count():
            return None
        b = await locator.first.evaluate("""el => { const r = document.createRange(); r.selectNodeContents(el);
            const b = r.getBoundingClientRect(); return [b.x, b.y, b.width, b.height]; }""")
        return Driver._clip(*b)

    async def click_here(self, hold: float = 0.09) -> None:
        await self.page.mouse.down()
        await asyncio.sleep(hold)
        await self.page.mouse.up()

    async def click(self, locator, settle: float = 0.25, **kw) -> None:
        await self.point(locator, **kw)
        await asyncio.sleep(settle)
        await self.click_here()

    async def scroll_to(self, target, align: str = "center", margin: int = 80, ms: float | None = None) -> None:
        top = await self.page.evaluate(TARGET_TOP_JS, [target, align, margin]) if isinstance(target, str) \
            else await target.evaluate("(el, a) => (" + TARGET_TOP_JS + ")([el, a[0], a[1]])", [align, margin])
        cur = await self.page.evaluate("scrollY")
        if ms is None:
            ms = max(700, min(1900, 550 + abs(top - cur) * 0.75))
        await self.page.evaluate(SMOOTH_SCROLL_JS, {"top": top, "ms": ms})
        await asyncio.sleep(0.15)

    async def reveal(self, locator, margin: int = 110) -> None:
        """Smooth-scroll down just enough that the element's bottom sits `margin` px above the viewport bottom."""
        r = await locator.first.bounding_box(timeout=5000)  # unclipped: the element may be below the fold
        if r and r["y"] + r["height"] > H - margin:
            cur = await self.page.evaluate("scrollY")
            d = r["y"] + r["height"] - (H - margin)
            await self.page.evaluate(SMOOTH_SCROLL_JS, {"top": cur + d, "ms": max(700, min(1500, 550 + d * 0.75))})
            await asyncio.sleep(0.2)

    async def set_week(self, iso: str) -> None:
        """Click the date field's first segment and type the date (en-AU: dd mm yyyy)."""
        y, m, d = iso.split("-")
        field = self.page.locator("#week-ending")
        await self.click(field, dx=26, dur=0.8)
        await asyncio.sleep(0.25)
        for chunk in (d, m, y):
            await self.page.keyboard.type(chunk, delay=110)
            await asyncio.sleep(0.12)
        if await field.input_value() != iso:
            print(f"  [{self.rec.id}] typed date did not stick ({await field.input_value()!r}); filling", flush=True)
            await field.fill(iso)
        await self.page.keyboard.press("Tab")

    async def run_and_wait(self, timeout_s: float) -> float:
        btn = self.page.locator("#run-btn")
        await self.reveal(btn)
        await self.point(btn, dur=0.9)
        await asyncio.sleep(0.35)
        run_box = await self.box(btn)
        await self.click_here()
        self.rec.mark("run_clicked", run_box)
        t0 = time.time()
        deadline = t0 + timeout_s
        while time.time() < deadline:
            if await self.page.locator("#summary").is_visible():
                took = time.time() - t0
                self.rec.mark("results_visible", await self.box(self.page.locator("#summary")))
                print(f"  [{self.rec.id}] run took {took:.1f} s", flush=True)
                return took
            err = self.page.locator("#run-error")
            if await err.is_visible():
                raise SystemExit(f"{self.rec.id}: run failed: {await err.inner_text()}")
            await asyncio.sleep(0.2)
        raise SystemExit(f"{self.rec.id}: run did not finish in {timeout_s:.0f} s")


async def open_app(browser, url: str):
    ctx = await browser.new_context(viewport={"width": W, "height": H}, device_scale_factor=1,
                                    color_scheme="light", locale="en-AU", timezone_id="Australia/Melbourne")
    await ctx.add_init_script(CURSOR_JS)
    page = await ctx.new_page()
    await page.goto(url, wait_until="load")
    await page.wait_for_function("document.getElementById('status').dataset.state !== 'checking'", timeout=15000)
    state = await page.evaluate("document.getElementById('status').dataset.state")
    if state != "ok":
        raise SystemExit(f"app is not in local mode (status {state!r}); is `python -m arvo serve` running?")
    await page.wait_for_timeout(400)
    return ctx, page


async def clip_text(browser, url: str) -> Recorder:
    rec = Recorder("s06_demo_text")
    ctx, page = await open_app(browser, url)
    d = Driver(page, rec)
    await d.park(W * 0.62, H * 0.42)
    await rec.attach(page)
    rec.mark("page_loaded")
    await d.pause(1.2)

    await d.set_week("2026-11-08")
    rec.mark("week_set")
    await d.pause(0.5)

    diary = (ROOT / "docs" / "demo" / "diary.txt").read_text()
    lines = diary.splitlines(keepends=True)
    head = "".join(lines[:3])  # header, blank line, Monday: typed with visible keystrokes
    rest = diary[len(head):]
    await d.click(page.locator("#diary"), fx=0.35, fy=0.3, dur=0.8)
    await d.pause(0.3)
    rec.mark("typing_start")
    await page.keyboard.type(head, delay=25)
    await d.pause(0.5)
    await page.keyboard.insert_text(rest)  # the rest arrives as a paste
    rec.mark("diary_pasted")
    await d.pause(0.4)
    await page.evaluate("document.getElementById('diary').scrollTop = 0")
    await d.pause(1.6)

    await d.run_and_wait(240)
    await d.pause(2.6)

    await d.glide(W * 0.86, H * 0.5, dur=0.6)  # cursor out of the way of the reading area
    await d.scroll_to("#flags", "center", margin=60)
    rec.mark("flags_in_view", await d.box(page.locator("#flags")))
    marks = page.locator("#flags li.flag mark.evidence")
    pantry = marks.filter(has_text="pantry")
    pantry = pantry.first if await pantry.count() else marks.first
    rec.mark("pantry_quote", await d.box(pantry))
    await d.pause(3.0)

    await d.scroll_to("#shifts", "top", margin=40)
    rec.mark("shifts_in_view", await d.box(page.locator("#shifts")))
    await d.pause(2.0)

    jake = page.locator("article.inv").filter(has=page.locator("h4", has_text="Jake")).first
    await d.scroll_to(jake, "center", margin=60)
    rec.mark("invoices_in_view", await d.box(jake))
    totals = jake.locator("td.c-total")
    cup = totals.filter(has_text="899.03")
    if not await cup.count():
        print(f"  [{rec.id}] no $899.03 line for Jake; boxing his first line total", flush=True)
    cup = cup.first if await cup.count() else totals.first
    rec.mark("cup_day_total", await d.text_box(cup))
    await d.pause(2.7)
    why = cup.locator("xpath=ancestor::tr[1]").locator("button.why")
    why = why if await why.count() else jake.locator("button.why").first
    await d.point(why, dur=0.9)
    await d.pause(0.3)
    why_box = await d.box(why)
    await d.click_here()
    rec.mark("why_clicked", why_box)
    await d.pause(0.15)
    rule = jake.locator("tr.rule-row:not([hidden])").first
    if await rule.count():
        rec.mark("why_rule", await d.box(rule))
    await d.pause(2.6)

    print_btn = jake.locator(".inv-head button", has_text="Print invoice")
    await d.point(print_btn, dur=0.9)
    await d.pause(0.35)
    print_box = await d.box(print_btn)
    async with ctx.expect_page() as pinfo:
        await d.click_here()
    rec.mark("print_clicked", print_box)
    popup = await pinfo.value
    await popup.wait_for_load_state("load")
    await rec.detach()
    await rec.attach(popup)
    await popup.wait_for_timeout(200)
    rec.mark("invoice_open", await Driver.box(popup.locator("table").first))
    before = len(rec.frames)
    await d.pause(3.4)
    if len(rec.frames) == before:  # a static page may send no screencast frame: add one by hand
        shot = rec.dir / "popup.jpg"
        await popup.screenshot(path=str(shot), type="jpeg", quality=90)
        rec.frames.append((time.time() - (rec.skew or 0.0) - 3.4, shot))
    await rec.stop()
    await ctx.close()
    return rec


async def clip_photo(browser, url: str) -> Recorder:
    rec = Recorder("s07_demo_photo")
    week = json.loads((ROOT / "eval" / "fixtures" / "week13.gold.json").read_text())["week_ending"]
    ctx, page = await open_app(browser, url)
    d = Driver(page, rec)
    await d.park(W * 0.62, H * 0.42)
    await rec.attach(page)
    rec.mark("page_loaded")
    await d.pause(1.0)

    await d.set_week(week)
    rec.mark("week_set")
    await d.pause(0.5)

    drop = page.locator("#drop")
    await d.point(drop, dur=0.9)
    await d.pause(0.4)
    drop_box = await d.box(drop)
    async with page.expect_file_chooser() as fc:
        await d.click_here()
    chooser = await fc.value
    await chooser.set_files(str(ROOT / "eval" / "fixtures" / "week13.png"))
    rec.mark("photo_dropzone", drop_box)  # the dropzone as it was when the file was chosen
    await page.locator("#photo-chosen").wait_for(state="visible", timeout=10000)
    await d.pause(0.1)
    rec.mark("photo_added", await d.box(page.locator("#photo-chosen")))  # the chosen-photo card that replaces it
    await d.pause(2.6)

    await d.run_and_wait(600)
    first = page.locator("#shifts tbody tr").first
    fb = await d.box(first)
    if fb and fb[1] + fb[3] < H:  # already on screen when the results appear
        rec.mark("first_shift_row", fb)
    await d.pause(2.6)
    await d.glide(W * 0.86, H * 0.5, dur=0.6)
    await d.scroll_to("#shifts", "top", margin=40)
    rec.mark("shifts_in_view", await d.box(page.locator("#shifts")))
    rec.mark("first_shift_row", await d.box(first))
    await d.pause(3.0)
    await rec.stop()
    await ctx.close()
    return rec


async def clip_voice(browser, url: str) -> Recorder:
    rec = Recorder("s08_demo_voice")
    audio = sorted((ROOT / "eval" / "voice" / "heldout" / "audio").iterdir())[:3]
    dates = ["2026-12-21", "2026-12-22", "2026-12-23"]
    ctx, page = await open_app(browser, url)
    d = Driver(page, rec)
    await d.park(W * 0.62, H * 0.42)
    await rec.attach(page)
    rec.mark("page_loaded")
    await d.pause(1.0)

    await d.set_week("2026-12-27")
    rec.mark("week_set")
    await d.pause(0.5)

    btn = page.locator("label[for='audio-files']")
    await d.point(btn, dur=0.9)
    await d.pause(0.4)
    async with page.expect_file_chooser() as fc:
        await d.click_here()
    chooser = await fc.value
    await chooser.set_files([str(p) for p in audio])
    await page.locator("#memo-list").wait_for(state="visible", timeout=10000)
    await d.pause(0.7)
    await d.glide(W * 0.86, H * 0.55, dur=0.6)
    await d.reveal(page.locator("#run-btn"))  # the memo list pushes the run button below the fold
    rec.mark("memos_added", await d.box(page.locator("#memo-list")))
    for i, want in enumerate(dates):
        inp = page.locator("#memo-list li.memo").nth(i).locator("input[type='date']")
        have = await inp.input_value()
        if have != want:
            print(f"  [{rec.id}] memo {i + 1} date {have!r} -> {want}", flush=True)
            await d.point(inp, dur=0.6)
            await inp.fill(want)
    await d.pause(2.6)

    await d.run_and_wait(900)
    await d.pause(2.6)
    heard = page.locator("details.heard")
    await d.glide(W * 0.86, H * 0.5, dur=0.6)
    await d.scroll_to("#shifts", "top", margin=40)
    if await heard.count():
        if not await heard.evaluate("el => el.open"):
            await d.click(heard.locator("summary"), dur=0.8)
            await d.pause(0.6)
            await d.glide(W * 0.86, H * 0.5, dur=0.6)
        rec.mark("heard_in_view", await d.box(heard))
        await d.pause(3.0)
    else:
        print(f"  [{rec.id}] no 'What Gemma heard' panel in the results", flush=True)
    first = page.locator("#shifts tbody tr").first
    fb = await d.box(first)
    if fb and fb[1] + fb[3] > H - 20:  # shift rows below the fold: bring the table up under the transcripts
        await d.scroll_to("#shifts table", "center", margin=40)
    rec.mark("shifts_in_view", await d.box(page.locator("#shifts")))
    if await first.count():
        rec.mark("first_shift_row", await d.box(first))
    await d.pause(3.0)
    await rec.stop()
    await ctx.close()
    return rec


CLIP_FNS = {"s06_demo_text": clip_text, "s07_demo_photo": clip_photo, "s08_demo_voice": clip_voice}
# Stills for a quick visual check: (event label, offset in seconds).
STILL_AT = {
    "s06_demo_text": [("pantry_quote", 1.5), ("why_clicked", 1.5), ("invoice_open", 1.5)],
    "s07_demo_photo": [("photo_added", 1.5), ("results_visible", 1.0), ("shifts_in_view", 2.0)],
    "s08_demo_voice": [("memos_added", 2.0), ("results_visible", 1.0), ("heard_in_view", 2.0)],
}


def stills(clip_id: str) -> None:
    STILLS.mkdir(parents=True, exist_ok=True)
    ev = {e["label"]: e["t"] for e in json.loads((CLIPS / f"{clip_id}.events.json").read_text())}
    for label, off in STILL_AT[clip_id]:
        args = ["-ss", f"{ev[label] + off:.2f}"] if label in ev else ["-sseof", "-0.5"]
        label = label if label in ev else "end"
        out = STILLS / f"{clip_id}_{label}.png"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args, "-i", str(CLIPS / f"{clip_id}.mp4"),
                        "-frames:v", "1", str(out)], check=True)


async def main_async(args) -> None:
    async with async_playwright() as p:
        # en-AU UI locale so the date field reads dd/mm/yyyy, as an Australian user sees it
        browser = await p.chromium.launch(executable_path=args.chromium, headless=True, args=["--lang=en-AU"],
                                          env={**os.environ, "LANGUAGE": "en_AU", "LANG": "en_AU.UTF-8"})
        for cid in args.only or list(CLIP_FNS):
            print(f"recording {cid}", flush=True)
            rec = await CLIP_FNS[cid](browser, args.url)
            rec.encode()
            stills(cid)
            if not args.keep_frames:
                shutil.rmtree(rec.dir, ignore_errors=True)
        await browser.close()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--chromium", default="/usr/bin/chromium")
    ap.add_argument("--url", default="http://127.0.0.1:8765/")
    ap.add_argument("--only", nargs="*", choices=list(CLIP_FNS))
    ap.add_argument("--keep-frames", action="store_true")
    asyncio.run(main_async(ap.parse_args()))


if __name__ == "__main__":
    main()
