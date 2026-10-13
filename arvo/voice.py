"""Voice memos -> diary text, with Gemma 4 doing the listening.

`transcribe()` turns one memo (any format ffmpeg reads) into 16 kHz mono PCM, cuts it into
<= 28 s pieces at the quietest moment near each cut, and sends each piece as a WAV in
`messages[].images` (Ollama's audio slot for gemma4). `memos_to_diary()` writes one diary
line per memo, prefixed with the recording date taken from the filename (or file mtime),
so the normal text pipeline can read it like a typed diary.

stdlib only; ffmpeg is used as a subprocess when the input is not already 16 kHz mono WAV.
"""

from __future__ import annotations

import io
import os
import re
import shutil
import subprocess
import sys
import time
import wave
from array import array
from datetime import date, datetime
from pathlib import Path

from . import llm

RATE = 16000
MAX_CHUNK_S = 28.0     # gemma4 audio clips should be <= 30 s
SEARCH_S = 4.0         # look this far back from a hard cut for a quiet spot
MIN_AUDIO_S = 0.3
AUDIO_EXTS = {".wav", ".mp3", ".m4a", ".aac", ".ogg", ".oga", ".opus", ".flac", ".webm", ".amr", ".3gp", ".caf"}
WEEKDAY_ABBR = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


class VoiceError(RuntimeError):
    """Audio could not be decoded (no ffmpeg, unreadable file)."""


# --------------------------------------------------------------------------- audio decode

def ffmpeg_cmd(src: str | Path, ffmpeg: str = "ffmpeg") -> list[str]:
    """argv that decodes any audio file to raw 16 kHz mono signed 16-bit little-endian PCM on stdout."""
    return [ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-i", str(src),
            "-vn", "-ac", "1", "-ar", str(RATE), "-acodec", "pcm_s16le", "-f", "s16le", "-"]


def _pcm_array(raw: bytes) -> array:
    a = array("h")
    a.frombytes(raw[: len(raw) - len(raw) % 2])
    if sys.byteorder == "big":
        a.byteswap()
    return a


def _read_wav_if_ready(path: Path) -> array | None:
    """Samples if `path` is already a 16 kHz mono 16-bit PCM WAV, else None."""
    try:
        with wave.open(str(path), "rb") as w:
            if (w.getnchannels(), w.getframerate(), w.getsampwidth(), w.getcomptype()) != (1, RATE, 2, "NONE"):
                return None
            return _pcm_array(w.readframes(w.getnframes()))
    except (wave.Error, EOFError, OSError):
        return None


def load_pcm(path: str | Path, *, run=None) -> tuple[array, bool]:
    """Audio file -> (16 kHz mono int16 samples, converted_with_ffmpeg)."""
    path = Path(path)
    if not path.is_file():
        raise VoiceError(f"no such audio file: {path}")
    ready = _read_wav_if_ready(path)
    if ready is not None:
        return ready, False
    exe = shutil.which("ffmpeg")
    if exe is None and run is None:
        raise VoiceError(f"{path.name} is not 16 kHz mono WAV and ffmpeg is not installed to convert it")
    run = run or subprocess.run
    proc = run(ffmpeg_cmd(path, exe or "ffmpeg"), capture_output=True, check=False, timeout=120)
    if proc.returncode != 0:
        err = (proc.stderr or b"").decode("utf-8", "replace").strip()[-300:]
        raise VoiceError(f"ffmpeg could not read {path.name}: {err or 'exit ' + str(proc.returncode)}")
    return _pcm_array(proc.stdout), True


def wav_bytes(samples, rate: int = RATE) -> bytes:
    """int16 mono samples -> a complete in-memory WAV file."""
    a = array("h", samples)
    if sys.byteorder == "big":
        a.byteswap()
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(a.tobytes())
    return buf.getvalue()


# --------------------------------------------------------------------------- chunking

def plan_chunks(samples, rate: int = RATE, max_s: float = MAX_CHUNK_S, search_s: float = SEARCH_S,
                win_s: float = 0.05) -> list[tuple[int, int]]:
    """[(start, end)] sample ranges, each <= max_s long, covering all samples with no gaps.
    Each cut goes in the quietest win_s window within the last search_s seconds before the hard
    limit, so a word is less likely to be split in half."""
    n = len(samples)
    max_n = int(max_s * rate)
    if n <= max_n:
        return [(0, n)]
    win = max(1, int(win_s * rate))
    out: list[tuple[int, int]] = []
    a = 0
    while n - a > max_n:
        hi = a + max_n
        lo = max(a + 1, hi - int(search_s * rate))
        best, best_e = hi, None
        for s in range(lo, hi - win + 1, win):
            e = sum(abs(x) for x in samples[s:s + win])
            if best_e is None or e < best_e:
                best, best_e = s + win // 2, e
        out.append((a, best))
        a = best
    out.append((a, n))
    return out


# --------------------------------------------------------------------------- transcription

TRANSCRIPT_SCHEMA = {
    "type": "object",
    "properties": {"transcript": {"type": "string"}},
    "required": ["transcript"],
}

SYSTEM_PROMPT = "You transcribe short voice memos word for word. You never summarise or add words."

TRANSCRIBE_PROMPT = """Transcribe the attached voice memo verbatim. The speaker is an Australian disability support worker recording a shift note in the car after a shift, in Australian English.

RULES
1. Write every word that is spoken, in order. Do not summarise, shorten, correct, explain or add anything.
2. Write numbers as digits: "three" -> 3, "twelve" -> 12, "twenty five" -> 25. Clock times as digits too: "half eight" -> half 8, "quarter to six" -> quarter to 6, "two thirty" -> 2:30, "nine till one" -> 9 till 1.
3. Keep Australian words as spoken: arvo (afternoon), k's (kilometres).
4. Use normal sentence punctuation. If a word is unclear, write your best guess.{vocab}
Reply with JSON: {{"transcript": "..."}}"""

# "12 k's" / "12 ks" / "12 kays" / "12 kms" / "12 kilometres" -> "12 km": the km check in extract needs a unit
_KM_RE = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)\s*(?:k['’]?s\b|kays?\b|kms?\b|kilomet(?:er|re)s?\b|k\b(?!['’]))", re.I)


def normalise_km(text: str) -> str:
    return _KM_RE.sub(lambda m: f"{m.group(1)} km", text)


def build_messages(vocab: list[str] | tuple[str, ...] = ()) -> list[dict]:
    words = ", ".join(dict.fromkeys(v.strip() for v in vocab if v and v.strip()))
    hint = f"\n5. Names you may hear (spell them like this): {words}." if words else ""
    return [{"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": TRANSCRIBE_PROMPT.format(vocab=hint)}]


def transcribe(audio_path: str | Path, model: str = llm.DEFAULT_MODEL, *,
               vocab: list[str] | tuple[str, ...] = ()) -> tuple[str, dict]:
    """One memo -> (transcript, meta). meta: path, duration_s, chunks, converted, total_s, tokens, warnings."""
    t0 = time.perf_counter()
    samples, converted = load_pcm(audio_path)
    duration = len(samples) / RATE
    meta = {"path": str(audio_path), "duration_s": round(duration, 2), "converted": converted, "chunks": 0,
            "model": model, "llm_s": 0.0, "load_s": 0.0, "prompt_tokens": 0, "eval_tokens": 0, "warnings": []}
    if duration < MIN_AUDIO_S:
        meta["warnings"].append(f"{Path(audio_path).name}: audio is empty or shorter than {MIN_AUDIO_S} s")
        meta["total_s"] = round(time.perf_counter() - t0, 3)
        return "", meta
    messages = build_messages(vocab)
    parts = []
    for a, b in plan_chunks(samples):
        obj, m = llm.chat(messages, TRANSCRIPT_SCHEMA, model=model, images=[wav_bytes(samples[a:b])])
        meta["chunks"] += 1
        for k, mk in (("llm_s", "total_s"), ("load_s", "load_s"), ("prompt_tokens", "prompt_tokens"),
                      ("eval_tokens", "eval_tokens")):
            meta[k] += m.get(mk, 0) or 0
        parts.append(re.sub(r"\s+", " ", str(obj.get("transcript") or "")).strip())
    text = normalise_km(" ".join(p for p in parts if p))
    if not text:
        meta["warnings"].append(f"{Path(audio_path).name}: the model heard no words")
    meta["llm_s"] = round(meta["llm_s"], 3)
    meta["load_s"] = round(meta["load_s"], 3)
    meta["total_s"] = round(time.perf_counter() - t0, 3)
    return text, meta


# --------------------------------------------------------------------------- memos -> diary

_FNAME_DATE_RE = re.compile(r"(?<!\d)(20\d\d)[-_.]?(0[1-9]|1[0-2])[-_.]?(0[1-9]|[12]\d|3[01])(?!\d)")


def memo_date(path: str | Path, use_mtime: bool = True) -> date | None:
    """Recording date: the first YYYY-MM-DD / YYYYMMDD in the filename, else the file mtime (if allowed)."""
    p = Path(path)
    for m in _FNAME_DATE_RE.finditer(p.name):
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            continue
    if use_mtime:
        try:
            return datetime.fromtimestamp(os.path.getmtime(p)).date()
        except OSError:
            return None
    return None


def memo_line(text: str, recorded: date | None) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    if recorded is None:
        return text
    return f"[memo recorded {WEEKDAY_ABBR[recorded.weekday()]} {recorded.isoformat()}] {text}"


def memos_to_diary(paths, model: str = llm.DEFAULT_MODEL, *, vocab: list[str] | tuple[str, ...] = (),
                   use_mtime: bool = True) -> tuple[str, list[dict]]:
    """Memos -> (diary text with one line per memo, per-memo metas incl. 'transcript' and 'recorded').
    Order is kept as given. Memos that transcribe to nothing are left out of the diary."""
    lines, metas = [], []
    for p in paths:
        text, meta = transcribe(p, model, vocab=vocab)
        rec = memo_date(p, use_mtime=use_mtime)
        meta["transcript"] = text
        meta["recorded"] = rec.isoformat() if rec else ""
        metas.append(meta)
        if text:
            lines.append(memo_line(text, rec))
    return "\n".join(lines), metas
