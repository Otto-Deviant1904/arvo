"""Baselines for the Arvo eval.

(a) keyword_screen: a restrictive-practice screen a careful developer could write from the five
    NDIS definitions without seeing the test notes. The list below was written once, before any eval
    run, and is frozen: do not tune it against eval/fixtures (that would make the comparison dishonest).
(b) model_alone_lines: "what if we let the model decide": one Gemma call per diary that gets the same
    diary + roster + the NDIS price table and writes the invoice lines itself (item, hours, price, total).
    Skipped (returns None) if data/ndis_prices_2026_27.json does not exist.
"""

from __future__ import annotations

import json
import re
import time
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRICES_PATH = ROOT / "data" / "ndis_prices_2026_27.json"
RP_TYPES = ("seclusion", "chemical", "mechanical", "physical", "environmental")

# ---------------------------------------------------------------------------------------------
# (a) keyword baseline for restrictive practices (frozen; see module docstring)
# ---------------------------------------------------------------------------------------------
RP_KEYWORDS: dict[str, list[str]] = {
    "seclusion": [
        r"\bseclu", r"\bshut (him|her|them) in\b", r"\blocked (him|her|them) in\b", r"\bconfine",
        r"\btime[- ]?out\b", r"\bwouldn'?t let (him|her|them) (out|leave)", r"\bkept (him|her|them) in\b",
        r"\bheld the door\b", r"\bdoor (shut|closed)\b", r"\b(by|on) (him|her|them)sel(f|ves)\b.*\b(room|door)\b",
    ],
    "chemical": [
        r"\bsedat", r"\bprn\b", r"\bextra (dose|tablet|pill|med)", r"\bdoubled? (up )?(the |his |her )?(dose|meds?)",
        r"\b(valium|diazepam|lorazepam|seroquel|quetiapine|risperidone|olanzapine|phenergan|promethazine)\b",
        r"\b(calming|sleeping) (tablet|pill)", r"\bto (calm|settle) (him|her|them)( down)?\b.*\b(tablet|pill|med)",
        r"\bchemical restraint",
    ],
    "mechanical": [
        r"\bstrap", r"\bbelt(ed)?\b", r"\bharness", r"\bsplint", r"\bmitt(en)?s?\b", r"\bbuckle guard",
        r"\bbed ?rails?\b", r"\bcot sides?\b", r"\btied\b", r"\btray table\b", r"\bmechanical restraint",
    ],
    "physical": [
        r"\brestrain", r"\bheld (him|her|them) down\b", r"\bpin(ned)? (him|her|them)\b",
        r"\bheld (his|her|their) (arms?|wrists?|hands?|legs?|head)\b", r"\bphysical(ly)? (restrain|held|hold|stopp)",
        r"\bgrab(bed)? (him|her|them)\b", r"\bsat on (him|her|them)\b", r"\bbear[- ]?hug", r"\bprone\b",
        r"\bheld (him|her|them)\b",
    ],
    "environmental": [
        r"lock", r"\btook (his|her|their) \w+ (away|off)", r"\bconfiscat", r"\bnot allowed\b", r"\bbanned\b",
        r"\bhid (his|her|their)\b", r"\bremoved (his|her|their)\b", r"\b(wifi|internet) off\b",
        r"\bturned (off )?(the |his |her )?(wifi|internet|tv|power)( off)?\b",
    ],
}
SECLUSION_LOCK = re.compile(r"\block(ed)? (him|her|them) in\b", re.I)
HARM_RE = re.compile(r"\b(bruis\w*|injur\w*|hurt\w*|bleed\w*|blood\w*|graz\w*|scrap\w*|cuts?|marks?|fell|fall\w*|"
                     r"pain\w*|swell\w*|swollen|wound\w*)\b", re.I)


def sentences(note: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", note or "") if s.strip()]


def keyword_types(text: str) -> list[tuple[str, str]]:
    """[(rp_type, matching sentence)] for every type whose keywords hit; first matching sentence per type."""
    out: dict[str, str] = {}
    for sent in sentences(text):
        for t in RP_TYPES:
            if t in out:
                continue
            for pat in RP_KEYWORDS[t]:
                if t == "environmental" and pat == "lock" and SECLUSION_LOCK.search(sent):
                    continue  # "locked him in" is seclusion, already covered above
                if re.search(pat, sent, re.I):
                    out[t] = sent
                    break
    return [(t, out[t]) for t in RP_TYPES if t in out]


def keyword_rp(note: str, bsp_authorised: list[str] | None = None) -> list[dict]:
    """Keyword flags for one note. A type is 'authorised' if the participant's BSP lists a practice
    whose own text maps to the same type (the obvious rule without a model)."""
    auth_types = {t for txt in (bsp_authorised or []) for t, _ in keyword_types(txt)}
    harm = bool(HARM_RE.search(note or ""))
    return [{"rp_type": t, "evidence_quote": s, "authorised_in_bsp": t in auth_types, "harm_mentioned": harm}
            for t, s in keyword_types(note)]


def keyword_screen(shifts, roster) -> list[dict]:
    """Flags (as dicts shaped like arvo.models.RPFlag) for every shift note."""
    people = {p["id"]: p for p in (roster.get("participants", []) if isinstance(roster, dict) else roster)}
    flags = []
    for s in shifts:
        s = s if isinstance(s, dict) else s.__dict__
        auth = (people.get(s["participant_id"]) or {}).get("bsp_authorised", [])
        for f in keyword_rp(s.get("note", ""), auth):
            flags.append({"participant_id": s["participant_id"], "date": s["date"], **f})
    return flags


# ---------------------------------------------------------------------------------------------
# (b) model-alone pricing baseline
# ---------------------------------------------------------------------------------------------
LINES_SCHEMA_ITEM = {
    "type": "object",
    "properties": {
        "participant_id": {"type": "string"},
        "date": {"type": "string"},
        "item_number": {"type": "string"},
        "quantity": {"type": "number"},
        "unit_price": {"type": "number"},
        "total": {"type": "number"},
    },
    "required": ["participant_id", "date", "item_number", "quantity", "unit_price", "total"],
}


def lines_schema(participant_ids: list[str]) -> dict:
    item = json.loads(json.dumps(LINES_SCHEMA_ITEM))
    item["properties"]["participant_id"]["enum"] = participant_ids
    return {"type": "object", "properties": {"lines": {"type": "array", "items": item}}, "required": ["lines"]}


def load_price_table() -> dict | None:
    if not PRICES_PATH.exists():
        return None
    return json.loads(PRICES_PATH.read_text(encoding="utf-8"))


def km_rules(roster) -> dict[str, dict]:
    """Which km item/rate the engine uses per support type: probe arvo.pricing with a 1 km shift,
    so the baseline is told exactly the rule the deterministic code applies."""
    from arvo.models import Shift
    from arvo.pricing import price_shifts

    out = {}
    for p in roster["participants"]:
        st = p["support_type"]
        if st in out:
            continue
        lines, _ = price_shifts([Shift(p["id"], "2026-10-14", "10:00", "11:00", 1.0, "")], roster)
        km = [ln for ln in lines if ln.unit != "H"]
        if km:
            out[st] = {"item_number": km[0].item_number, "item_name": km[0].item_name, "unit_price": km[0].unit_price}
    return out


def compact_price_table(table: dict, roster: dict) -> dict:
    """The parts of the price JSON a human invoicer needs: items, band definitions, boundary rule, km rule."""
    items = []
    for fam, lst in table["items"].items():
        if isinstance(lst, list):
            for it in lst:
                items.append({"item_number": it["item_number"], "item_name": it["item_name"],
                              "time_band": it["time_band"], "unit": it["unit"],
                              "price_limit_aud": it["price_limit_national_aud"]})
    defs = dict(table["time_bands"]["definitions_verbatim"])
    defs.pop("night_time_sleepover_support", None)
    return {
        "hour_items": items,
        "which_items": {"self_care": "Assistance With Self-Care Activities items",
                        "community": "Access Community Social and Rec Activ items"},
        "time_band_definitions": defs,
        "boundary_rule": table["boundary_rule"]["rule_2026_27_verbatim"],
        "km_lines": km_rules(roster),
    }


def _week_lines(week_ending: str) -> str:
    end = date.fromisoformat(week_ending)
    out = []
    for i in range(7):
        d = end - timedelta(days=6 - i)
        extra = ""
        try:
            from arvo.calendar_au import holiday_name
            name = holiday_name(d.isoformat())
            extra = f" (Victorian public holiday: {name})" if name else ""
        except ImportError:
            pass
        out.append(f"- {d.strftime('%A')} {d.isoformat()}{extra}")
    return "\n".join(out)


def build_messages(diary_text: str, roster: dict, week_ending: str, table: dict) -> list[dict]:
    people = [{"participant_id": p["id"], "name": p["name"], "aliases": p["aliases"],
               "support_type": p["support_type"]} for p in roster["participants"]]
    user = (
        f"NDIS PRICE TABLE 2026-27 (Victoria, non-remote):\n{json.dumps(compact_price_table(table, roster), indent=1)}\n\n"
        f"PARTICIPANTS:\n{json.dumps(people, indent=1)}\n\n"
        f"WEEK (week ending {week_ending}):\n{_week_lines(week_ending)}\n\n"
        "TASK: write the invoice lines for every shift in the diary below.\n"
        "- One hours line per shift: item_number = the item for the participant's support_type and the shift's "
        "time band (apply the definitions and the boundary rule), date = ISO date the shift started, quantity = "
        "hours worked rounded to 2 decimals, unit_price = the item's price limit, total = quantity x unit_price "
        "rounded to cents.\n"
        "- If km are written for a shift, add one km line for it: the km_lines item for that support_type, "
        "quantity = km, unit_price = its unit_price, total = quantity x unit_price rounded to cents.\n"
        "- Skip anything that is not a shift worked.\n\n"
        f'DIARY:\n"""\n{diary_text.strip()}\n"""'
    )
    return [{"role": "system", "content": "You are an invoicing assistant for an Australian NDIS independent "
                                          "support worker. Reply with JSON only."},
            {"role": "user", "content": user}]


def _num(x) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def model_alone_lines(diary_text: str, roster: dict, week_ending: str, model: str) -> tuple[list[dict], dict] | None:
    """One model call; returns (lines as dicts, meta) or None if the price table is missing."""
    table = load_price_table()
    if table is None:
        return None
    from arvo import llm

    msgs = build_messages(diary_text, roster, week_ending, table)
    t0 = time.perf_counter()
    obj, meta = llm.chat(msgs, lines_schema([p["id"] for p in roster["participants"]]), model=model, timeout=600)
    meta = {**meta, "wall_s": round(time.perf_counter() - t0, 3)}
    lines = []
    for ln in obj.get("lines") or []:
        if not isinstance(ln, dict):
            continue
        lines.append({"participant_id": str(ln.get("participant_id", "")), "date": str(ln.get("date", ""))[:10],
                      "item_number": str(ln.get("item_number", "")).strip(), "quantity": _num(ln.get("quantity")),
                      "unit_price": _num(ln.get("unit_price")), "total": _num(ln.get("total"))})
    return lines, meta
