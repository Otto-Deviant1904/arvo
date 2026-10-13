"""Render the hand-drawn scenes in video/scenes/<id>.html to video/scenes/<id>.mp4.

Each scene page exposes window.renderAt(t). We step t at 1/12 s ("on twos"), screenshot
every frame with headless system Chromium (Playwright), and ffmpeg duplicates frames up to
30 fps (H.264, yuv420p, crf 18).

Scene length = narration duration from --durations (video/audio/durations.json) + --pad
(default 0.9 s). If the file or the id is missing, --default-length is used (8 s).
Accepted durations.json shapes: {"s02_hook": 7.4, ...}, {"s02_hook": {"duration": 7.4}},
or [{"id": "s02_hook", "duration": 7.4}, ...] (keys "duration", "seconds" or "dur").

Usage:
  uv run --with playwright python video/render_scenes.py                 # all scenes
  uv run --with playwright python video/render_scenes.py s02_hook --length 9
  uv run --with playwright python video/render_scenes.py --durations video/audio/durations.json --jobs 4 --split 3
  uv run --with playwright python video/render_scenes.py s02_hook --stills 0,0.5,1   # PNG stills only
"""
from __future__ import annotations

import argparse
import functools
import http.server
import json
import math
import shutil
import subprocess
import sys
import tempfile
import threading
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

VIDEO = Path(__file__).resolve().parent
SCENES = VIDEO / "scenes"
FPS_DRAW = 12
FPS_OUT = 30
CHROMIUM = "/usr/bin/chromium"
ALL_IDS = ["s01_title", "s02_hook", "s03_who", "s04_trap_price", "s05_trap_pantry", "s09_how",
           "s10_results", "s11_lesson", "s12_open", "s13_pay", "s14_end"]


def load_durations(path: Path | None) -> dict[str, float]:
    if not path or not path.exists():
        return {}
    data = json.loads(path.read_text())
    out: dict[str, float] = {}

    def num(v):
        if isinstance(v, (int, float)):
            return float(v)
        if isinstance(v, dict):
            for k in ("duration", "seconds", "dur", "length"):
                if k in v:
                    return float(v[k])
        return None

    if isinstance(data, dict):
        for k, v in data.items():
            n = num(v)
            if n is not None:
                out[k] = n
    elif isinstance(data, list):
        for row in data:
            if isinstance(row, dict) and "id" in row:
                n = num(row)
                if n is not None:
                    out[row["id"]] = n
    return out


def serve(root: Path) -> tuple[http.server.ThreadingHTTPServer, int]:
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args, **kwargs):
            pass

    handler = functools.partial(Quiet, directory=str(root))
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_address[1]


def open_scene(page, port: int, sid: str, length: float):
    page.goto(f"http://127.0.0.1:{port}/scenes/{sid}.html?d={length}&t=0")
    page.wait_for_function("window.sceneReady === true || !!window.sceneError", timeout=30000)
    err = page.evaluate("window.sceneError || null")
    if err:
        raise RuntimeError(f"{sid}: {err}")


def _browser_page(p):
    browser = p.chromium.launch(executable_path=CHROMIUM, args=["--disable-gpu", "--hide-scrollbars"])
    page = browser.new_page(viewport={"width": 1920, "height": 1080}, device_scale_factor=1)
    return browser, page


def render_stills(sid: str, length: float, out_dir: str, stills: list[float], transparent: bool = False) -> str:
    from playwright.sync_api import sync_playwright

    srv, port = serve(VIDEO)
    out = Path(out_dir)
    try:
        with sync_playwright() as p:
            browser, page = _browser_page(p)
            open_scene(page, port, sid, length)
            paths = []
            for frac in stills:
                t = min(length, max(0.0, frac * length))
                page.evaluate(f"window.renderAt({t})")
                pth = out / f"{sid}_t{t:05.2f}.png"
                page.screenshot(path=str(pth), omit_background=transparent)
                paths.append(str(pth))
            browser.close()
        return f"{sid}: stills " + ", ".join(paths)
    finally:
        srv.shutdown()


def render_chunk(sid: str, length: float, frames: list[int], tmp: str) -> int:
    """Render the given frame numbers of one scene into tmp/%05d.png (own browser + server)."""
    from playwright.sync_api import sync_playwright

    srv, port = serve(VIDEO)
    try:
        with sync_playwright() as p:
            browser, page = _browser_page(p)
            open_scene(page, port, sid, length)
            for i in frames:
                page.evaluate(f"window.renderAt({i / FPS_DRAW})")
                page.screenshot(path=str(Path(tmp) / f"{i:05d}.png"))
            browser.close()
        return len(frames)
    finally:
        srv.shutdown()


def encode(sid: str, n: int, tmp: Path, out: Path, keep_frames: bool) -> str:
    mp4 = out / f"{sid}.mp4"
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(FPS_DRAW), "-i", str(tmp / "%05d.png"),
           "-vf", f"fps={FPS_OUT}", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18",
           "-preset", "medium", "-movflags", "+faststart", str(mp4)]
    subprocess.run(cmd, check=True)
    shutil.copy(tmp / f"{n - 1:05d}.png", out / f"{sid}_last.png")  # last frame, for checking / fallback
    if not keep_frames:
        shutil.rmtree(tmp, ignore_errors=True)
    return f"{sid}: {n} frames at {FPS_DRAW} fps = {n / FPS_DRAW:.2f} s -> {mp4}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("ids", nargs="*", help="scene ids (default: all)")
    ap.add_argument("--durations", type=Path, default=VIDEO / "audio" / "durations.json")
    ap.add_argument("--pad", type=float, default=0.9, help="seconds added to each narration duration")
    ap.add_argument("--default-length", type=float, default=8.0, help="length when no duration is known")
    ap.add_argument("--length", type=float, help="force this length (seconds) for every scene given")
    ap.add_argument("--out", type=Path, default=SCENES)
    ap.add_argument("--jobs", type=int, default=3, help="parallel browser processes")
    ap.add_argument("--split", type=int, default=3, help="browser processes per scene (frames interleaved)")
    ap.add_argument("--stills", help="comma-separated fractions of the length; write PNG stills instead of mp4")
    ap.add_argument("--keep-frames", action="store_true")
    ap.add_argument("--transparent", action="store_true", help="stills only: keep the page background transparent (RGBA)")
    a = ap.parse_args()

    ids = a.ids or [i for i in ALL_IDS if (SCENES / f"{i}.html").exists()]
    durs = load_durations(a.durations)
    a.out.mkdir(parents=True, exist_ok=True)
    jobs = []
    for sid in ids:
        if not (SCENES / f"{sid}.html").exists():
            print(f"skip {sid}: no scenes/{sid}.html", file=sys.stderr)
            continue
        if a.length:
            length = a.length
        elif sid in durs:
            length = durs[sid] + a.pad
        else:
            length = a.default_length
        jobs.append((sid, round(length, 3)))
    stills = [float(x) for x in a.stills.split(",")] if a.stills else None
    with ProcessPoolExecutor(max_workers=max(1, a.jobs)) as ex:
        if stills is not None:
            for f in [ex.submit(render_stills, sid, length, str(a.out), stills, a.transparent) for sid, length in jobs]:
                print(f.result(), flush=True)
            return 0
        # every scene's frames are split into --split interleaved chunks, each in its own browser
        pending = []
        for sid, length in jobs:
            n = max(1, math.ceil(length * FPS_DRAW - 1e-6))
            tmp = Path(tempfile.mkdtemp(prefix=f"frames_{sid}_"))
            k = max(1, min(a.split, n))
            futs = [ex.submit(render_chunk, sid, length, list(range(c, n, k)), str(tmp)) for c in range(k)]
            pending.append((sid, n, tmp, futs))
        for sid, n, tmp, futs in pending:
            done = sum(f.result() for f in futs)
            assert done == n, (sid, done, n)
            print(encode(sid, n, tmp, a.out, a.keep_frames), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
