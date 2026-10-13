"""Assemble the Arvo video from slides, screen clips and narration.

    python3 video/assemble.py [--memo eval/voice/heldout/audio/<file>] [--memo-seconds 6] [--no-captions]

Reads video/script.json (segment order), video/audio/<id>.wav (narration), video/slides/<id>.png
or video/clips/<id>.mp4 (+ <id>.events.json). Writes video/arvo.mp4 (captions burned in),
video/arvo.srt and video/build/arvo_nocaps.mp4. Needs ffmpeg/ffprobe and Pillow (for clip labels).
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

VIDEO = Path(__file__).resolve().parent
ROOT = VIDEO.parent
BUILD = VIDEO / "build"
W, H, FPS, SR = 1920, 1080, 30, 48000
PRE, POST = 0.35, 0.55          # silence before / after each narration
FONT = "/usr/share/fonts/noto/NotoSans-SemiBold.ttf"
LABEL_FONT = next(iter(sorted((VIDEO / "vendor" / "fonts").glob("ShantellSans*.ttf"))), Path(FONT))
NAVY = "0x1c2330"
ANNOTATE = {  # clip id -> (event label, kind) to circle with a red loop
    "s06_demo_text": [("pantry_quote", "loop"), ("cup_day_total", "loop")],
    "s07_demo_photo": [("first_shift_row", "loop")],
    "s08_demo_voice": [("heard_in_view", "loop")],
}


def run(cmd: list[str]) -> None:
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"command failed: {' '.join(cmd[:8])} ...\n{r.stderr[-2000:]}")


def duration(path: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True, check=True).stdout.strip()
    return float(out)


def clip_label(text: str, out: Path) -> Path:
    """A small rounded label PNG ("LIVE: gemma4:e4b on a laptop ...") for clip segments."""
    from PIL import Image, ImageDraw, ImageFont
    font = ImageFont.truetype(str(LABEL_FONT), 32)
    try:
        font.set_variation_by_axes([600])
    except Exception:
        pass
    pad_x, pad_y = 26, 14
    tmp = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
    x0, y0, x1, y1 = tmp.textbbox((0, 0), text, font=font)
    w, h = x1 - x0 + 2 * pad_x + 28, y1 - y0 + 2 * pad_y
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, w - 1, h - 1), radius=h // 2, fill=(28, 35, 48, 235), outline=(239, 232, 214, 255), width=3)
    d.ellipse((pad_x - 4, h // 2 - 7, pad_x + 10, h // 2 + 7), fill=(220, 60, 50, 255))
    d.text((pad_x + 24 - x0, pad_y - y0), text, font=font, fill=(239, 232, 214, 255))
    img.save(out)
    return out


def fit_clip(events: dict, clip_len: float, target: float) -> tuple[list[tuple[float, float, float]], float]:
    """Split the clip at run_clicked/results_visible, speed the waiting part up first (max 8x),
    then the rest (max 1.75x). Returns ([(start, end, speed)], effective length)."""
    a, b = events.get("run_clicked"), events.get("results_visible")
    if a is not None and b is not None and 0 <= a < b <= clip_len:
        parts = [(0.0, a, "act"), (a, b, "wait"), (b, clip_len, "act")]
    else:
        parts = [(0.0, clip_len, "act")]
    act = sum(e - s for s, e, k in parts if k == "act")
    wait = sum(e - s for s, e, k in parts if k == "wait")
    s_act = s_wait = 1.0
    if act + wait > target and wait > 0:
        room = max(target - act, wait / 8)
        s_wait = min(8.0, max(1.0, wait / room))
    if act + wait / s_wait > target:
        room = max(target - wait / s_wait, act / 1.75)
        s_act = min(1.75, max(1.0, act / room))
    out = [(s, e, s_wait if k == "wait" else s_act) for s, e, k in parts if e - s > 0.05]
    eff = sum((e - s) / sp for s, e, sp in out)
    return out, eff


def map_time(t: float, parts: list[tuple[float, float, float]]) -> float:
    """Clip time -> output time after the speed changes in fit_clip."""
    out = 0.0
    for s0, e0, sp in parts:
        if t <= e0:
            return out + max(0.0, t - s0) / sp
        out += (e0 - s0) / sp
    return out


def annotations(sid: str, events_raw: list, parts, length: float) -> list[tuple[Path, float]]:
    """Render red loops for this clip's boxed events with video/annotate.py; [(png_dir, start_s)]."""
    rect = VIDEO / "scenes" / "frame_rect.json"
    tool = VIDEO / "annotate.py"
    if not (rect.exists() and tool.exists()):
        return []
    out = []
    for label, kind in ANNOTATE.get(sid, []):
        ev = next((e for e in events_raw if e["label"] == label and e.get("box")), None)
        if not ev:
            continue
        start = map_time(float(ev["t"]), parts) + 0.15
        dur = min(2.4, max(0.8, length - start - 0.1))
        d = BUILD / f"ann_{sid}_{label}"
        if not any(d.glob("a_*.png")):
            d.mkdir(parents=True, exist_ok=True)
            x, y, w, h = ev["box"]
            run(["uv", "run", "-q", "--with", "playwright", "python", str(tool), "--box", str(x), str(y), str(w), str(h),
                 "--src-size", "1920", "1080", "--rect-json", str(rect), "--duration", f"{dur:.2f}",
                 "--kind", kind, "--out", str(d)])
        out.append((d, start))
    return out


def make_segment(i: int, seg: dict, memo: Path | None, memo_s: float) -> tuple[Path, float, float]:
    """Encode one segment. Returns (mp4, length, narration start offset within the segment)."""
    sid = seg["id"]
    narr = VIDEO / "audio" / f"{sid}.wav"
    d = duration(narr)
    front = memo_s if (memo and sid == "s08_demo_voice") else 0.0
    audio_len = front + PRE + d + POST
    slide = VIDEO / "slides" / f"{sid}.png"
    clip = VIDEO / "clips" / f"{sid}.mp4"
    out = BUILD / f"seg{i:02d}_{sid}.mp4"

    scene = VIDEO / "scenes" / f"{sid}.mp4"
    if clip.exists():
        ev_path = VIDEO / "clips" / f"{sid}.events.json"
        events, events_raw = {}, []
        if ev_path.exists():
            events_raw = json.loads(ev_path.read_text())
            for e in events_raw:
                events.setdefault(e["label"], float(e["t"]))
        parts, eff = fit_clip(events, duration(clip), audio_len)
        length = max(audio_len, eff)
        freeze = max(0.0, length - eff)
        chains = [f"[0:v]trim=start={s:.3f}:end={e:.3f},setpts=(PTS-STARTPTS)/{sp:.4f}[p{k}]"
                  for k, (s, e, sp) in enumerate(parts)]
        concat = "".join(f"[p{k}]" for k in range(len(parts))) + f"concat=n={len(parts)}:v=1:a=0[vc]"
        vf = ";".join(chains) + ";" + concat + f";[vc]tpad=stop_mode=clone:stop_duration={freeze:.3f},fps={FPS}[vt]"
        inputs = ["-i", str(clip)]
        n = 1
        frame_png = VIDEO / "scenes" / "frame_overlay.png"
        rect_json = VIDEO / "scenes" / "frame_rect.json"
        if frame_png.exists() and rect_json.exists():
            r = json.loads(rect_json.read_text())
            inputs += ["-f", "lavfi", "-i", f"color=c={NAVY}:s={W}x{H}:r={FPS}:d={length:.3f}",
                       "-loop", "1", "-framerate", str(FPS), "-i", str(frame_png)]
            vf += (f";[vt]scale={r['w']}:{r['h']}[vs];[{n}:v][vs]overlay={r['x']}:{r['y']}[vb0]"
                   f";[vb0][{n + 1}:v]overlay=0:0:shortest=1[vb]")
            n += 2
        else:
            vf += (f";[vt]scale={W}:{H}:force_original_aspect_ratio=decrease,"
                   f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=white[vb]")
        last = "vb"
        for k, (adir, start) in enumerate(annotations(sid, events_raw, parts, length)):
            inputs += ["-framerate", str(FPS), "-i", str(adir / "a_%04d.png")]
            vf += (f";[{n}:v]format=rgba,setpts=PTS-STARTPTS+{start:.3f}/TB[an{k}]"
                   f";[{last}][an{k}]overlay=0:0:eof_action=pass[va{k}]")
            last = f"va{k}"
            n += 1
        label = seg.get("on_screen_caption")
        if label:
            png = clip_label(label, BUILD / f"label_{sid}.png")
            inputs += ["-i", str(png)]
            vf += f";[{last}][{n}:v]overlay=(main_w-overlay_w)/2:22,format=yuv420p[v]"
            n += 1
        else:
            vf += f";[{last}]format=yuv420p[v]"
        n_img = n
    elif scene.exists():
        sc = duration(scene)
        length = max(audio_len, sc)
        inputs = ["-i", str(scene)]
        vf = (f"[0:v]scale={W}:{H},fps={FPS},tpad=stop_mode=clone:stop_duration={max(0.0, length - sc):.3f},"
              f"format=yuv420p[v]")
        n_img = 1
    else:
        if not slide.exists():
            raise SystemExit(f"no scene, slide or clip for {sid}")
        length = audio_len
        inputs = ["-loop", "1", "-framerate", str(FPS), "-i", str(slide)]
        # a slow 2% push-in keeps a still slide alive without being noticeable
        frames = int(length * FPS) + 1
        vf = (f"[0:v]scale={W * 2}:{H * 2},zoompan=z='1+0.02*on/{frames}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
              f":d={frames}:s={W}x{H}:fps={FPS},format=yuv420p[v]")
        n_img = 1

    # audio: optional memo at 0, narration after front + PRE, padded to the segment length
    a_inputs = ["-i", str(narr)]
    na = n_img
    delay = int((front + PRE) * 1000)
    af = (f"[{na}:a]aresample={SR},aformat=channel_layouts=stereo,adelay={delay}|{delay},"
          f"apad,atrim=0:{length:.3f}[n]")
    if front:
        a_inputs += ["-i", str(memo)]
        af += (f";[{na + 1}:a]aresample={SR},aformat=channel_layouts=stereo,atrim=0:{memo_s:.3f},"
               f"afade=t=out:st={memo_s - 0.4:.3f}:d=0.4,volume=0.9,apad,atrim=0:{length:.3f}[m]"
               f";[n][m]amix=inputs=2:duration=first:normalize=0[a]")
    else:
        af += ";[n]anull[a]"
    cmd = (["ffmpeg", "-y", "-loglevel", "error"] + inputs + a_inputs +
           ["-filter_complex", vf + ";" + af, "-map", "[v]", "-map", "[a]", "-t", f"{length:.3f}",
            "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-r", str(FPS), "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", "-ar", str(SR), str(out)])
    run(cmd)
    return out, length, front + PRE


def chunks(text: str, max_chars: int = 84) -> list[str]:
    """Caption chunks: split at sentence ends, then at commas or word boundaries under max_chars."""
    out = []
    for sent in re.split(r"(?<=[.!?])\s+", text.strip()):
        words, cur = sent.split(), ""
        for w in words:
            if cur and len(cur) + 1 + len(w) > max_chars:
                out.append(cur)
                cur = w
            else:
                cur = f"{cur} {w}".strip()
        if cur:
            out.append(cur)
    return out


def ts(t: float, ass: bool = False) -> str:
    h, rem = divmod(max(t, 0), 3600)
    m, s = divmod(rem, 60)
    if ass:
        return f"{int(h)}:{int(m):02d}:{s:05.2f}"
    return f"{int(h):02d}:{int(m):02d}:{int(s):02d},{int(round((s - int(s)) * 1000)):03d}"


def build_captions(timeline: list[tuple[dict, float, float, float]]) -> tuple[str, str]:
    srt, events, n = [], [], 1
    for seg, start, narr_off, d in timeline:
        parts = chunks(seg["narration"])
        total = sum(len(p) for p in parts) or 1
        t = start + narr_off
        for p in parts:
            span = d * len(p) / total
            srt.append(f"{n}\n{ts(t)} --> {ts(t + span)}\n{p}\n")
            events.append(f"Dialogue: 0,{ts(t, True)},{ts(t + span, True)},Cap,,0,0,0,,{p}")
            n += 1
            t += span
    ass = "\n".join([
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {W}", f"PlayResY: {H}", "WrapStyle: 0", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
        "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, "
        "MarginR, MarginV, Encoding",
        "Style: Cap,Noto Sans,46,&H00FFFFFF,&H00FFFFFF,&H00141414,&H96000000,-1,0,0,0,100,100,0,0,1,2.2,2,2,"
        "240,240,54,1",
        "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
        *events, ""])
    return "\n".join(srt), ass


CHAPTERS = {  # segment id -> chapter title (YouTube needs the first at 0:00, 3+ chapters, each >= 10 s)
    "s01_title": "One diary line, two traps",
    "s06_demo_text": "Demo: a week's diary",
    "s07_demo_photo": "Demo: photo and voice memos",
    "s09_how": "The model reads, code decides",
    "s10_results": "Held-out results",
    "s11_lesson": "What went wrong",
    "s12_open": "Why open weights, and who pays",
    "s14_end": "Links",
}


def write_youtube_text(timeline) -> None:
    def mmss(t: float) -> str:
        return f"{int(t // 60)}:{int(t % 60):02d}"
    chapters = [(start, CHAPTERS[seg["id"]]) for seg, start, _, _ in timeline if seg["id"] in CHAPTERS]
    lines = [
        "# YouTube upload text", "",
        "## Title",
        "Arvo: offline NDIS invoicing on Gemma 4 (Hacktoberfest 2026 demo)", "",
        "## Description",
        "An independent NDIS support worker's week of shift notes goes in. Invoice lines priced against the official "
        "NDIS Pricing Schedule 2026-27 come out, plus a flag on any note that describes a restrictive practice. "
        "Gemma 4 runs on the worker's own laptop through Ollama, so no shift notes leave it. The model reads, code decides.",
        "",
        "Code (MIT): https://github.com/Otto-Deviant1904/arvo",
        "Demo page: https://otto-deviant1904.github.io/arvo/",
        "",
        "Chapters:",
        *[f"{mmss(t)} {name}" for t, name in chapters],
        "",
        "All data in the demo and the evaluation is synthetic; Mel is a composite, not a real person. "
        "Not legal or compliance advice. Prices: NDIS Pricing Schedule 2026-27 (Victoria, non-remote).",
        "",
        "Built for the DEV Hacktoberfest Open-Source AI Challenge, Week 2: Side Hustle.",
        "", "## Tags",
        "Gemma 4, Ollama, local AI, open source AI, NDIS, support worker, invoicing, Hacktoberfest, DEV challenge",
        "", "## Captions", "Upload video/arvo.srt only if you upload a version without burned-in captions.", "",
    ]
    (VIDEO / "YOUTUBE.md").write_text("\n".join(lines))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--memo", default=None, help="audio file played at the start of s08_demo_voice")
    ap.add_argument("--memo-seconds", type=float, default=6.0)
    ap.add_argument("--no-captions", action="store_true")
    ap.add_argument("--only", default="", help="comma-separated segment ids, for previews")
    ap.add_argument("--out", default=str(VIDEO / "arvo.mp4"))
    args = ap.parse_args()
    BUILD.mkdir(parents=True, exist_ok=True)
    script = json.loads((VIDEO / "script.json").read_text())
    if args.only:
        keep = set(args.only.split(","))
        script = [seg for seg in script if seg["id"] in keep]
    memo = Path(args.memo) if args.memo else None
    if memo is None:
        memos = sorted((ROOT / "eval" / "voice" / "heldout" / "audio").glob("*"))
        memo = memos[0] if memos else None

    timeline, files, t = [], [], 0.0
    for i, seg in enumerate(script):
        mp4, length, narr_off = make_segment(i, seg, memo, args.memo_seconds)
        d = duration(VIDEO / "audio" / f"{seg['id']}.wav")
        timeline.append((seg, t, narr_off, d))
        files.append(mp4)
        print(f"{seg['id']:<18} {t:6.1f}s +{length:5.1f}s")
        t += length
    lst = BUILD / "concat.txt"
    lst.write_text("".join(f"file '{f}'\n" for f in files))
    nocaps = BUILD / "arvo_nocaps.mp4"
    run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(nocaps)])

    srt, ass = build_captions(timeline)
    (VIDEO / "arvo.srt").write_text(srt)
    (BUILD / "arvo.ass").write_text(ass)
    total = duration(nocaps)
    fade = f"fade=t=in:st=0:d=0.6,fade=t=out:st={total - 0.9:.3f}:d=0.9"
    vf = fade if args.no_captions else f"ass={BUILD / 'arvo.ass'},{fade}"
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(nocaps), "-vf", vf,
         "-af", f"afade=t=in:st=0:d=0.4,afade=t=out:st={total - 0.9:.3f}:d=0.9",
         "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
         "-c:a", "aac", "-b:a", "192k", args.out])
    if not args.only:
        write_youtube_text(timeline)
    print(f"wrote {args.out} ({total:.1f}s), {VIDEO / 'arvo.srt'} and {VIDEO / 'YOUTUBE.md'}")


if __name__ == "__main__":
    main()
