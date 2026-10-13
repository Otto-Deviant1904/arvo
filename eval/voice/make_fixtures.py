"""Generate the voice-memo eval set with an open-source TTS (Piper) + ffmpeg.

12 memos = 2 voices x 6 scripts, written the way support workers talk in the car park
("half eight", "twelve k's", "arvo"). Two memos get low-level car-like noise (brown noise
from ffmpeg anoisesrc, low-passed) mixed in at a fixed SNR. Writes:

    eval/voice/audio/<voice>/<recording-timestamp>.<ext>   (alan -> .m4a AAC, jenny -> .ogg Opus)
    eval/voice/gold.json                                   scripts + gold shifts

Run (voices from https://huggingface.co/rhasspy/piper-voices, .onnx + .onnx.json side by side):

    uv run --python 3.12 --with piper-tts python -I eval/voice/make_fixtures.py \
        --voice-a /path/en_GB-alan-medium.onnx --voice-b /path/en_GB-jenny_dioco-medium.onnx
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import tempfile
import wave
from array import array
from pathlib import Path

HERE = Path(__file__).resolve().parent
WEEK_ENDING = "2026-10-11"  # Sunday; window Mon 5 Oct .. Sun 11 Oct 2026
NOISE_SNR_DB = 12.0

# rec: when the memo was recorded (goes in the filename, like a phone voice recorder does).
SCRIPTS = [
    dict(rec="2026-10-05T20:47",
         text="Jake, Monday, three till half eight. Footy training, then Maccas on the way home. Twelve k's.",
         shift=dict(alias="Jake", participant_id="jake", day="Monday", date="2026-10-05",
                    start="15:00", end="20:30", km=12,
                    note="Footy training, then Maccas on the way home.", rp_type=None)),
    dict(rec="2026-10-06T13:10",
         text="Priya, Tuesday morning, nine till one. Helped her with the shower and brekkie, "
              "then we did the washing together. No k's today.",
         shift=dict(alias="Priya", participant_id="priya", day="Tuesday", date="2026-10-06",
                    start="09:00", end="13:00", km=0,
                    note="Helped her with the shower and brekkie, then we did the washing together.",
                    rp_type=None)),
    dict(rec="2026-10-07T17:55",
         text="Tommy, Wednesday arvo, quarter past two till quarter to six. Went to Bunnings and the library, "
              "eighteen k's. He got really worked up at the checkout, so I held both his arms down by his sides "
              "until he settled.",
         shift=dict(alias="Tommy", participant_id="tom", day="Wednesday", date="2026-10-07",
                    start="14:15", end="17:45", km=18,
                    note="Went to Bunnings and the library. He got really worked up at the checkout, so I held "
                         "both his arms down by his sides until he settled.", rp_type="physical")),
    dict(rec="2026-10-08T10:40",
         text="Mrs B, Thursday, seven in the morning till half past ten. Breakfast, meds prompt, "
              "and a slow walk around the block. Nothing else to report.",
         shift=dict(alias="Mrs B", participant_id="nonna", day="Thursday", date="2026-10-08",
                    start="07:00", end="10:30", km=0,
                    note="Breakfast, meds prompt, and a slow walk around the block. Nothing else to report.",
                    rp_type=None)),
    # no day spoken: only the recording date says which day it was
    dict(rec="2026-10-09T21:15",
         text="Jake again, four till nine tonight. Movies and dinner in the city, twenty five k's. "
              "His mum wants his Xbox controller kept in my car all week so he can't play it, so I've taken it.",
         shift=dict(alias="Jake", participant_id="jake", day="Friday", date="2026-10-09",
                    start="16:00", end="21:00", km=25,
                    note="Movies and dinner in the city. His mum wants his Xbox controller kept in my car all "
                         "week so he can't play it, so I've taken it.", rp_type="environmental")),
    # recorded the next morning: "yesterday" = Saturday
    dict(rec="2026-10-11T09:05",
         text="Priya, yesterday, ten till two thirty. Shopping at Chadstone, eight k's. She wouldn't stop yelling "
              "in the car, so I put the child locks on and left her in there for ten minutes to calm down.",
         shift=dict(alias="Priya", participant_id="priya", day="Saturday", date="2026-10-10",
                    start="10:00", end="14:30", km=8,
                    note="Shopping at Chadstone. She wouldn't stop yelling in the car, so I put the child locks "
                         "on and left her in there for ten minutes to calm down.", rp_type="seclusion")),
]

# voice key -> (filename style, container args, ext, script indexes that get car noise)
VOICES = {
    "a": dict(name="alan", fname="{d}-{hm}", ext="m4a", codec=["-c:a", "aac", "-b:a", "48k"], noisy={4}),
    "b": dict(name="jenny", fname="Recording_{d}_{hm}00", ext="ogg", codec=["-c:a", "libopus", "-b:a", "32k"],
              noisy={2}),
}


def ff(*args: str) -> bytes:
    return subprocess.run(["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y", *args],
                          check=True, capture_output=True).stdout


def rms(samples) -> float:
    return math.sqrt(sum(x * x for x in samples) / max(1, len(samples)))


def speech_rms(samples, rate: int) -> float:
    """RMS over 20 ms frames that are not near-silent (so pauses do not dilute the SNR)."""
    win = rate // 50
    frames = [samples[i:i + win] for i in range(0, len(samples) - win, win)]
    levels = [rms(f) for f in frames]
    peak = max(levels or [0.0])
    voiced = [lv for lv in levels if lv > 0.1 * peak]
    return math.sqrt(sum(lv * lv for lv in voiced) / max(1, len(voiced)))


def noise_filter(dur: float, rate: int, gain: float) -> str:
    return (f"anoisesrc=d={dur:.3f}:c=brown:r={rate}:a=0.5:seed=42,"
            f"lowpass=f=350,lowpass=f=350,volume={gain:.5f}")


def synth(voice, text: str, out_wav: Path) -> None:
    with wave.open(str(out_wav), "wb") as wf:
        voice.synthesize_wav(text, wf)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--voice-a", required=True, help="Piper .onnx (en_GB), config .onnx.json next to it")
    ap.add_argument("--voice-b", required=True, help="second, different Piper .onnx")
    args = ap.parse_args()
    from piper import PiperVoice  # only needed here; not an arvo dependency

    items = []
    with tempfile.TemporaryDirectory(prefix="arvo-voice-") as tmp:
        tmp = Path(tmp)
        for key, onnx in (("a", args.voice_a), ("b", args.voice_b)):
            v = VOICES[key]
            voice = PiperVoice.load(onnx, config_path=onnx + ".json")
            outdir = HERE / "audio" / v["name"]
            outdir.mkdir(parents=True, exist_ok=True)
            for i, sc in enumerate(SCRIPTS):
                raw = tmp / f"{v['name']}-{i}.wav"
                synth(voice, sc["text"], raw)
                with wave.open(str(raw), "rb") as w:
                    rate, n = w.getframerate(), w.getnframes()
                    speech = array("h", w.readframes(n))
                dur = n / rate
                d, hm = sc["rec"][:10].replace("-", ""), sc["rec"][11:].replace(":", "")
                dst = outdir / f"{v['fname'].format(d=d, hm=hm)}.{v['ext']}"
                snr = None
                if i in v["noisy"]:
                    probe = array("h", ff("-f", "lavfi", "-i", noise_filter(dur, rate, 1.0),
                                          "-f", "s16le", "-acodec", "pcm_s16le", "-"))
                    gain = speech_rms(speech, rate) / (rms(probe) * 10 ** (NOISE_SNR_DB / 20))
                    ff("-i", str(raw), "-f", "lavfi", "-i", noise_filter(dur, rate, gain),
                       "-filter_complex", "[0:a][1:a]amix=inputs=2:duration=first:normalize=0",
                       *v["codec"], str(dst))
                    snr = NOISE_SNR_DB
                else:
                    ff("-i", str(raw), *v["codec"], str(dst))
                items.append({
                    "id": f"{v['name']}-{i + 1}",
                    "voice": Path(onnx).stem,
                    "file": str(dst.relative_to(HERE)),
                    "recorded": sc["rec"],
                    "duration_s": round(dur, 2),
                    "noise_snr_db": snr,
                    "script": sc["text"],
                    "shift": sc["shift"],
                })
                print(f"{dst.relative_to(HERE)}  {dur:5.1f}s  {'noise ' + str(snr) + ' dB' if snr else ''}")
    gold = {"week_ending": WEEK_ENDING, "tts": "piper-tts (rhasspy/piper-voices)",
            "noise": f"ffmpeg anoisesrc brown, lowpass 350 Hz x2, mixed at {NOISE_SNR_DB} dB SNR",
            "memos": items}
    (HERE / "gold.json").write_text(json.dumps(gold, indent=2) + "\n", encoding="utf-8")
    too_long = [it["id"] for it in items if it["duration_s"] >= 25]
    if too_long:
        print("WARNING: >= 25 s:", too_long)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
