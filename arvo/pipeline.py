"""extract -> price -> restrictive-practice screen, in one call."""

from __future__ import annotations

import json
import time
from datetime import date
from pathlib import Path

from . import llm
from .extract import extract_shifts
from .models import RunResult
from .rp import screen_notes


def load_roster(roster_path_or_dict) -> dict:
    """Path to roster JSON, or an already-loaded dict -> dict with 'participants'."""
    if isinstance(roster_path_or_dict, (str, Path)):
        return json.loads(Path(roster_path_or_dict).read_text(encoding="utf-8"))
    if isinstance(roster_path_or_dict, list):
        return {"participants": roster_path_or_dict}
    return roster_path_or_dict


def _price(shifts, roster) -> tuple[list, list[str]]:
    try:
        from arvo.pricing import price_shifts
    except ImportError as e:
        if e.name not in ("arvo.pricing", None):
            raise
        return [], ["pricing module not available yet: no invoice lines"]
    lines, warnings = price_shifts(shifts, roster)
    return list(lines), list(warnings)


def roster_vocab(roster) -> list[str]:
    """Participant names and aliases (2+ chars), to help the model spell them when listening."""
    from .extract import as_participants
    words = [w for p in as_participants(roster) for w in [*p.aliases, p.name]]
    return list(dict.fromkeys(w.strip() for w in words if len(w.strip()) > 1))


def transcribe_memos(audio_paths, roster_path_or_dict, model: str = llm.DEFAULT_MODEL,
                     use_mtime: bool = True) -> tuple[str, list[dict]]:
    """Voice memos -> (diary text, one line per memo, per-memo metas with 'transcript')."""
    from .voice import memos_to_diary
    return memos_to_diary(list(audio_paths), model, vocab=roster_vocab(load_roster(roster_path_or_dict)),
                          use_mtime=use_mtime)


def run(diary_text: str, roster_path_or_dict, week_ending: str, model: str = llm.DEFAULT_MODEL,
        image_path: str | None = None, audio_paths: list[str] | None = None,
        audio_use_mtime: bool = True) -> RunResult:
    """audio_paths: voice memos; each is transcribed by the model into one diary line (appended to
    diary_text), then the normal text pipeline runs. What was heard is listed in warnings to check."""
    date.fromisoformat(week_ending)  # fail fast on a bad date
    t0 = time.perf_counter()
    roster = load_roster(roster_path_or_dict)

    heard: list[str] = []
    if audio_paths:
        memo_text, vmetas = transcribe_memos(audio_paths, roster, model, use_mtime=audio_use_mtime)
        diary_text = "\n".join(t for t in ((diary_text or "").strip(), memo_text) if t)
        for m in vmetas:
            heard.extend(m.get("warnings", []))
            if m.get("transcript"):
                heard.append(f"voice memo {Path(m['path']).name} ({m['duration_s']:g} s"
                             f"{', recorded ' + m['recorded'] if m.get('recorded') else ''}): "
                             f"heard \"{m['transcript']}\"; check names, times and km")
    ta = time.perf_counter()

    shifts, warnings, emeta = extract_shifts(diary_text, roster, week_ending, model, image_path=image_path)
    t1 = time.perf_counter()
    lines, pwarn = _price(shifts, roster)
    t2 = time.perf_counter()
    flags, rmeta = screen_notes(shifts, roster, model)
    t3 = time.perf_counter()

    timings = {
        "extract_s": round(t1 - ta, 3),
        "pricing_s": round(t2 - t1, 3),
        "rp_s": round(t3 - t2, 3),
        "total_s": round(t3 - t0, 3),
        "rp_calls": rmeta.get("calls", 0),
        "extract_prompt_tokens": emeta.get("prompt_tokens", 0),
        "extract_eval_tokens": emeta.get("eval_tokens", 0),
        "load_s": round((emeta.get("load_s") or 0) + (rmeta.get("load_s") or 0), 3),
    }
    if audio_paths:
        timings["transcribe_s"] = round(ta - t0, 3)
        timings["memos"] = len(audio_paths)
    return RunResult(shifts=shifts, lines=lines, flags=flags,
                     warnings=[*heard, *warnings, *pwarn, *rmeta.get("warnings", [])],
                     model=model, timings=timings)
