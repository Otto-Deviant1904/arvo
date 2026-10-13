"""Shared data types. Every module talks in these; keep them plain and JSON-friendly."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Literal, Optional

SupportType = Literal["self_care", "community"]
RPType = Literal["seclusion", "chemical", "mechanical", "physical", "environmental"]


@dataclass
class Participant:
    """One NDIS participant the worker supports. Lives in roster.json."""
    id: str                      # short slug, e.g. "jake"
    name: str                    # full name as it must appear on the invoice
    ndis_number: str             # 9 digits, starts with 43
    aliases: list[str]           # what the worker writes in the diary: ["Jake", "J", "Jakey"]
    support_type: SupportType    # which item family their core hours are claimed under
    plan_manager: str = ""       # who the invoice goes to
    bsp_authorised: list[str] = field(default_factory=list)  # restrictive practices authorised in their behaviour support plan, free text


@dataclass
class Shift:
    """One shift as read out of the diary by the model, after code validation."""
    participant_id: str          # must match a Participant.id ("" if the model could not match)
    date: str                    # ISO yyyy-mm-dd
    start: str                   # 24h HH:MM
    end: str                     # 24h HH:MM; may be "00:00".."06:00" on the next day if overnight
    km: float                    # provider travel km with/for the participant, 0 if none
    note: str                    # the worker's own words for this shift, verbatim from the diary
    source_quote: str = ""       # the diary span the model read the times from, verbatim
    warnings: list[str] = field(default_factory=list)  # e.g. "approximate end time '7ish'"


@dataclass
class InvoiceLine:
    participant_id: str
    date: str
    item_number: str
    item_name: str
    start: str
    end: str
    quantity: float              # hours (or km for a km line), 2 decimal places
    unit: str                    # "H" or "km"
    unit_price: float
    total: float                 # round(quantity * unit_price, 2)
    rule: str = ""               # one-line human reason, e.g. "Sunday rate: shift date is a Sunday"


@dataclass
class RPFlag:
    """A possible restrictive practice found in a shift note."""
    participant_id: str
    date: str
    rp_type: RPType
    evidence_quote: str          # verbatim sentence from the note; code rejects flags whose quote is not in the note
    harm_mentioned: bool         # injury or harm mentioned -> 24h report window instead of 5 business days
    authorised_in_bsp: bool      # matched against Participant.bsp_authorised by the model, reviewed by a human
    report_by: str = ""          # ISO datetime/date deadline computed by code
    explanation: str = ""        # one sentence, plain English


@dataclass
class RunResult:
    shifts: list[Shift]
    lines: list[InvoiceLine]
    flags: list[RPFlag]
    warnings: list[str]
    model: str
    timings: dict                # {"extract_s": .., "rp_s": .., "total_s": ..}

    def to_dict(self) -> dict:
        return asdict(self)
