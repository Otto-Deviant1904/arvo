"""Held-out voice-memo set: 10 memos nobody tunes on (the dev set in eval/voice/gold.json was used while building).

Scripts + gold live in eval/voice/heldout/scripts.json (same shape as eval/voice/gold.json, plus `tags`).
This script checks the gold, synthesises each script with a Piper voice that the dev set does not use,
mixes car noise into the memos whose `noise_snr_db` is set (same recipe as make_fixtures.py), encodes
WhatsApp-style Ogg Opus voice notes into eval/voice/heldout/audio/, and writes duration_s back.

    uv run --python 3.12 --with piper-tts python -I eval/voice/heldout/make_heldout.py \
        --voice /path/en_GB-northern_english_male-medium.onnx      # .onnx.json next to it
    python -I eval/voice/heldout/make_heldout.py --check            # gold checks only, no Piper

No Gemma/Ollama call is made here.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
import wave
from array import array
from datetime import date, datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
VOICE_DIR = HERE.parent
REPO = VOICE_DIR.parent.parent
SCRIPTS = HERE / "scripts.json"
sys.path.insert(0, str(VOICE_DIR))
sys.path.insert(0, str(REPO))

from make_fixtures import ff, noise_filter, rms, speech_rms, synth  # noqa: E402

DEV_VOICES = {"en_GB-alan-medium", "en_GB-jenny_dioco-medium"}
CODEC = ["-ac", "1", "-ar", "16000", "-c:a", "libopus", "-b:a", "32k"]
MAX_S = 25.0
RP_TYPES = {"seclusion", "chemical", "mechanical", "physical", "environmental"}
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def _words(s: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", s.casefold().replace("’", "'"))


def check(gold: dict) -> list[str]:
    """Problems with the gold (empty list = fine). Pure stdlib + arvo.voice.memo_date; no model calls."""
    from arvo.voice import memo_date

    hols = json.loads((REPO / "data" / "vic_public_holidays.json").read_text(encoding="utf-8"))
    ph = {h["date"]: h["name"] for y, hs in hols.items() if y != "meta" for h in hs if h.get("date")}
    end = date.fromisoformat(gold["week_ending"])
    window = {(end - timedelta(days=i)).isoformat() for i in range(7)}
    bad: list[str] = []
    seen_ids = set()
    for m in gold["memos"]:
        s, i, tags = m["shift"], m["id"], m.get("tags", [])
        if i in seen_ids:
            bad.append(f"{i}: duplicate id")
        seen_ids.add(i)
        if m["voice"] in DEV_VOICES:
            bad.append(f"{i}: voice {m['voice']} is a dev-set voice")
        if s["date"] not in window:
            bad.append(f"{i}: date {s['date']} outside week ending {gold['week_ending']}")
        d = date.fromisoformat(s["date"])
        if DAYS[d.weekday()] != s["day"]:
            bad.append(f"{i}: day {s['day']} != weekday of {s['date']}")
        rec = datetime.fromisoformat(m["recorded"])
        said_before = re.search(r"\b(yesterday|last night)\b", m["script"], re.I)
        want = rec.date() - timedelta(days=1) if said_before else rec.date()
        if d != want:
            bad.append(f"{i}: shift date {d} but recorded {rec.date()} (yesterday/last night: {bool(said_before)})")
        if memo_date(m["file"], use_mtime=False) != rec.date():
            bad.append(f"{i}: filename {m['file']} does not carry the recording date")
        if not (re.fullmatch(r"\d\d:\d\d", s["start"]) and re.fullmatch(r"\d\d:\d\d", s["end"])
                and s["start"] < s["end"]):
            bad.append(f"{i}: bad times {s['start']}-{s['end']}")
        if datetime.fromisoformat(f"{s['date']}T{s['end']}") > rec:
            bad.append(f"{i}: recorded {m['recorded']} before the shift ended")
        if ("crosses_8pm" in tags) != (s["start"] < "20:00" < s["end"]):
            bad.append(f"{i}: crosses_8pm tag disagrees with {s['start']}-{s['end']}")
        tag_ph = [t.split(":", 1)[1] for t in tags if t.startswith("public_holiday:")]
        if tag_ph != ([ph[s["date"]]] if s["date"] in ph else []):
            bad.append(f"{i}: public_holiday tag {tag_ph} vs calendar {ph.get(s['date'])}")
        if s["rp_type"] is not None and s["rp_type"] not in RP_TYPES:
            bad.append(f"{i}: rp_type {s['rp_type']}")
        if ("rp" in tags) != (s["rp_type"] is not None):
            bad.append(f"{i}: rp tag disagrees with rp_type")
        script_w = set(_words(m["script"]))
        missing = [w for w in _words(s["note"]) if w not in script_w]
        if missing:
            bad.append(f"{i}: note words not in script: {missing}")
        if s["alias"].casefold() not in m["script"].casefold():
            bad.append(f"{i}: alias {s['alias']} not spoken")
        if m.get("duration_s") is not None and m["duration_s"] >= MAX_S:
            bad.append(f"{i}: {m['duration_s']} s >= {MAX_S} s")
    tags = [t for m in gold["memos"] for t in m.get("tags", [])]
    need = {"public_holiday dates": (len({m["shift"]["date"] for m in gold["memos"] if any(
                t.startswith("public_holiday:") for t in m.get("tags", []))}), 2),
            "crosses_8pm": (tags.count("crosses_8pm"), 2), "last_night": (tags.count("last_night"), 1),
            "rp": (tags.count("rp"), 2), "trap_words": (sum(t.startswith("trap_words:") for t in tags), 2),
            "noisy": (sum(bool(m["noise_snr_db"]) for m in gold["memos"]), 3)}
    bad += [f"coverage: {k} {have} < {n}" for k, (have, n) in need.items() if have < n]
    return bad


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--voice", help="Piper .onnx not used by the dev set; config .onnx.json next to it")
    ap.add_argument("--check", action="store_true", help="only check scripts.json, no audio")
    args = ap.parse_args()
    gold = json.loads(SCRIPTS.read_text(encoding="utf-8"))
    problems = check(gold)
    if problems:
        print("\n".join(problems))
        return 1
    if args.check:
        print(f"ok: {len(gold['memos'])} memos")
        return 0
    if not args.voice:
        ap.error("--voice is required unless --check")
    stem = Path(args.voice).name.removesuffix(".onnx")
    if stem in DEV_VOICES:
        ap.error(f"{stem} is a dev-set voice")
    from piper import PiperVoice  # only needed here; not an arvo dependency

    voice = PiperVoice.load(args.voice, config_path=args.voice + ".json")
    with tempfile.TemporaryDirectory(prefix="arvo-heldout-") as tmp:
        for m in gold["memos"]:
            raw = Path(tmp) / f"{m['id']}.wav"
            synth(voice, m["script"], raw)
            with wave.open(str(raw), "rb") as w:
                rate, n = w.getframerate(), w.getnframes()
                speech = array("h", w.readframes(n))
            dur = n / rate
            dst = VOICE_DIR / m["file"]
            dst.parent.mkdir(parents=True, exist_ok=True)
            snr = m["noise_snr_db"]
            if snr:
                probe = array("h", ff("-f", "lavfi", "-i", noise_filter(dur, rate, 1.0),
                                      "-f", "s16le", "-acodec", "pcm_s16le", "-"))
                gain = speech_rms(speech, rate) / (rms(probe) * 10 ** (snr / 20))
                ff("-i", str(raw), "-f", "lavfi", "-i", noise_filter(dur, rate, gain),
                   "-filter_complex", "[0:a][1:a]amix=inputs=2:duration=first:normalize=0", *CODEC, str(dst))
            else:
                ff("-i", str(raw), *CODEC, str(dst))
            m["voice"], m["duration_s"] = stem, round(dur, 2)
            print(f"{m['file']}  {dur:5.1f}s  {'noise ' + str(snr) + ' dB' if snr else ''}")
    SCRIPTS.write_text(json.dumps(gold, indent=2) + "\n", encoding="utf-8")
    problems = check(gold)
    print("\n".join(problems) or f"ok: {len(gold['memos'])} memos")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
