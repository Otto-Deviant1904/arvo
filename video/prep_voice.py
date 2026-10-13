"""Prepare the narrator's own recordings for the Arvo video (stdlib + ffmpeg only).

  python video/prep_voice.py --in <folder> --out video/audio/ [--script video/script.json]

<folder> holds one file per segment, named <segment_id>.<any audio ext> (m4a, wav, mp3,
flac, ogg, opus, webm, ...). Each becomes <out>/<segment_id>.wav, 48 kHz mono 16-bit:
  highpass 80 Hz -> afftdn noise reduction -> gentle compressor (2.5:1 above -20 dBFS)
  -> leading/trailing silence trimmed to 0.15 s -> two-pass loudnorm to -16 LUFS (TP -1.5).
<out>/durations.json is rewritten: processed ids get their new length; ids not recorded keep
their previous (e.g. TTS scratch) value. With --script the keys follow script order and ids
that are not in the script are reported.
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
import tempfile
import wave
from array import array
from pathlib import Path

SR = 48000
PAD_S = 0.15
CLEAN = ("highpass=f=80,"
         "afftdn=nr=12:nf=-45:tn=1,"
         "acompressor=threshold=0.1:ratio=2.5:attack=15:release=200:makeup=1")
LOUDNORM = "loudnorm=I=-16:TP=-1.5:LRA=11"
AUDIO_EXT = {".m4a", ".mp4", ".aac", ".wav", ".mp3", ".flac", ".ogg", ".oga", ".opus",
             ".webm", ".caf", ".aiff", ".aif", ".wma", ".amr", ".3gp"}


def ff(*args: str, capture: bool = False) -> str:
    p = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", *args],
                       capture_output=True, text=True)
    if p.returncode:
        sys.exit(f"ffmpeg failed: {' '.join(args)}\n{p.stderr[-2000:]}")
    return p.stderr if capture else ""


def speech_bounds(raw: Path, rel_db: float = -35.0) -> tuple[float, float]:
    """(start, end) seconds of the span louder than rel_db below the loudest 10 ms frame."""
    a = array("f")
    a.frombytes(raw.read_bytes())
    fr = SR // 100
    n = len(a) // fr
    rms = [math.sqrt(sum(x * x for x in a[i * fr:(i + 1) * fr]) / fr) for i in range(n)]
    if not rms or max(rms) == 0:
        return 0.0, len(a) / SR
    thr = max(rms) * 10 ** (rel_db / 20)
    voiced = [i for i, r in enumerate(rms) if r > thr]
    return voiced[0] / 100, (voiced[-1] + 1) / 100


def prep(src: Path, dst: Path) -> float:
    with tempfile.TemporaryDirectory() as td:
        raw, trimmed = Path(td) / "clean.f32", Path(td) / "trimmed.wav"
        ff("-y", "-i", str(src), "-vn", "-af", CLEAN, "-ar", str(SR), "-ac", "1",
           "-f", "f32le", str(raw))
        start, end = speech_bounds(raw)
        ff("-y", "-f", "f32le", "-ar", str(SR), "-ac", "1", "-i", str(raw), "-af",
           f"atrim=start={start}:end={end},asetpts=N/SR/TB,"
           f"adelay={int(PAD_S * 1000)}:all=1,apad=pad_dur={PAD_S}",
           "-c:a", "pcm_f32le", str(trimmed))
        err = ff("-i", str(trimmed), "-af", LOUDNORM + ":print_format=json", "-f", "null", "-",
                 capture=True)
        m = json.loads(err[err.rindex("{"): err.rindex("}") + 1])
        ff("-y", "-loglevel", "error", "-i", str(trimmed), "-af",
           f"{LOUDNORM}:measured_I={m['input_i']}:measured_TP={m['input_tp']}"
           f":measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}"
           f":offset={m['target_offset']}:linear=true",
           "-ar", str(SR), "-ac", "1", "-c:a", "pcm_s16le", str(dst))
    with wave.open(str(dst)) as w:
        return round(w.getnframes() / w.getframerate(), 3)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--in", dest="src", type=Path, required=True, help="folder of <segment_id>.<ext>")
    ap.add_argument("--out", type=Path, default=Path("video/audio"))
    ap.add_argument("--script", type=Path, help="script.json, only for key order / id check")
    a = ap.parse_args()

    files = sorted(p for p in a.src.iterdir() if p.is_file() and p.suffix.lower() in AUDIO_EXT)
    if not files:
        sys.exit(f"no audio files in {a.src}")
    stems = [p.stem for p in files]
    dupes = {s for s in stems if stems.count(s) > 1}
    if dupes:
        sys.exit(f"more than one file for: {sorted(dupes)}")

    a.out.mkdir(parents=True, exist_ok=True)
    dur_path = a.out / "durations.json"
    durations = json.loads(dur_path.read_text()) if dur_path.exists() else {}
    for p in files:
        if (a.out / f"{p.stem}.wav").resolve() == p.resolve():
            sys.exit(f"{p} would overwrite itself; use a separate --in folder")
        durations[p.stem] = prep(p, a.out / f"{p.stem}.wav")
        print(f"{p.name} -> {a.out / (p.stem + '.wav')}  {durations[p.stem]:.2f} s", flush=True)

    if a.script:
        segs = json.loads(a.script.read_text())
        if isinstance(segs, dict):
            segs = segs.get("segments", segs.get("shots", []))
        order = [s["id"] for s in segs if isinstance(s, dict) and s.get("id")]
        extra = [k for k in durations if k not in order]
        if extra:
            print(f"warning: ids not in {a.script}: {extra}", file=sys.stderr)
        durations = {k: durations[k] for k in order + extra if k in durations}
    dur_path.write_text(json.dumps(durations, indent=2) + "\n")
    kept = [k for k in durations if k not in stems]
    print(f"total {sum(durations.values()):.2f} s -> {dur_path}"
          + (f"  (kept earlier values for: {', '.join(kept)})" if kept else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
