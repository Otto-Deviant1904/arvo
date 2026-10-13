"""Record frames of the local app reading the demo diary with live Gemma, then stitch them with ffmpeg.

Needs `python -m arvo serve` running on 127.0.0.1:8765, a Chromium binary and ffmpeg.
    uv run --with playwright python scripts/record_demo.py --chromium /usr/bin/chromium --out out/video
"""
import argparse
import shutil
import subprocess
import threading
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--chromium", default="/usr/bin/chromium")
    ap.add_argument("--url", default="http://127.0.0.1:8765/")
    ap.add_argument("--out", default=str(ROOT / "out" / "video"))
    args = ap.parse_args()
    diary = (ROOT / "docs" / "demo" / "diary.txt").read_text()
    out = Path(args.out)
    frames = out / "frames"
    shutil.rmtree(frames, ignore_errors=True)
    frames.mkdir(parents=True)
    n = 0

    def snap(page, hold: float = 0.0) -> None:
        nonlocal n
        page.screenshot(path=str(frames / f"f{n:05d}.png"))
        n += 1
        if hold:
            for _ in range(int(hold * 4) - 1):  # 4 fps video: repeat the frame to hold it
                shutil.copy(frames / f"f{n - 1:05d}.png", frames / f"f{n:05d}.png")
                n += 1

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=args.chromium, headless=True)
        ctx = browser.new_context(viewport={"width": 1280, "height": 760}, color_scheme="light")
        page = ctx.new_page()
        page.goto(args.url)
        page.wait_for_timeout(1200)
        page.fill("#week-ending", "2026-11-08")
        snap(page, 1.0)
        for i in range(0, len(diary), 40):                # the diary appears line by line
            page.fill("#diary", diary[: i + 40])
            snap(page)
        snap(page, 1.0)
        t0 = time.time()
        page.click("#run-btn")
        done = threading.Event()
        while not done.is_set():                            # real elapsed time, compressed: one frame per second
            if page.is_visible("#summary"):
                break
            if time.time() - t0 > 180:
                raise SystemExit("run did not finish in 180 s")
            snap(page)
            page.wait_for_timeout(1000)
        took = time.time() - t0
        print(f"run took {took:.1f}s")
        page.wait_for_timeout(600)
        snap(page, 2.0)
        for _ in range(16):                                 # scroll through flags, shifts, invoices
            page.mouse.wheel(0, 240)
            page.wait_for_timeout(250)
            snap(page, 0.5)
        snap(page, 2.0)
        ctx.close()
        browser.close()
    mp4 = out / "arvo-demo.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", "4", "-i", str(frames / "f%05d.png"),
                    "-vf", "scale=1280:-2", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "24", str(mp4)], check=True)
    gif = out / "arvo-demo.gif"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", "4", "-i", str(frames / "f%05d.png"),
                    "-vf", "scale=900:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=96[p];[b][p]paletteuse=dither=bayer",
                    str(gif)], check=True)
    print("video:", mp4, "gif:", gif, f"frames: {n}")


if __name__ == "__main__":
    main()
