"""Shift note -> possible NDIS regulated restrictive practices (RPFlag).

One model call per non-empty note. Code keeps a flag only if its type is one of
the five regulated types and its evidence quote is really in the note, then
computes the reporting deadline.
"""

from __future__ import annotations

import re

from . import llm
from .extract import as_participants, find_verbatim
from .models import Participant, RPFlag, Shift

RP_TYPES = ("seclusion", "chemical", "mechanical", "physical", "environmental")

RP_SCHEMA = {
    "type": "object",
    "properties": {
        "flags": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "evidence_quote": {"type": "string"},
                    "explanation": {"type": "string"},
                    "rp_type": {"type": "string", "enum": list(RP_TYPES)},
                    "harm_mentioned": {"type": "boolean"},
                    "authorised_in_bsp": {"type": "boolean"},
                },
                "required": ["evidence_quote", "explanation", "rp_type", "harm_mentioned", "authorised_in_bsp"],
            },
        }
    },
    "required": ["flags"],
}

SYSTEM_PROMPT = (
    "You screen an NDIS support worker's shift note for possible regulated restrictive practices. "
    "Report only what the note says was done to the participant. Most notes contain none."
)

RUBRIC = """THE FIVE REGULATED RESTRICTIVE PRACTICES (use only these types):
- seclusion: the person is left alone in a room or space they cannot leave, or believe they cannot leave.
- chemical: a medication given mainly to change behaviour, not to treat a diagnosed illness or condition.
- mechanical: a device used to stop or limit movement because of behaviour (e.g. bed rails, splints, lap belt, harness, mittens).
- physical: physical force to stop, hold or subdue the person's movement because of behaviour (e.g. holding wrists, pinning down, a restraint hold).
- environmental: stopping free access to places or things (e.g. locking the pantry or fridge, taking their phone away, locking doors so they cannot leave).

NOT restrictive practices (never flag these):
- offering choices, redirection, verbal de-escalation, giving the person space
- the person chose to go to their room
- holding the person's hand to cross a road safely, at their request
- a PRN medication given and recorded as per the plan, when that PRN is in the authorised list below
- ordinary support: meals, shopping, outings, prompting, regular prescribed medication (e.g. Webster pack)"""

INSTRUCTIONS = """For each restrictive practice in the note give:
- evidence_quote: the sentence from the note that shows it, copied character for character
- explanation: one plain-English sentence saying what was restricted and why it is that type
- rp_type: one of seclusion, chemical, mechanical, physical, environmental
- harm_mentioned: true only if the note mentions injury, pain, bruising or harm to anyone
- authorised_in_bsp: true only if this practice is in the authorised list above
If the note has no restrictive practice, return {"flags": []}."""


def _participant_block(p: Participant | None) -> str:
    if p is None:
        return "PARTICIPANT: unknown. Authorised in behaviour support plan: none."
    auth = "; ".join(p.bsp_authorised) if p.bsp_authorised else "none"
    return f"PARTICIPANT: {p.name} ({p.id}). Authorised in behaviour support plan: {auth}."


def build_messages(shift: Shift, participant: Participant | None) -> list[dict]:
    user = (f"{RUBRIC}\n\n{_participant_block(participant)}\n\n"
            f'SHIFT NOTE ({shift.date}):\n"""\n{shift.note.strip()}\n"""\n\n{INSTRUCTIONS}')
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}]


def is_screenable(note: str) -> bool:
    """Skip empty notes and notes with no words at all (e.g. '12km')."""
    return bool(re.search(r"[A-Za-z]{2,}", note or "")) and not re.fullmatch(
        r"\s*\d+(\.\d+)?\s*(km|kms|k)?\s*", note or "", re.I)


def _as_bool(v) -> bool:
    if isinstance(v, str):
        return v.strip().lower() in {"true", "yes", "1"}
    return bool(v)


def report_deadline(iso_date: str, harm: bool) -> tuple[str, str | None]:
    """(report_by, warning). Harm -> 24h window; else 5 business days via arvo.calendar_au if present."""
    if harm:
        return f"within 24 hours of {iso_date}", None
    try:
        from arvo.calendar_au import add_business_days
    except ImportError:
        return "", None
    try:
        return str(add_business_days(iso_date, 5)), None
    except Exception as e:  # calendar data gap etc: flag still stands, deadline left blank
        return "", f"could not compute report_by for {iso_date}: {e}"


def validate_flag(raw: dict, shift: Shift, participant: Participant | None) -> tuple[RPFlag | None, str | None]:
    """Code checks on one model flag. Returns (flag or None, warning or None)."""
    where = f"{shift.participant_id or '?'} {shift.date}"
    rp_type = str(raw.get("rp_type") or "").strip().lower()
    rp_type = next((t for t in RP_TYPES if rp_type.startswith(t)), rp_type)
    if rp_type not in RP_TYPES:
        return None, f"{where}: dropped flag with unknown rp_type {raw.get('rp_type')!r}"
    quote = str(raw.get("evidence_quote") or "")
    span = find_verbatim(quote, shift.note)
    if not span:
        return None, f"{where}: model quote not found in note, flag dropped ({rp_type}: {quote[:80]!r})"
    harm = _as_bool(raw.get("harm_mentioned"))
    authorised = _as_bool(raw.get("authorised_in_bsp")) and bool(participant and participant.bsp_authorised)
    report_by, warn = report_deadline(shift.date, harm)
    flag = RPFlag(participant_id=shift.participant_id, date=shift.date, rp_type=rp_type,
                  evidence_quote=span, harm_mentioned=harm, authorised_in_bsp=authorised,
                  report_by=report_by, explanation=str(raw.get("explanation") or "").strip())
    return flag, (f"{where}: {warn}" if warn else None)


def screen_notes(shifts: list[Shift], roster, model: str = llm.DEFAULT_MODEL) -> tuple[list[RPFlag], dict]:
    """One model call per non-empty note. Returns (flags, meta); meta['warnings'] lists dropped flags etc."""
    people = {p.id: p for p in as_participants(roster)}
    flags: list[RPFlag] = []
    warnings: list[str] = []
    meta = {"model": model, "calls": 0, "skipped": 0, "total_s": 0.0, "load_s": 0.0,
            "prompt_tokens": 0, "eval_tokens": 0, "per_call_s": [], "warnings": warnings}
    for s in shifts:
        if not is_screenable(s.note):
            meta["skipped"] += 1
            continue
        p = people.get(s.participant_id)
        try:
            obj, m = llm.chat(build_messages(s, p), RP_SCHEMA, model=model)
        except llm.LLMError as e:
            warnings.append(f"{s.participant_id or '?'} {s.date}: note not screened ({e}); read it yourself")
            continue
        meta["calls"] += 1
        for k in ("total_s", "load_s", "prompt_tokens", "eval_tokens"):
            meta[k] += m.get(k, 0) or 0
        meta["per_call_s"].append(m.get("total_s", 0.0))
        seen: set[tuple] = set()
        for raw in obj.get("flags") or []:
            if not isinstance(raw, dict):
                continue
            flag, warn = validate_flag(raw, s, p)
            if warn:
                warnings.append(warn)
            if flag is None:
                continue
            key = (flag.rp_type, flag.evidence_quote.casefold())
            if key in seen:
                continue
            seen.add(key)
            flags.append(flag)
    meta["total_s"] = round(meta["total_s"], 3)
    meta["load_s"] = round(meta["load_s"], 3)
    return flags, meta
