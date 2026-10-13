"""Diary (text or photo) -> list[Shift].

The model reads the whole week in one call; Python then decides: dates must be
in the week window (and agree with the weekday the worker wrote), times must be
HH:MM, participants must be on the roster, notes must be verbatim.
"""

from __future__ import annotations

import difflib
import re
from datetime import date, timedelta

from . import llm
from .models import Participant, Shift

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
_WEEKDAY_TOKENS = [
    {"mon", "monday"},
    {"tue", "tues", "tuesday"},
    {"wed", "weds", "wednesday"},
    {"thu", "thur", "thurs", "thr", "thrs", "thursday"},
    {"fri", "friday"},
    {"sat", "saturday"},
    {"sun", "sunday"},
]
UNKNOWN = "unknown"
_MONTH_NAMES = ["january", "february", "march", "april", "may", "june", "july", "august", "september",
                "october", "november", "december"]


# --------------------------------------------------------------------------- text helpers

_QUOTE_MAP = str.maketrans({
    "‘": "'", "’": "'", "‚": "'", "′": "'", "`": "'",
    "“": '"', "”": '"', "„": '"', "″": '"',
    "–": "-", "—": "-", "−": "-", " ": " ",
})


def norm_text(s: str) -> str:
    """Casefold, straighten curly quotes/dashes, collapse whitespace."""
    return re.sub(r"\s+", " ", (s or "").translate(_QUOTE_MAP)).strip().casefold()


def _verbatim_regex(quote: str) -> str | None:
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
    return "".join(parts)


def find_span(quote: str, text: str, pos: int = 0) -> tuple[int, int] | None:
    """(start, end) of `quote` in `text` up to whitespace/case/curly quotes; searches from pos, then from 0."""
    rx = _verbatim_regex(quote)
    if not rx or not text:
        return None
    pat = re.compile(rx, re.IGNORECASE)
    m = pat.search(text, pos) or (pat.search(text) if pos else None)
    return (m.start(), m.end()) if m else None


def find_verbatim(quote: str, text: str) -> str | None:
    """Return the span of `text` that equals `quote` up to whitespace/case/curly quotes, else None."""
    sp = find_span(quote, text)
    return text[sp[0]:sp[1]] if sp else None


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


_AMBIGUOUS_DAY_WORDS = {"sat", "sun", "wed", "mon"}  # also ordinary words ("sat down", "the sun")


def weekday_index(tok: str, strict: bool = False) -> int | None:
    """'tues' -> 1. Also misspelt full names ('tuseday', 'thrusday'). strict=True ignores sat/sun/wed/mon."""
    tok = tok.casefold()
    for i, names in enumerate(_WEEKDAY_TOKENS):
        if tok in names:
            return None if strict and tok in _AMBIGUOUS_DAY_WORDS else i
    if len(tok) >= 5 and tok.endswith(("day", "days")):
        scores = sorted(((difflib.SequenceMatcher(None, tok, w.lower()).ratio(), i)
                         for i, w in enumerate(WEEKDAYS)), reverse=True)
        if scores[0][0] >= 0.8 and scores[0][0] - scores[1][0] >= 0.05:
            return scores[0][1]
    return None


def dates_from_day_written(day_written: str, window: list[date], strict: bool = False) -> list[date]:
    """Window dates implied by what the worker wrote ('Tues', 'Wed 4th', '3/11', 'Cup day').
    Returns [] if nothing parseable; >1 entries means the words disagree with each other."""
    s = (day_written or "").casefold()
    found: set[date] = set()
    toks = re.findall(r"[a-z]+", s)
    wds = {i for i in (weekday_index(t, strict) for t in toks) if i is not None}
    if len(wds) == 1:
        found |= {d for d in window if d.weekday() in wds}
    elif len(wds) > 1:
        return list(window)  # e.g. "Mon/Tue": ambiguous, signal disagreement
    for m in re.finditer(r"\b(\d{1,2})/(\d{1,2})\b", s):
        dd, mm = int(m.group(1)), int(m.group(2))
        found |= {d for d in window if d.day == dd and d.month == mm}
    for m in re.finditer(r"\b(\d{1,2})(?:st|nd|rd|th)\b", s):
        found |= {d for d in window if d.day == int(m.group(1))}
    for m in re.finditer(r"\b(\d{1,2})(?:st|nd|rd|th)?\s*(?:of\s+)?([a-z]{3,9})\b", s):
        mon = _month(m.group(2))
        found |= {d for d in window if mon and d.day == int(m.group(1)) and d.month == mon}
    for m in re.finditer(r"\b([a-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?\b", s):
        mon = _month(m.group(1))
        found |= {d for d in window if mon and d.day == int(m.group(2)) and d.month == mon}
    if "cup" in toks:
        found |= {d for d in window if "Melbourne Cup day" in _day_labels(d)}
    return sorted(found)


def _month(word: str) -> int | None:
    """'nov' / 'November' / 'sept' -> 11 / 11 / 9."""
    w = word.casefold()
    if w == "sept":
        return 9
    return next((i + 1 for i, n in enumerate(_MONTH_NAMES) if len(w) >= 3 and n.startswith(w)), None)


_DAYISH_RE = re.compile(r"\b(?:\d{1,2}(?:st|nd|rd|th)|\d{1,2}/\d{1,2}|yesterday|today|tonight|"
                        r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*)\b", re.I)


def parse_model_date(raw: str, window: list[date]) -> str:
    """The model's date field -> ISO. ISO first; else read it like diary text (DD/MM, 'Tues', '3rd')."""
    try:
        return date.fromisoformat(raw[:10]).isoformat()
    except ValueError:
        pass
    implied = dates_from_day_written(raw, window)
    return implied[0].isoformat() if len(implied) == 1 else ""


# --------------------------------------------------------------------------- prompt + schema

SHIFT_FIELDS = ["day_written", "date", "name_written", "participant_id",
                "times_written", "start", "end", "km", "note"]


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
                        "date": {"type": "string"},
                        "name_written": {"type": "string"},
                        "participant_id": {"type": "string", "enum": [*participant_ids, UNKNOWN]},
                        "times_written": {"type": "string"},
                        "start": {"type": "string"},
                        "end": {"type": "string"},
                        "km": {"type": "number"},
                        "note": {"type": "string"},
                    },
                    "required": SHIFT_FIELDS,
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
1. One item per shift: one participant and one block of time. Two blocks of time on one line (e.g. "9-11, then back 4-6") are two items. A day heading (e.g. "Tues", "Wed 4th", "Cup day") applies to every line under it until the next heading.
2. day_written: the day words exactly as the diary has them. date: the matching ISO date from WEEK.
3. times_written: the time words exactly as written, keeping ish/about, e.g. "3 till 8:30ish". start and end: 24-hour HH:MM. Australian usage: "arvo" = afternoon. With no am/pm, pick the reading that gives a normal day or evening shift: "3 till 8:30" = 15:00 to 20:30, "9-1" = 09:00 to 13:00, "half 3" = 15:30, "quarter to 5" = 16:45, "7ish" in the evening = 19:00, "noon" = 12:00, "midnight" = 00:00.
4. km: the kilometres written for that shift. 0 if no km is written. Never estimate.
5. note: everything the worker wrote about that shift apart from the name and times, copied exactly (same spelling, same punctuation, every sentence). "" if nothing.
6. name_written: the participant name exactly as written. participant_id: from PARTICIPANTS, or "unknown".
7. List every shift, including ones added late or out of order at the end of the diary. Skip only days off, cancelled shifts and reminders."""


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
                "then list the shifts. Copy names, times and notes as written on the page.")
    else:
        body = f'DIARY:\n"""\n{diary_text.strip()}\n"""'
    return [{"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": head + body}]


# --------------------------------------------------------------------------- validation

_TIME_RE = re.compile(r"^\s*(\d{1,2})[:.h](\d{2})\s*$")
_APPROX_RE = re.compile(r"\d[\s-]?ish\b|\bish\b|\babout\b|\bapprox|\baround\b|\broughly\b|\babt\b|~", re.I)


def norm_time(t: str) -> str | None:
    m = _TIME_RE.match(str(t or ""))
    if not m:  # e.g. "3:00 PM", "1530": accept one explicit time expression
        toks = parse_written_times(str(t or ""))
        return _hhmm(toks[0][0] * 60 + toks[0][1]) if len(toks) == 1 and toks[0][2] else None
    h, mi = int(m.group(1)), int(m.group(2))
    if h == 24 and mi == 0:
        h = 0
    if h > 23 or mi > 59:
        return None
    return f"{h:02d}:{mi:02d}"


def _minutes(t: str) -> int:
    return int(t[:2]) * 60 + int(t[3:])


def _hhmm(mins: int) -> str:
    mins %= 1440
    return f"{mins // 60:02d}:{mins % 60:02d}"


_TIME_TOKEN_RE = re.compile(r"""
    (?P<half>\bhalf\s+(?:past\s+)?(?P<halfh>\d{1,2})\b)
  | (?P<qp>\bquarter\s+past\s+(?P<qph>\d{1,2})\b)
  | (?P<qt>\bquarter\s+to\s+(?P<qth>\d{1,2})\b)
  | (?P<noon>\bnoon\b|\bmidday\b)
  | (?P<midnight>\bmidnight\b)
  | (?P<mil>(?<![\d/])\b(?P<milh>[01]\d|2[0-3])(?P<milm>[0-5]\d)\b(?![/\d]))
  | (?P<num>(?<![\d:./$])(?<!km\s)(?<!km)(?P<h>\d{1,2})(?:[:.](?P<m>[0-5]\d))?(?![\d/])
        (?!st\b|nd\b|rd\b|th\b)(?!\s*(?:kms?|k)\b(?!\s*:?\s*\d))(?:\s*(?P<ap>[ap]\.?m\b\.?|[ap](?![a-z])))?)
""", re.X | re.I)

_RANGE_SEP_RE = re.compile(r"^\s*(?:-+|–|—|to|till|til|'til|until|untill|thru)\s*$", re.I)

Tok = tuple[int, int, bool]  # (hour, minute, explicit)


def _token(m: re.Match) -> Tok | None:
    if m.group("half"):
        h, mi, ex = int(m.group("halfh")), 30, False
    elif m.group("qp"):
        h, mi, ex = int(m.group("qph")), 15, False
    elif m.group("qt"):
        h, mi, ex = (int(m.group("qth")) - 1) or 12, 45, False
    elif m.group("noon"):
        h, mi, ex = 12, 0, True
    elif m.group("midnight"):
        h, mi, ex = 0, 0, True
    elif m.group("mil"):
        h, mi, ex = int(m.group("milh")), int(m.group("milm")), True
    else:
        raw_h = m.group("h")
        h, mi = int(raw_h), int(m.group("m") or 0)
        ap = (m.group("ap") or "").lower()[:1]
        if ap == "p" and h < 12:
            h, ex = h + 12, True
        elif ap == "a":
            h, ex = (0 if h == 12 else h), True
        else:
            ex = h > 12 or h == 0 or (len(raw_h) == 2 and raw_h.startswith("0"))
    return None if h > 23 or mi > 59 else (h, mi, ex)


_DATE_MASK_RE = re.compile(r"\b\d{4}-\d{1,2}-\d{1,2}\b|\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b|\b\d{1,2}-\d{1,2}-\d{4}\b")


def _mask_dates(text: str) -> str:
    """Blank out written dates (2026-11-03, 3/11, 3/11/26) so their digits are never read as times."""
    return _DATE_MASK_RE.sub(lambda m: " " * len(m.group()), text or "")


def time_tokens(text: str) -> list[tuple[int, int, Tok]]:
    """[(start, end, (hour, minute, explicit))] for each time expression. explicit=False means no am/pm
    and a 1-12 hour, so the half of the day is unknown. Dates, ordinals ('4th') and km are not times."""
    out = []
    for m in _TIME_TOKEN_RE.finditer(_mask_dates(text)):
        tok = _token(m)
        if tok:
            out.append((m.start(), m.end(), tok))
    return out


def parse_written_times(text: str) -> list[Tok]:
    return [t for _, _, t in time_tokens(text)]


def time_ranges(text: str) -> list[tuple[int, int, Tok, Tok]]:
    """'3 till 8:30', '9am-1pm', 'half 4-6:30' -> [(start, end, from_tok, to_tok)] in text order."""
    toks, out, i = time_tokens(text), [], 0
    while i < len(toks) - 1:
        (a0, a1, ta), (b0, b1, tb) = toks[i], toks[i + 1]
        if _RANGE_SEP_RE.match(text[a1:b0]) and ta != tb:
            out.append((a0, b1, ta, tb))
            i += 2
        else:
            i += 1
    return out


def _cands(tok: Tok) -> list[int]:
    h, mi, ex = tok
    return [h * 60 + mi] if ex else [(h % 12) * 60 + mi, (h % 12 + 12) * 60 + mi]


def resolve_range(t1: Tok, t2: Tok, *, after: int | None = None, model_start: int | None = None,
                  model_end: int | None = None) -> tuple[int, int]:
    """Minutes since midnight for a written range. No am/pm: agree with the model if it fits, else
    start after `after` (second block of a split day), else the shortest shift to an explicit end, else
    1-6 and 12 = pm, 7-11 = am. An ambiguous end is the first reading after the start."""
    c = _cands(t1)
    if len(c) == 1:
        s = c[0]
    elif model_start in c:
        s = model_start
    elif after is not None:
        s = min((x for x in c if x >= after), default=c[1])
    elif t2[2]:
        e = t2[0] * 60 + t2[1]
        s = min(c, key=lambda x: (e - x) % 1440 or 1440)
    else:
        h12 = t1[0] % 12 or 12
        s = c[1] if (h12 <= 6 or h12 == 12) else c[0]
    c = _cands(t2)
    if len(c) == 1:
        e = c[0]
    elif model_end in c:
        e = model_end
    else:
        e = min((x for x in c if x > s), default=min(c))
    return s, e


def reconcile_times(times_written: str, start: str, end: str) -> tuple[str, str, list[str]]:
    """Code wins over the model where the written times are unambiguous; digits always come from the text.
    Then fix an ambiguous end/start that only makes sense +12h (e.g. '3 till 8:30' read as 15:00-08:30)."""
    toks = parse_written_times(times_written)
    warns: list[str] = []
    if len(toks) != 2:
        return start, end, warns
    fixed = []
    for label, model_t, (h, mi, ex) in (("start", start, toks[0]), ("end", end, toks[1])):
        mm = _minutes(model_t)
        if ex:
            want = h * 60 + mi
        elif mm // 60 % 12 == h % 12 and mm % 60 == mi:
            want = mm
        else:  # keep the model's am/pm half, take hour/minute from the text
            want = (h % 12 + (12 if mm >= 12 * 60 else 0)) * 60 + mi
        if want != mm:
            warns.append(f"{label} set to {_hhmm(want)} from '{times_written}' (model said {model_t})")
        fixed.append((want, ex))
    (s_m, s_ex), (e_m, e_ex) = fixed
    if not e_ex and e_m <= s_m and e_m < 12 * 60 and e_m + 720 > s_m:
        warns.append(f"end read as {_hhmm(e_m + 720)} (not {_hhmm(e_m)}) so the shift ends after it starts")
        e_m += 720
    if not s_ex and s_m < 6 * 60 and s_m + 720 < e_m:
        warns.append(f"start read as {_hhmm(s_m + 720)} (not {_hhmm(s_m)}): no am/pm written")
        s_m += 720
    return _hhmm(s_m), _hhmm(e_m), warns


def _num_str(x: float) -> str:
    return str(int(x)) if float(x).is_integer() else f"{x:g}"


_KM_RE = re.compile(r"(?<![\d.])(\d+(?:\.\d+)?)\s*(?:kms?|kilomet\w*|k)\b(?!\s*:?\s*\d)"
                    r"|\b(?:kms?|kilomet\w*)\s*:?\s*(\d+(?:\.\d+)?)(?![\d.])", re.I)


def km_figures(text: str) -> list[float]:
    """Every km figure written, either way round: '12km', '8 kms', 'km 29', 'kms: 4'."""
    return [float(m.group(1) or m.group(2)) for m in _KM_RE.finditer(text or "")]


def _km_stated(km: float, text: str) -> bool:
    return any(abs(f - km) < 0.05 for f in km_figures(text))


# --------------------------------------------------------------------------- where each shift sits in the diary

def _line_bounds(text: str, i: int, j: int) -> tuple[int, int]:
    ls = text.rfind("\n", 0, i) + 1
    le = text.find("\n", j)
    return ls, (len(text) if le < 0 else le)


def _lines(text: str):
    pos = 0
    for line in text.split("\n"):
        yield pos, pos + len(line)
        pos += len(line) + 1


def _find_range_by_name(name: str, model_start: int | None, text: str, pos: int) -> tuple[int, int] | None:
    """The model's times_written is not verbatim: take the first time range on a line with the name whose
    start agrees with the model's start."""
    rx = _verbatim_regex(name)
    if not rx:
        return None
    for from_pos in (pos, 0):
        for m in re.finditer(rx, text[from_pos:], re.I):
            ls, le = _line_bounds(text, from_pos + m.start(), from_pos + m.end())
            for r0, r1, t1, t2 in time_ranges(text[ls:le]):
                if model_start is None or resolve_range(t1, t2, model_start=model_start)[0] == model_start:
                    return ls + r0, ls + r1
    return None


def _locate(it: dict, text: str, pos: int) -> tuple[int, int, int, int] | None:
    """(quote_start, quote_end, times_start, times_end) of one model item in the diary, or None."""
    tw, name = str(it.get("times_written") or ""), str(it.get("name_written") or "")
    tsp = find_span(tw, text, pos) if tw else None
    if not tsp and name:
        ms = norm_time(it.get("start"))
        tsp = _find_range_by_name(name, _minutes(ms) if ms else None, text, pos)
    if tsp:
        ls, le = _line_bounds(text, tsp[0], tsp[1])
        nsp = find_span(name, text[ls:le]) if name else None
        if nsp:
            return min(ls + nsp[0], tsp[0]), max(ls + nsp[1], tsp[1]), tsp[0], tsp[1]
        return tsp[0], tsp[1], tsp[0], tsp[1]
    q = find_span(str(it.get("source_quote") or ""), text, pos)
    return (q[0], q[1], q[0], q[1]) if q else None


def locate_shifts(items: list, text: str) -> list[dict | None]:
    """For each model item, offsets in the diary (code-side, verbatim by construction):
    q0..q1 = name + times (the source_quote), t0..t1 = the times, s0..s1 = the shift's slice: from the quote
    to the end of that line (or of the line where the model's note ends, if later), never past the next shift."""
    spans: list[tuple | None] = []
    pos = 0
    for it in items:
        it = it if isinstance(it, dict) else {}
        q = _locate(it, text, pos)
        if not q:
            spans.append(None)
            continue
        n = find_span(str(it.get("note") or ""), text, q[0])
        last = max(q[1], n[1] if n and n[0] >= q[0] else 0)
        spans.append((*q, last))
        pos = q[0] + 1
    starts = sorted({sp[0] for sp in spans if sp})
    out: list[dict | None] = []
    for sp in spans:
        if not sp:
            out.append(None)
            continue
        q0, q1, t0, t1, last = sp
        eol = text.find("\n", max(last - 1, q0))
        end = min(len(text) if eol < 0 else eol, min((b for b in starts if b > q0), default=len(text)))
        out.append({"q0": q0, "q1": q1, "t0": t0, "t1": t1, "s0": q0, "s1": max(end, q1)})
    return out


_HEADING_WORDS = {"st", "nd", "rd", "th", "the", "cup", "day", "arvo", "morning", "evening", "night",
                  "am", "pm", "of", "on", "and"}


def _is_heading_line(line: str) -> bool:
    toks = re.findall(r"[a-z]+|\d+", line.casefold())
    return 0 < len(toks) <= 6 and all(t.isdigit() or t in _HEADING_WORDS or weekday_index(t) is not None
                                      for t in toks)


def context_date(text: str, t0: int, t1: int, window: list[date]) -> tuple[date | None, str]:
    """The day the diary itself gives for the times at text[t0:t1]: words before the times on that line
    (plus up to 3 words after them), else the nearest earlier day heading or dated shift line.
    Returns (date, the words used) or (None, '') if nothing or a contradiction."""
    ls, le = _line_bounds(text, t0, t1)
    before = text[ls:t0]
    after = " ".join(re.findall(r"[A-Za-z0-9/]+", text[t1:le])[:3])
    found = set(dates_from_day_written(before, window)) | set(dates_from_day_written(after, window, strict=True))
    if found:
        return (found.pop(), (before + " " + after).strip()) if len(found) == 1 else (None, "")
    if _DAYISH_RE.search(before):  # the line names a day we cannot place: do not borrow one from above
        return None, ""
    pos = ls - 1
    while pos > 0:
        ps = text.rfind("\n", 0, pos) + 1
        line, pos = text[ps:pos], ps - 1
        if not line.strip() or re.search(r"\b(?:wk|week)\b", line, re.I):
            continue
        rngs = time_ranges(line)
        if rngs:
            region = line[:rngs[0][0]]
        elif _is_heading_line(line):
            region = line
        else:
            continue  # a note line
        found = set(dates_from_day_written(region, window))
        if len(found) == 1:
            return found.pop(), region.strip()
        if found:
            return None, ""
    return None, ""


def aliases_in(s: str, participants: list[Participant]) -> set[str]:
    """Participant ids whose name/alias (2+ letters, whole word) appears in s."""
    out = set()
    for p in participants:
        for a in {p.id, p.name, (p.name.split() or [""])[0], *p.aliases}:
            a = a.strip()
            if len(re.sub(r"\W", "", a)) >= 2 and re.search(rf"(?<![A-Za-z]){re.escape(a)}(?![A-Za-z])", s, re.I):
                out.add(p.id)
    return out


def _words(s: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", norm_text(s)))


def _full_note(note: str, seg: str | None, times_written: str) -> str:
    """Prefer the diary's own words: if the model's note is part of (or mostly matches) this shift's diary
    slice, return the whole slice after the times, so a sentence the model skipped or reworded still
    reaches the restrictive-practice screen verbatim."""
    if not seg:
        return note
    tsp = find_span(times_written, seg) if times_written else None
    tail = _strip_punct(seg[tsp[1]:] if tsp else seg)
    if not tail:
        return note
    if norm_text(note) in norm_text(tail):
        return tail if len(tail) > len(note) else note
    nw = _words(note)
    if nw and len(nw & _words(tail)) / len(nw) >= 0.6:
        return tail
    return note


def _strip_punct(s: str) -> str:
    """Trim separators around a slice of diary text; keeps a closing full stop or bracket."""
    return s.strip().lstrip(",.;:-–—) \t").rstrip(",;:-–—( \t").strip()


# --------------------------------------------------------------------------- double shifts on one line

def split_merged(it: dict, loc: dict | None, text: str) -> list[tuple[dict, dict | None]]:
    """One model item that covers two time blocks ('8:30-10:45am ... then back half 4-6:30') -> two items.
    Triggered when the model's times_written holds two ranges, or its end time is the end of the next
    range on the same diary line."""
    tw = str(it.get("times_written") or "")
    tw_r = time_ranges(tw)
    ms, me = norm_time(it.get("start")), norm_time(it.get("end"))
    model_start, model_end = (_minutes(ms) if ms else None), (_minutes(me) if me else None)
    pair: list = []
    ls = le = 0
    if loc:
        ls, le = _line_bounds(text, loc["t0"], loc["t1"])
        line_r = [(ls + a, ls + b, x, y) for a, b, x, y in time_ranges(text[ls:le])]
        k = next((i for i, r in enumerate(line_r) if r[0] < loc["t1"] and loc["t0"] < r[1]), None)
        if k is not None and k + 1 < len(line_r):
            pair = line_r[k:k + 2]
    merged = len(tw_r) == 2
    if not merged and len(pair) == 2 and model_end is not None:
        e1 = resolve_range(pair[0][2], pair[0][3], model_start=model_start)[1]
        e2 = resolve_range(pair[1][2], pair[1][3], after=e1)[1]
        merged = model_end % 1440 == e2 % 1440 != e1 % 1440
    if not merged:
        return [(it, loc)]
    blocks = pair if len(pair) == 2 else [(None, None, x, y) for _, _, x, y in tw_r]
    s1, e1 = resolve_range(blocks[0][2], blocks[0][3], model_start=model_start)
    s2, e2 = resolve_range(blocks[1][2], blocks[1][3], after=e1, model_end=model_end)
    why = f"split: '{tw or text[pair[0][0]:pair[1][1]]}' is two blocks of time"
    if pair:
        (a0, a1, _, _), (b0, b1, _, _) = pair
        q0 = min(loc["q0"], a0)
        loc1 = {"q0": q0, "q1": a1, "t0": a0, "t1": a1, "s0": q0, "s1": b0}
        loc2 = {"q0": b0, "q1": b1, "t0": b0, "t1": b1, "s0": b0, "s1": le}
        notes = (_strip_punct(text[a1:b0]), _strip_punct(text[b1:le]))
        tws = (text[a0:a1], text[b0:b1])
    else:
        loc1 = loc2 = None
        notes = (str(it.get("note") or ""), "")
        tws = (tw[tw_r[0][0]:tw_r[0][1]], tw[tw_r[1][0]:tw_r[1][1]])
    it1 = {**it, "times_written": tws[0], "start": _hhmm(s1), "end": _hhmm(e1), "note": notes[0],
           "_code_note": bool(pair), "_warn": [why]}
    it2 = {**it, "times_written": tws[1], "start": _hhmm(s2), "end": _hhmm(e2), "note": notes[1], "km": 0,
           "_code_note": bool(pair), "_warn": [why]}
    return [(it1, loc1), (it2, loc2)]


# --------------------------------------------------------------------------- one model item -> Shift

def _check_item(it: dict, loc: dict | None, text: str, participants: list[Participant], window: list[date],
                from_image: bool, run_warn: list[str]) -> Shift | None:
    ids = {p.id for p in participants}
    in_window = {d.isoformat() for d in window}
    times_written = str(it.get("times_written") or "").strip()
    if loc:
        quote, seg = text[loc["q0"]:loc["q1"]].strip(), text[loc["s0"]:loc["s1"]].strip()
    else:
        quote = (str(it.get("source_quote") or "").strip()
                 or f"{it.get('name_written') or ''} {times_written}".strip())
        seg = None
    label = f"'{quote}'" if quote else "a shift"
    w: list[str] = list(it.get("_warn") or [])

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

    # date: the day the diary gives (same line or nearest heading) > the model's day_written > model date
    raw_date = str(it.get("date") or "").strip()
    model_date = parse_model_date(raw_date, window)
    day_written = str(it.get("day_written") or "").strip()
    ctx, ctx_words = context_date(text, loc["t0"], loc["t1"], window) if loc else (None, "")
    implied = dates_from_day_written(day_written, window)
    d_iso = model_date
    if ctx:
        d_iso = ctx.isoformat()
        if d_iso != model_date:
            w.append(f"date set to {d_iso} from the diary's '{ctx_words[:40]}' "
                     f"(model said {model_date or raw_date or 'nothing'})")
    elif len(implied) == 1 and implied[0].isoformat() != model_date:
        d_iso = implied[0].isoformat()
        w.append(f"date set to {d_iso} from '{day_written}' (model said {model_date or raw_date or 'nothing'})")
    elif len(implied) > 1 and model_date in in_window:
        w.append(f"day written '{day_written}' is ambiguous; kept {model_date}")
    if d_iso not in in_window:
        run_warn.append(f"dropped {label}: date {raw_date or '?'} is outside the week "
                        f"{window[0].isoformat()}..{window[-1].isoformat()}")
        return None

    # times
    start, end = norm_time(it.get("start")), norm_time(it.get("end"))
    if not start or not end:
        run_warn.append(f"dropped {label}: times not HH:MM (start={it.get('start')!r}, end={it.get('end')!r})")
        return None
    start, end, tw = reconcile_times(times_written or quote, start, end)
    w.extend(tw)
    approx_src = times_written or quote
    if _APPROX_RE.search(approx_src):
        w.append(f"approximate time in '{approx_src}': check start/end")
    _time_sanity(start, end, w)

    # note: widen to the whole diary slice for this shift when the model's note is part of it
    note = str(it.get("note") or "").strip()
    if not it.get("_code_note"):
        note = _full_note(note, seg, times_written)

    # km: only if written; the figure in this shift's own slice of the diary wins
    try:
        km = max(0.0, float(it.get("km") or 0))
    except (TypeError, ValueError):
        km = 0.0
    if not from_image and text:
        own = seg if seg is not None else quote + " " + note
        figs = km_figures(own)
        if len(figs) == 1 and abs(figs[0] - km) >= 0.05:
            w.append(f"km set to {_num_str(figs[0])} from the diary (model said {_num_str(km)})")
            km = figs[0]
        elif km and not _km_stated(km, own):
            if _km_stated(km, text):
                w.append(f"{_num_str(km)} km is in the diary but not in this shift's text: check it belongs here")
            else:
                w.append(f"model gave {_num_str(km)} km but no such km figure is in the diary: set to 0")
                km = 0.0

    if note and not from_image and norm_text(note) not in norm_text(text):
        w.append("note is not word-for-word from the diary: check it")
    return Shift(participant_id=pid, date=d_iso, start=start, end=end, km=round(km, 2),
                 note=note, source_quote=quote, warnings=w)


def _time_sanity(start: str, end: str, w: list[str]) -> None:
    if _minutes(end) <= _minutes(start):
        w.append(f"end {end} is not after start {start}: treated as overnight, finishing next day")
        dur = _minutes(end) + 1440 - _minutes(start)
    else:
        dur = _minutes(end) - _minutes(start)
    if _minutes(start) < 6 * 60 and dur < 12 * 60 and _minutes(end) > _minutes(start):
        w.append(f"start {start} is before 6am: check am/pm")
    if dur > 12 * 60:
        w.append(f"shift is {dur / 60:.1f} hours long: check times")


# --------------------------------------------------------------------------- diary lines the model skipped

_SKIP_LINE_RE = re.compile(r"\b(?:cancel\w*|no[- ]show|didn'?t (?:go|happen|show)|called in sick|"
                           r"next (?:week|wk)|tomorrow)\b", re.I)


def recover_skipped(text: str, participants: list[Participant], window: list[date],
                    kept: list[tuple[Shift, dict | None]]) -> list[Shift]:
    """Time ranges in the diary that no model shift accounts for -> shifts, read by code, each with a
    warning. Needs a roster name in the range's part of the line (or a host shift on the same line, for a
    second block of time), a date from the diary, and a range that does not fall inside the host shift."""
    covered = [(loc["t0"], loc["t1"]) for _, loc in kept if loc]
    hosts = [(loc["s0"], loc["s1"], sh) for sh, loc in kept if loc]
    out: list[Shift] = []
    for ls, le in _lines(text):
        line = text[ls:le]
        rngs = [(ls + a, ls + b, x, y) for a, b, x, y in time_ranges(line)]
        for k, (r0, r1, t1, t2) in enumerate(rngs):
            if any(a < r1 and r0 < b for a, b in covered):
                continue
            cell0 = rngs[k - 1][1] if k else ls
            cell1 = rngs[k + 1][0] if k + 1 < len(rngs) else le
            near = text[cell0:r1] + " " + " ".join(re.findall(r"\S+", text[r1:cell1])[:3])
            if _SKIP_LINE_RE.search(near):
                continue
            host = next((sh for s0, s1, sh in hosts if s0 <= r0 < s1), None)
            who = aliases_in(text[cell0:cell1], participants)
            pid = next(iter(who)) if len(who) == 1 else (host.participant_id if host and not who else None)
            if not pid:
                continue
            ctx, _ = context_date(text, r0, r1, window)
            d = ctx.isoformat() if ctx else (host.date if host else None)
            if not d:
                continue
            same_day_host = host if host and host.date == d and host.participant_id == pid else None
            s, e = resolve_range(t1, t2, after=_minutes(same_day_host.end) if same_day_host else None)
            if same_day_host:
                hs, he = _minutes(same_day_host.start), _minutes(same_day_host.end)
                if max(hs, s) < min(he if he > hs else he + 1440, e if e > s else e + 1440):
                    continue  # a time inside the host shift's note, not a second block
            tail = text[r1:cell1]
            figs = km_figures(tail) if not same_day_host else []
            w = [f"added by code: the model did not list '{_strip_punct(text[cell0:r1])}'; check it"
                 if not same_day_host else
                 f"split: '{text[r0:r1]}' is a second block of time on the same line"]
            if _APPROX_RE.search(text[r0:r1]):
                w.append(f"approximate time in '{text[r0:r1]}': check start/end")
            _time_sanity(_hhmm(s), _hhmm(e), w)
            out.append(Shift(participant_id=pid, date=d, start=_hhmm(s), end=_hhmm(e),
                             km=figs[0] if len(figs) == 1 else 0.0, note=_strip_punct(tail),
                             source_quote=_strip_punct(text[cell0:r1]), warnings=w))
            covered.append((r0, r1))
    return out


# --------------------------------------------------------------------------- validation entry

def validate_shifts(items: list, diary_text: str, participants: list[Participant],
                    window: list[date], from_image: bool = False) -> tuple[list[Shift], list[str]]:
    """Code checks on the model's raw shift dicts, plus shifts the model skipped. Returns (shifts, run_warnings)."""
    text = diary_text or ""
    run_warn: list[str] = []
    raw = []
    for i, it in enumerate(items or []):
        if isinstance(it, dict):
            raw.append(it)
        else:
            run_warn.append(f"dropped model item #{i + 1}: not an object")
    locs = locate_shifts(raw, text) if text and not from_image else [None] * len(raw)
    work = [pair for it, loc in zip(raw, locs) for pair in split_merged(it, loc, text)]

    kept: list[tuple[Shift, dict | None]] = []
    seen: set[tuple] = set()
    for it, loc in work:
        sh = _check_item(it, loc, text, participants, window, from_image, run_warn)
        if sh is None:
            continue
        key = (sh.participant_id, sh.date, sh.start, sh.end)
        if key in seen:
            run_warn.append(f"dropped duplicate '{sh.source_quote}'")
            continue
        seen.add(key)
        kept.append((sh, loc))

    if text and not from_image:
        for sh in recover_skipped(text, participants, window, kept):
            key = (sh.participant_id, sh.date, sh.start, sh.end)
            if key not in seen:
                seen.add(key)
                kept.append((sh, None))
                run_warn.append(f"{sh.date} {sh.participant_id}: {sh.warnings[0]}")

    shifts = sorted((sh for sh, _ in kept), key=lambda s: (s.date, s.start, s.participant_id))
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
