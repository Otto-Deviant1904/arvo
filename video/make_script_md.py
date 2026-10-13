"""Write video/SCRIPT.md (the recording sheet) from video/script.json and the guide-track durations."""
import json
from pathlib import Path

V = Path(__file__).resolve().parent
script = json.loads((V / "script.json").read_text())
dur = json.loads((V / "audio" / "durations.json").read_text())
lines = [
    "# Arvo video: recording sheet",
    "",
    "Record each segment as its own file named exactly `<id>.m4a` (or .wav/.mp3/.ogg), e.g. `s02_hook.m4a`, into one folder.",
    "Phone voice memos are fine. Quiet room, phone 20-30 cm from your mouth, same spot for every take.",
    "Speak at your natural pace. Pauses are fine; silence at the start/end is trimmed automatically.",
    "Scenes are re-timed to YOUR recordings, so you don't need to hit the guide length exactly.",
    "",
    "Then run:",
    "```bash",
    "python3 video/prep_voice.py --in ~/arvo-voice --out video/audio/",
    "bash video/build_video.sh",
    "```",
    "",
    "| # | file | say this | guide length |",
    "|---|---|---|---|",
]
for i, s in enumerate(script, 1):
    lines.append(f"| {i} | `{s['id']}` | {s['narration']} | {dur.get(s['id'], 0):.1f} s |")
lines += ["", f"Total guide narration: {sum(dur.get(s['id'], 0) for s in script):.0f} s.", ""]
(V / "SCRIPT.md").write_text("\n".join(lines))
print("wrote", V / "SCRIPT.md")
