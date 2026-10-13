"""Diary (text or photo) -> list[Shift].

The model reads the whole week in one call; Python then decides: dates must be
in the week window (and agree with the weekday the worker wrote), times must be
HH:MM, participants must be on the roster, notes must be verbatim.
"""

from __future__ import annotations

import re
from datetime import date, timedelta

from . import llm
from .models import Participant, Shift

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
_WEEKDAY_TOKENS = [
    {"mon", "monday"},
    {"tue", "tues", "tuesday"},
    {"wed", "weds", "wednesday"},
    {"thu", "thur", "thurs", "thursday"},
    {"fri", "friday"},
    {"sat", "saturday"},
    {"sun", "sunday"},
]
UNKNOWN = "unknown"


# --------------------------------------------------------------------------- text helpers

_QUOTE_MAP = str.maketrans({
    "‘": "'", "’": "'", "‚": "'", "′": "'", "`": "'",
    "“": '"', "”": '"', "„": '"', "″": '"',
    "–": "-", "—": "-", "−": "-", " ": " ",
})


def norm_text(s: str) -> str:
    """Casefold, straighten curly quotes/dashes, collapse whitespace."""
    return re.sub(r"\s+", " ", (s or "").translate(_QUOTE_MAP)).strip().casefold()


def find_verbatim(quote: str, text: str) -> str | None:
    """Return the span of `text` that equals `quote` up to whitespace/case/curly quotes, else None."""
    q = norm_text(quote).strip(" \"'.,;:…")
    if not q:
        return None
    parts = []
    for ch in q:
        if ch == " ":
            parts.append(r"\s+")
        elif ch == "'":
            parts.append("['‘’‚′`]")
        elif ch == '"':
            parts.append('["“”„″]')
        elif ch == "-":
            parts.append("[-–—−]")
        else:
            parts.append(re.escape(ch))
    m = re.search("".join(parts), text or "", flags=re.IGNORECASE)
    return text[m.start():m.end()] if m else None


# --------------------------------------------------------------------------- roster helpers

def as_participants(roster) -> list[Participant]:
    """Roster JSON dict ({"participants": [...]}) / list of dicts / list[Participant] -> list[Participant]."""
    items = roster.get("participants", []) if isinstance(roster, dict) else (roster or [])
    fields = Participant.__dataclass_fields__
    out = []
    for p in items:
        out.append(p if isinstance(p, Participant)
                   else Participant(**{k: v for k, v in p.items() if k in fields}))
    return out


def _alias_key(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (s or "").casefold())


def match_alias(name: str, participants: list[Participant]) -> str | None:
    """Code-side alias match. Exact (punctuation-insensitive) first, then whole-word for aliases >= 3 chars.
    Returns a participant id only if the match is unambiguous."""
    key = _alias_key(name)
    if not key:
        return None
    exact = {p.id for p in participants
             if key in {_alias_key(a) for a in [p.id, p.name, *p.aliases]}
             or key == _alias_key(p.name.split()[0] if p.name else "")}
    if len(exact) == 1:
        return exact.pop()
    if exact:
        return None
    words = set(re.findall(r"[a-z0-9]+", (name or "").casefold()))
    loose = {p.id for p in participants
             for a in [p.id, *p.aliases, *(p.name.split()[:1])]
             if len(_alias_key(a)) >= 3 and _alias_key(a) in words}
    return loose.pop() if len(loose) == 1 else None


# --------------------------------------------------------------------------- week window

def week_window(week_ending: str) -> list[date]:
    """The 7 dates ending on week_ending (inclusive)."""
    end = date.fromisoformat(week_ending)
    return [end - timedelta(days=6 - i) for i in range(7)]


def _day_labels(d: date) -> list[str]:
    """Reading aids only (so the model can map 'Cup day', 'Boxing Day'); pricing uses calendar_au."""
    labels = []
    fixed = {(1, 1): "New Year's Day", (1, 26): "Australia Day", (4, 25): "Anzac Day",
             (12, 24): "Christmas Eve", (12, 25): "Christmas Day", (12, 26): "Boxing Day",
             (12, 31): "New Year's Eve"}
    if (d.month, d.day) in fixed:
        labels.append(fixed[(d.month, d.day)])
    if d.month == 11 and d.weekday() == 1 and d.day <= 7:
        labels.append("Melbourne Cup day")
    try:  # optional, built by another module
        from arvo.calendar_au import is_public_holiday
        if is_public_holiday(d.isoformat()) and not labels:
            labels.append("public holiday")
    except Exception:
        pass
    return labels


def _ordinal(n: int) -> str:
    suf = "th" if 11 <= n % 100 <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suf}"


def window_lines(window: list[date]) -> str:
    out = []
    for d in window:
        extra = _day_labels(d)
        tail = f" ({', '.join(extra)})" if extra else ""
        out.append(f"- {WEEKDAYS[d.weekday()]} the {_ordinal(d.day)} ({d.strftime('%d %b')}) = {d.isoformat()}{tail}")
    return "\n".join(out)


def dates_from_day_written(day_written: str, window: list[date]) -> list[date]:
    """Window dates implied by what the worker wrote ('Tues', 'Wed 4th', '3/11', 'Cup day').
    Returns [] if nothing parseable; >1 entries means the words disagree with each other."""
    s = (day_written or "").casefold()
    found: set[date] = set()
    toks = re.findall(r"[a-z]+", s)
    wds = {i for i, names in enumerate(_WEEKDAY_TOKENS) for t in toks if t in names}
    if len(wds) == 1:
        found |= {d for d in window if d.weekday() in wds}
    elif len(wds) > 1:
        return list(window)  # e.g. "Mon/Tue": ambiguous, signal disagreement
    for m in re.finditer(r"\b(\d{1,2})/(\d{1,2})\b", s):
        dd, mm = int(m.group(1)), int(m.group(2))
        found |= {d for d in window if d.day == dd and d.month == mm}
    for m in re.finditer(r"\b(\d{1,2})(?:st|nd|rd|th)\b", s):
        found |= {d for d in window if d.day == int(m.group(1))}
    if "cup" in toks:
        found |= {d for d in window if "Melbourne Cup day" in _day_labels(d)}
    return sorted(found)


# --------------------------------------------------------------------------- prompt + schema

def shift_schema(participant_ids: list[str]) -> dict:
    return {
        "type": "object",
        "properties": {
            "shifts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "day_written": {"type": "string"},
                        "source_quote": {"type": "string"},
                        "name_written": {"type": "string"},
                        "participant_id": {"type": "string", "enum": [*participant_ids, UNKNOWN]},
                        "date": {"type": "string"},
                        "start": {"type": "string"},
                        "end": {"type": "string"},
                        "km": {"type": "number"},
                        "note": {"type": "string"},
                    },
                    "required": ["day_written", "source_quote", "name_written", "participant_id",
                                 "date", "start", "end", "km", "note"],
                },
            }
        },
        "required": ["shifts"],
    }


SYSTEM_PROMPT = (
    "You read an Australian disability support worker's weekly shift diary and list every shift "
    "as JSON. Copy the worker's words exactly. Never invent shifts, times or km."
)

RULES = """RULES
1. One item per shift: one participant and one block of time. A day heading (e.g. "Tues", "Wed 4th", "Cup day") applies to every line under it until the next heading.
2. day_written: the day words exactly as the diary has them. date: the matching ISO date from WEEK.
3. start and end: 24-hour HH:MM. Australian usage: "arvo" = afternoon. With no am/pm, pick the reading that gives a normal day or evening shift: "3 till 8:30" = 15:00 to 20:30, "9-1" = 09:00 to 13:00, "half 3" = 15:30, "quarter to 5" = 16:45, "7ish" in the evening = 19:00, "noon" = 12:00, "midnight" = 00:00.
4. km: the kilometres written for that shift. 0 if no km is written. Never estimate.
5. note: everything the worker wrote about that shift apart from the name and times, copied exactly (same spelling, same punctuation, every sentence). "" if nothing.
6. source_quote: the exact diary text with the name and the times, e.g. "Jake 3 till 8:30ish". Keep words like ish/about.
7. name_written: the participant name as written. participant_id: from PARTICIPANTS, or "unknown".
8. Skip anything that is not a shift worked (days off, cancellations, reminders)."""


def roster_lines(participants: list[Participant]) -> str:
    return "\n".join(f"- {', '.join(dict.fromkeys([*p.aliases, p.name]))} -> {p.id}" for p in participants)


def build_messages(diary_text: str, participants: list[Participant], window: list[date],
                   from_image: bool = False) -> list[dict]:
    head = (f"WEEK (the only valid dates, week ending {WEEKDAYS[window[-1].weekday()]} "
            f"{window[-1].isoformat()}):\n{window_lines(window)}\n\n"
            f"PARTICIPANTS (names the worker uses -> participant_id):\n{roster_lines(participants)}\n\n"
            f"{RULES}\n\n")
    if from_image:
        body = ("DIARY: the attached photo is a handwritten diary page. Read the handwriting line by line, "
                "then list the shifts. Copy note and source_quote as written on the page.")
    else:
        body = f'DIARY:\n"""\n{diary_text.strip()}\n"""'
    return [{"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": head + body}]


# --------------------------------------------------------------------------- validation

_TIME_RE = re.compile(r"^\s*(\d{1,2})[:.h](\d{2})\s*$")
_APPROX_RE = re.compile(r"\d[\s-]?ish\b|\bish\b|\babout\b|\bapprox|\baround\b|\broughly\b|\babt\b|~", re.I)


def norm_time(t: str) -> str | None:
    m = _TIME_RE.match(str(t or ""))
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2))
    if h == 24 and mi == 0:
        h = 0
    if h > 23 or mi > 59:
        return None
    return f"{h:02d}:{mi:02d}"


def _minutes(t: str) -> int:
    return int(t[:2]) * 60 + int(t[3:])


def _num_str(x: float) -> str:
    return str(int(x)) if float(x).is_integer() else f"{x:g}"


def _km_stated(km: float, text: str) -> bool:
    return re.search(rf"(?<![\d.]){re.escape(_num_str(km))}(?:\.0+)?\s*(?:km|kms|k\b|kilomet)",
                     text or "", re.I) is not None


def validate_shifts(items: list, diary_text: str, participants: list[Participant],
                    window: list[date], from_image: bool = False) -> tuple[list[Shift], list[str]]:
    """Code checks on the model's raw shift dicts. Returns (shifts, run_warnings)."""
    ids = {p.id for p in participants}
    in_window = {d.isoformat() for d in window}
    shifts: list[Shift] = []
    run_warn: list[str] = []
    seen: set[tuple] = set()
    text = diary_text or ""
    norm_diary = norm_text(text)

    for i, it in enumerate(items or []):
        if not isinstance(it, dict):
            run_warn.append(f"dropped model item #{i + 1}: not an object")
            continue
        quote = str(it.get("source_quote") or "").strip()
        label = f"'{quote}'" if quote else f"shift #{i + 1}"
        w: list[str] = []

        # participant: model id, cross-checked against a code alias match on the written name
        pid = str(it.get("participant_id") or "").strip()
        name = str(it.get("name_written") or "").strip()
        code_pid = match_alias(name, participants) or (match_alias(pid, participants) if pid not in ids else None)
        if pid in ids and code_pid and code_pid != pid:
            w.append(f"model matched '{name}' to {pid}, but it is an alias of {code_pid}; using {code_pid}")
            pid = code_pid
        elif pid not in ids:
            if code_pid:
                pid = code_pid
            else:
                w.append(f"unknown participant '{name or pid}': not on the roster")
                run_warn.append(f"{label}: unknown participant '{name or pid}'")
                pid = ""

        # date: must be in the window; weekday/day-of-month the worker wrote wins over the model
        raw_date = str(it.get("date") or "").strip()[:10]
        try:
            model_date = date.fromisoformat(raw_date).isoformat()
        except ValueError:
            model_date = ""
        day_written = str(it.get("day_written") or "").strip()
        implied = dates_from_day_written(day_written, window)
        d_iso = model_date
        if len(implied) == 1 and implied[0].isoformat() != model_date:
            d_iso = implied[0].isoformat()
            w.append(f"date set to {d_iso} from '{day_written}' (model said {model_date or raw_date or 'nothing'})")
        elif len(implied) > 1 and model_date in in_window:
            w.append(f"day written '{day_written}' is ambiguous; kept {model_date}")
        if d_iso not in in_window:
            run_warn.append(f"dropped {label}: date {raw_date or '?'} is outside the week "
                            f"{window[0].isoformat()}..{window[-1].isoformat()}")
            continue

        # times
        start, end = norm_time(it.get("start")), norm_time(it.get("end"))
        if not start or not end:
            run_warn.append(f"dropped {label}: times not HH:MM (start={it.get('start')!r}, end={it.get('end')!r})")
            continue
        if _APPROX_RE.search(quote):
            w.append(f"approximate time in '{quote}': check start/end")
        if _minutes(end) <= _minutes(start):
            w.append(f"end {end} is not after start {start}: treated as overnight, finishing next day")
            dur = _minutes(end) + 1440 - _minutes(start)
        else:
            dur = _minutes(end) - _minutes(start)
        if _minutes(start) < 6 * 60 and dur < 12 * 60 and _minutes(end) > _minutes(start):
            w.append(f"start {start} is before 6am: check am/pm")
        if dur > 12 * 60:
            w.append(f"shift is {dur / 60:.1f} hours long: check times")

        # km: only if written
        try:
            km = max(0.0, float(it.get("km") or 0))
        except (TypeError, ValueError):
            km = 0.0
        note = str(it.get("note") or "").strip()
        if km and not from_image:
            if _km_stated(km, quote + " " + note):
                pass
            elif _km_stated(km, text):
                w.append(f"{_num_str(km)} km is in the diary but not in this shift's text: check it belongs here")
            else:
                w.append(f"model gave {_num_str(km)} km but no such km figure is in the diary: set to 0")
                km = 0.0

        # note must be verbatim
        if note and not from_image and norm_text(note) not in norm_diary:
            w.append("note is not word-for-word from the diary: check it")

        key = (pid, d_iso, start, end)
        if key in seen:
            run_warn.append(f"dropped duplicate {label}")
            continue
        seen.add(key)
        shifts.append(Shift(participant_id=pid, date=d_iso, start=start, end=end, km=round(km, 2),
                            note=note, source_quote=quote, warnings=w))

    shifts.sort(key=lambda s: (s.date, s.start, s.participant_id))
    return shifts, run_warn


# --------------------------------------------------------------------------- entry point

def extract_shifts(diary_text: str, roster, week_ending: str, model: str = llm.DEFAULT_MODEL,
                   image_path: str | None = None) -> tuple[list[Shift], list[str], dict]:
    """One model call for the whole week. Returns (shifts, run_warnings, llm_meta)."""
    participants = as_participants(roster)
    window = week_window(week_ending)
    from_image = bool(image_path)
    if not from_image and not (diary_text or "").strip():
        return [], ["diary is empty"], {"model": model, "total_s": 0.0, "attempts": 0}
    messages = build_messages(diary_text or "", participants, window, from_image=from_image)
    obj, meta = llm.chat(messages, shift_schema([p.id for p in participants]), model=model,
                         images=[image_path] if from_image else None)
    items = obj.get("shifts")
    if not isinstance(items, list):
        return [], ["model reply had no 'shifts' list"], meta
    shifts, warns = validate_shifts(items, diary_text or "", participants, window, from_image=from_image)
    if from_image:
        warns.append("photo input: notes and km could not be checked against typed text; review them")
    meta["raw_count"] = len(items)
    return shifts, warns, meta
