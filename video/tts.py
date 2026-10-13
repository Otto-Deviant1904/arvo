# /// script
# requires-python = ">=3.12,<3.13"
# dependencies = ["kokoro-onnx", "soundfile"]
# ///
"""Narration TTS for the Arvo video: Kokoro-82M (Apache-2.0 open weights) via kokoro-onnx.

Model files (official kokoro-onnx release "model-files-v1.0"):
  kokoro-v1.0.onnx, voices-v1.0.bin  ->  pass their folder as --model-dir

Run from the repo root (--no-project keeps uv away from the arvo project venv):
  uv run --no-project --python 3.12 --with kokoro-onnx --with soundfile python -I video/tts.py \
      --script video/script.json --voice af_heart --speed 0.9 --out video/audio/ --model-dir <dir>

Per segment id: <out>/<id>.wav, 24 kHz mono 16-bit, leading/trailing silence trimmed to
0.15 s, ffmpeg two-pass loudnorm to -16 LUFS (TP -1.5 dB). Also <out>/durations.json {id: s}.
--only id1,id2 re-renders some segments and merges into the existing durations.json.
--dry-run prints the text after pronunciation fixes, plus espeak phonemes, without synthesis.
--audition "TEXT" with --voice a,b,c writes <out>/<voice>.wav per voice and prints rate/peak.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf

SR = 24000
PAD_S = 0.15  # silence kept at each end
TARGET_LUFS = -16.0
TRUE_PEAK = -1.5
LRA = 11.0

# Pronunciation fixes, applied in order before synthesis (regex, replacement).
# Kept conservative: each one was checked against the espeak-ng phonemes kokoro-onnx uses
# (see --dry-run). Words that already come out right are deliberately NOT listed:
#   Arvo -> "AR-voh" (US ˈɑːɹvoʊ / GB ˈɑːvəʊ), Gemma, GitHub, PRN, GPU, JSON, RP, F1,
#   e4b / e2b ("ee four bee"), Melbourne, Cup Day, percentages, plain decimals.
FIXES: list[tuple[str, object]] = [  # replacement: str or callable
    # acronyms said letter by letter (espeak says "end-iss", "ab-en"; spaced "A B N"
    # turns the A into the article "uh", hyphens keep "ay")
    (r"\bNDIS\b", "N-D-I-S"),
    (r"\bABN\b", "A-B-N"),
    # model / tool names
    (r"\bOllama\b", "oh-llama"),  # espeak: "ah-LAH-ma"
    (r"\b[eE]4[bB]\b", "e four b"),
    (r"\b[eE]2[bB]\b", "e two b"),
    # clause references: "s2.4(c)" -> "section two point four c" (espeak: "ess two point four")
    (r"\bs(\d+)\.(\d+)\(([a-z])\)", r"section \1 point \2 \3"),
    # "5.5 h x $163.46": "times" and hours (before money, which removes the $)
    (r"(?<=[\dh]) [x×] (?=[\d$])", " times "),
    (r"(?<=\d)[x×](?=\d)", " times "),
    (r"(?<=\d) ?h\b", " hours"),
    # money: espeak reads "$73.58" as "dollar seventy three point five eight"
    (r"~\s?(?=[$\d])", "about "),
    (r"\$(\d[\d,]*)\.00\b", r"\1 dollars"),
    (r"\$(\d[\d,]*)\.0(\d)\b", r"\1 dollars and \2 cents"),
    (r"\$(\d[\d,]*)\.(\d\d)\b", r"\1 dollars \2"),
    (r"\$1\b(?![.,]\d)", "1 dollar"),
    (r"\$(\d[\d,]*)\b(?![.,]\d)", r"\1 dollars"),
    (r"(?<=dollars) ?/ ?(week|month|year|hour|fortnight)\b", r" a \1"),
    # decimals: espeak sometimes reads "75.9%" as "seventy five. nine" -> "75 point 9"
    (r"(?<![\d.])(\d+)\.(\d+)\b", lambda m: f"{m[1]} point {' '.join(m[2])}"),
    # "7/8 weeks", "6/10" -> "7 out of 8" (espeak: "seven slash eight")
    (r"\b(\d+)/(\d+)\b", r"\1 out of \2"),
    # clock times: "8:30" -> "8 30" (espeak keeps the colon), "8:00" -> "8 o'clock"
    (r"\b(\d{1,2}):00\b", r"\1 o'clock"),
    (r"\b(\d{1,2}):(\d{2})", r"\1 \2"),
    (r"\bTues\b", "Tuesday"),  # espeak: "tooz"
    (r"\bvs\.?(?=\s)", "versus"),  # espeak: "vee ess"
]


def apply_fixes(text: str) -> str:
    for pat, rep in FIXES:
        text = re.sub(pat, rep, text)
    return re.sub(r"\s+", " ", text).strip()


def lang_for(voice: str) -> str:
    return "en-gb" if voice.startswith("b") else "en-us"


def trim_silence(audio: np.ndarray, pad_s: float = PAD_S, rel_db: float = -40.0) -> np.ndarray:
    """Cut leading/trailing silence, then pad both ends with exactly pad_s of digital silence."""
    frame = int(0.01 * SR)
    n = len(audio) // frame
    if n == 0:
        return audio
    rms = np.sqrt(np.mean(audio[: n * frame].reshape(n, frame) ** 2, axis=1) + 1e-12)
    voiced = np.nonzero(rms > rms.max() * 10 ** (rel_db / 20))[0]
    if voiced.size == 0:
        return audio
    start, end = voiced[0] * frame, min(len(audio), (voiced[-1] + 1) * frame)
    pad = np.zeros(int(pad_s * SR), dtype=np.float32)
    return np.concatenate([pad, audio[start:end].astype(np.float32), pad])


def loudnorm(src: Path, dst: Path) -> None:
    """ffmpeg two-pass EBU R128 loudnorm (linear) -> 24 kHz mono s16 WAV."""
    base = f"loudnorm=I={TARGET_LUFS}:TP={TRUE_PEAK}:LRA={LRA}"
    p = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(src), "-af",
         base + ":print_format=json", "-f", "null", "-"],
        capture_output=True, text=True, check=True,
    )
    m = json.loads(p.stderr[p.stderr.rindex("{"): p.stderr.rindex("}") + 1])
    af = (f"{base}:measured_I={m['input_i']}:measured_TP={m['input_tp']}"
          f":measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}"
          f":offset={m['target_offset']}:linear=true")
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-loglevel", "error", "-y", "-i", str(src),
         "-af", af, "-ar", str(SR), "-ac", "1", "-c:a", "pcm_s16le", str(dst)],
        check=True,
    )


def render(kokoro, text: str, voice: str, speed: float, dst: Path) -> dict:
    """Synthesise text -> trimmed, loudness-normalised WAV at dst. Returns stats."""
    audio, sr = kokoro.create(apply_fixes(text), voice=voice, speed=speed, lang=lang_for(voice))
    assert sr == SR, sr
    raw_peak = float(np.max(np.abs(audio)))
    audio = trim_silence(np.asarray(audio, dtype=np.float32))
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td) / "raw.wav"
        sf.write(tmp, audio, SR, subtype="FLOAT")  # float: no clipping before loudnorm
        loudnorm(tmp, dst)
    out, _ = sf.read(dst, dtype="float32")
    dur = len(out) / SR
    words = len(re.findall(r"[A-Za-z0-9$'’-]+", text))
    return {
        "seconds": round(dur, 3),
        "words": words,
        "wps": round(words / max(dur - 2 * PAD_S, 1e-6), 2),
        "raw_peak": round(raw_peak, 3),
        "peak_dbfs": round(20 * np.log10(max(float(np.max(np.abs(out))), 1e-9)), 2),
        "clipped_samples": int(np.sum(np.abs(out) >= 32767 / 32768)),
    }


def load_segments(path: Path) -> list[dict]:
    data = json.loads(path.read_text())
    if isinstance(data, dict):
        data = data.get("segments", data.get("shots", []))
    return [s for s in data if isinstance(s, dict) and s.get("id")]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--script", type=Path, help="script.json [{id, narration, ...}]")
    ap.add_argument("--voice", default="af_heart", help="Kokoro voice (comma list with --audition)")
    ap.add_argument("--speed", type=float, default=0.9)
    ap.add_argument("--out", type=Path, default=Path("video/audio"))
    ap.add_argument("--only", default="", help="comma-separated segment ids")
    ap.add_argument("--model-dir", type=Path, default=os.environ.get("KOKORO_MODEL_DIR"),
                    help="folder with kokoro-v1.0.onnx + voices-v1.0.bin (or $KOKORO_MODEL_DIR)")
    ap.add_argument("--audition", metavar="TEXT", help="render TEXT once per --voice to <out>/<voice>.wav")
    ap.add_argument("--dry-run", action="store_true", help="print fixed text + phonemes, no audio")
    a = ap.parse_args()
    if not a.model_dir:
        ap.error("--model-dir (or $KOKORO_MODEL_DIR) is required")
    if not a.audition and not a.script:
        ap.error("--script or --audition is required")

    from kokoro_onnx import Kokoro

    kokoro = Kokoro(str(a.model_dir / "kokoro-v1.0.onnx"), str(a.model_dir / "voices-v1.0.bin"))
    a.out.mkdir(parents=True, exist_ok=True)

    if a.audition:
        for v in [v.strip() for v in a.voice.split(",") if v.strip()]:
            st = render(kokoro, a.audition, v, a.speed, a.out / f"{v}.wav")
            print(json.dumps({"voice": v, **st}), flush=True)
        return 0

    segs = load_segments(a.script)
    only = {s.strip() for s in a.only.split(",") if s.strip()}
    if only:
        missing = only - {s["id"] for s in segs}
        if missing:
            ap.error(f"--only ids not in script: {sorted(missing)}")
        segs_todo = [s for s in segs if s["id"] in only]
    else:
        segs_todo = segs

    if a.dry_run:
        for s in segs_todo:
            fixed = apply_fixes(s.get("narration", ""))
            print(f"[{s['id']}] {fixed}\n    /{kokoro.tokenizer.phonemize(fixed, lang_for(a.voice))}/")
        return 0

    dur_path = a.out / "durations.json"
    durations = json.loads(dur_path.read_text()) if (only and dur_path.exists()) else {}
    for s in segs_todo:
        text = (s.get("narration") or "").strip()
        if not text:
            print(f"[{s['id']}] no narration, skipped", file=sys.stderr)
            continue
        st = render(kokoro, text, a.voice, a.speed, a.out / f"{s['id']}.wav")
        durations[s["id"]] = st["seconds"]
        print(json.dumps({"id": s["id"], **st}), flush=True)
    order = [s["id"] for s in segs] + sorted(set(durations) - {s["id"] for s in segs})
    durations = {k: durations[k] for k in order if k in durations}
    dur_path.write_text(json.dumps(durations, indent=2) + "\n")
    print(f"total {sum(durations.values()):.2f} s over {len(durations)} segments -> {dur_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
