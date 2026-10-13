"""Render a red hand-drawn annotation (loop or arrow) as transparent PNG frames for the assembler.

  python video/annotate.py --box X Y W H --src-size 1920 1080 --rect-json video/scenes/frame_rect.json \
      --duration 2.4 --kind loop --out DIR

Writes DIR/a_0000.png ... (1920x1080 RGBA, 30 fps). Drawn at 12 fps ("on twos") like the scenes and
duplicated up to 30 fps. The box is in clip pixels; it is mapped into the frame rect (where the
assembler places the clip). Uses video/scenes/annotate.html + lib/line.js (needs Playwright:
`uv run --with playwright python video/annotate.py ...`).
"""
from __future__ import annotations

import argparse
import functools
import http.server
import json
import math
import shutil
import threading
from pathlib import Path

VIDEO = Path(__file__).resolve().parent
CHROMIUM = "/usr/bin/chromium"
FPS_DRAW, FPS_OUT = 12, 30


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--box", type=float, nargs=4, required=True, metavar=("X", "Y", "W", "H"))
    ap.add_argument("--src-size", type=float, nargs=2, default=[1920, 1080], metavar=("W", "H"))
    ap.add_argument("--rect-json", type=Path, default=VIDEO / "scenes" / "frame_rect.json")
    ap.add_argument("--duration", type=float, default=2.4)
    ap.add_argument("--kind", choices=["loop", "arrow"], default="loop")
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()

    rect = json.loads(a.rect_json.read_text()) if a.rect_json and a.rect_json.exists() else {"x": 0, "y": 0, "w": 1920, "h": 1080}
    a.out.mkdir(parents=True, exist_ok=True)

    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args, **kwargs):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=str(VIDEO)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    q = (f"box={','.join(str(v) for v in a.box)}&src={a.src_size[0]},{a.src_size[1]}"
         f"&rect={rect['x']},{rect['y']},{rect['w']},{rect['h']}&kind={a.kind}&d={a.duration}&t=0")
    from playwright.sync_api import sync_playwright

    n_out = max(1, round(a.duration * FPS_OUT))
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=CHROMIUM, args=["--disable-gpu", "--hide-scrollbars"])
            page = browser.new_page(viewport={"width": 1920, "height": 1080}, device_scale_factor=1)
            page.goto(f"http://127.0.0.1:{port}/scenes/annotate.html?{q}")
            page.wait_for_function("window.sceneReady === true || !!window.sceneError", timeout=30000)
            err = page.evaluate("window.sceneError || null")
            if err:
                raise RuntimeError(err)
            drawn: dict[int, Path] = {}
            for k in range(n_out):
                f = math.floor(k / FPS_OUT * FPS_DRAW + 1e-9)
                dst = a.out / f"a_{k:04d}.png"
                if f not in drawn:
                    page.evaluate(f"window.renderAt({f / FPS_DRAW})")
                    page.screenshot(path=str(dst), omit_background=True)
                    drawn[f] = dst
                else:
                    shutil.copy(drawn[f], dst)
            browser.close()
    finally:
        srv.shutdown()
    print(f"{n_out} frames ({len(drawn)} drawn) -> {a.out}/a_%04d.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
