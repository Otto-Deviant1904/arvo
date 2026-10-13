"""Shift -> InvoiceLine. Deterministic: time bands, boundary rule, Vic public holidays, km line.

Bands (NDIS Pricing Schedule 2026-27 Part 4 Table 61, in data/ndis_prices_2026_27.json): the shift is cut
at midnight, 6am and 8pm; each piece gets a band (public holiday > Saturday > Sunday > weekday time of day,
weekday 06:00-20:00 daytime, 20:00-24:00 evening, 00:00-06:00 night). Pieces are half-open, so a shift that
ends at 20:00 is daytime only and one that starts at 20:00 is evening.
Boundary rule (s2.4(c)): a single worker's support that crosses bands is claimed WHOLE at the higher amount.
"""

from __future__ import annotations

from dataclasses import fields
from datetime import date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal

from . import calendar_au, prices
from .models import InvoiceLine, Participant, Shift

LONG_SHIFT_H = 12
SLEEPOVER_MIN_H = 8
SLEEPOVER_WARNING = "may be a sleepover support: not priced by Arvo rules, check"

_BAND_RANK = {b: i for i, b in enumerate(prices.BANDS)}  # tie-break: later band wins at equal price
_DAY_BANDS = {"public_holiday", "saturday", "sunday"}
_BOUNDARY_NAME = {time(0, 0): "midnight", time(6, 0): "6am", time(20, 0): "8pm"}
_SINGLE_BAND_RULE = {
    "weekday_daytime": "Weekday Daytime: starts at or after 6am and ends at or before 8pm on a weekday",
    "weekday_evening": "Weekday Evening: starts at or after 8pm and ends at or before midnight on a weekday",
    "weekday_night": "Weekday Night: starts before 6am and ends on the same weekday",
    "saturday": "Saturday rate: shift is on a Saturday",
    "sunday": "Sunday rate: shift is on a Sunday",
}


def q2(x) -> Decimal:
    return Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def band_label(band: str) -> str:
    return band.replace("_", " ").title()


def _parse_hhmm(s: str) -> time | None:
    """'HH:MM' -> time; '24:00' -> None meaning end of day."""
    s = s.strip()
    if s in ("24:00", "24:00:00"):
        return None
    return time.fromisoformat(s)


def shift_datetimes(d: str, start: str, end: str) -> tuple[datetime, datetime]:
    """Actual start/end. end <= start means the shift finishes the next day; end == start is zero length."""
    day = date.fromisoformat(d)
    st = _parse_hhmm(start)
    if st is None:
        raise ValueError(f"start time {start!r} is not a valid start")
    s_dt = datetime.combine(day, st)
    et = _parse_hhmm(end)
    if et is None:
        return s_dt, datetime.combine(day + timedelta(days=1), time(0, 0))
    e_dt = datetime.combine(day, et)
    if e_dt < s_dt:
        e_dt += timedelta(days=1)
    return s_dt, e_dt


def band_at(dt: datetime) -> str:
    """Band of the minute starting at dt."""
    iso = dt.date().isoformat()
    if calendar_au.is_public_holiday(iso):
        return "public_holiday"
    wd = dt.weekday()
    if wd == 5:
        return "saturday"
    if wd == 6:
        return "sunday"
    t = dt.time()
    if t < time(6, 0):
        return "weekday_night"
    if t < time(20, 0):
        return "weekday_daytime"
    return "weekday_evening"


def segments(s_dt: datetime, e_dt: datetime) -> list[tuple[datetime, datetime, str]]:
    """Cut [s_dt, e_dt) at midnight, 6am, 8pm; merge neighbours with the same band."""
    cuts = []
    day = s_dt.date()
    while datetime.combine(day, time(0, 0)) < e_dt:
        for t in (time(0, 0), time(6, 0), time(20, 0)):
            c = datetime.combine(day, t)
            if s_dt < c < e_dt:
                cuts.append(c)
        day += timedelta(days=1)
    points = [s_dt, *sorted(cuts), e_dt]
    out: list[tuple[datetime, datetime, str]] = []
    for a, b in zip(points, points[1:]):
        band = band_at(a)
        if out and out[-1][2] == band:
            out[-1] = (out[-1][0], b, band)
        else:
            out.append((a, b, band))
    return out


def _as_participants(roster) -> dict[str, Participant]:
    people = roster.get("participants", []) if isinstance(roster, dict) else list(roster or [])
    names = {f.name for f in fields(Participant)}
    out = {}
    for p in people:
        if isinstance(p, dict):
            p = Participant(**{k: v for k, v in p.items() if k in names})
        out[p.id] = p
    return out


def _as_shift(s) -> Shift:
    if isinstance(s, Shift):
        return s
    names = {f.name for f in fields(Shift)}
    return Shift(**{k: v for k, v in dict(s).items() if k in names})


def _boundary_text(segs, holiday: str | None) -> str:
    names = []
    for (_, b, band), (_, _, nxt) in zip(segs, segs[1:]):
        if band != nxt:
            n = _BOUNDARY_NAME.get(b.time(), b.strftime("%H:%M"))
            if n == "midnight" and nxt in _DAY_BANDS:
                n = f"midnight into {holiday if nxt == 'public_holiday' and holiday else band_label(nxt)}"
            if n not in names:
                names.append(n)
    return names[0] if len(names) == 1 else f"{', '.join(names[:-1])} and {names[-1]}"


def _rule_source(iso_date: str) -> str:
    if prices.is_previous_year(iso_date):
        return "NDIS PAPL 2025-26 p18"
    return "NDIS Pricing Schedule 2026-27 s2.4(c)"


def price_shift(shift: Shift, participant: Participant) -> tuple[list[InvoiceLine], list[str]]:
    """Lines for one shift of a known participant (hours line, plus km line if km > 0)."""
    where = f"{participant.id} {shift.date} {shift.start}-{shift.end}"
    warnings: list[str] = []
    try:
        s_dt, e_dt = shift_datetimes(shift.date, shift.start, shift.end)
        prices.period_for(shift.date)
    except ValueError as e:  # bad date/time, or no price data for the date (PriceError)
        return [], [f"{where}: not priced: {e}"]

    minutes = int((e_dt - s_dt).total_seconds() // 60)
    hours = Decimal(minutes) / Decimal(60)
    if minutes == 0:
        warnings.append(f"{where}: zero-length shift (start equals end); priced at 0 hours, check the times")
    elif hours > LONG_SHIFT_H:
        warnings.append(f"{where}: shift is {hours:.2f} h (over {LONG_SHIFT_H} h), check the times")
    if hours >= SLEEPOVER_MIN_H and e_dt > datetime.combine(s_dt.date() + timedelta(days=1), time(0, 0)):
        warnings.append(f"{where}: {SLEEPOVER_WARNING}")

    last_day = (e_dt - timedelta(minutes=1)).date().isoformat() if minutes else shift.date
    for day in dict.fromkeys((shift.date, last_day)):
        cw = calendar_au.coverage_warning(day)
        if cw:
            warnings.append(f"{where}: {cw}")
        warnings.extend(calendar_au.data_warnings(date.fromisoformat(day).year))  # same text every shift: deduped
    if prices.period_for(shift.date) is not prices.period_for(last_day):
        warnings.append(f"{where}: shift crosses a price-period change; priced at the prices of {shift.date}")

    segs = segments(s_dt, e_dt) if minutes else [(s_dt, e_dt, band_at(s_dt))]
    touched = list(dict.fromkeys(b for _, _, b in segs))
    support_type = participant.support_type
    try:
        options = []
        for band in touched:
            num, name, warn = prices.item_for(support_type, band)
            price, source = prices.price_for(num, shift.date)
            options.append((price, _BAND_RANK[band], band, num, name, warn, source))
    except ValueError as e:
        return [], [*warnings, f"{where}: not priced: {e}"]
    price, _, band, num, name, warn, _source = max(options)
    if warn:
        warnings.append(f"{where}: {warn}")

    priced_label = band_label(prices.band_of_item(num) or band)
    holiday = None
    if band == "public_holiday":
        ph_day = next(a for a, _, b in segs if b == "public_holiday").date().isoformat()
        holiday = calendar_au.holiday_name(ph_day)
    if len(touched) > 1:
        rule = (f"Crosses {_boundary_text(segs, holiday)}: whole shift at {priced_label} rate "
                f"({_rule_source(shift.date)})")
        if holiday:
            rule += f"; {holiday} is a Victorian public holiday"
    elif band == "public_holiday":
        rule = f"{holiday} is a Victorian public holiday: Public Holiday rate"
    else:
        rule = _SINGLE_BAND_RULE[band]
    if warn:
        rule += f" (no {band_label(band)} item for community access: priced at {priced_label})"

    qty = q2(hours)
    lines = [InvoiceLine(participant_id=participant.id, date=shift.date, item_number=num, item_name=name,
                         start=shift.start, end=shift.end, quantity=float(qty), unit="H",
                         unit_price=price, total=float(q2(qty * Decimal(str(price)))), rule=rule)]

    km = float(shift.km or 0)
    if km < 0:
        warnings.append(f"{where}: negative km ({km}) ignored")
    elif km > 0:
        t = prices.travel_km_item(support_type)
        kq = q2(km)
        lines.append(InvoiceLine(participant_id=participant.id, date=shift.date, item_number=t.item_number,
                                 item_name=t.item_name, start="", end="", quantity=float(kq), unit="km",
                                 unit_price=t.per_km_limit, total=float(q2(kq * Decimal(str(t.per_km_limit)))),
                                 rule=t.rule))
    return lines, warnings


def price_shifts(shifts, roster) -> tuple[list[InvoiceLine], list[str]]:
    """All shifts -> (invoice lines, warnings). Unknown participant: no line, a warning."""
    people = _as_participants(roster)
    lines: list[InvoiceLine] = []
    warnings: list[str] = []
    for raw in shifts:
        shift = _as_shift(raw)
        p = people.get(shift.participant_id)
        if p is None:
            warnings.append(f"{shift.participant_id or '(no participant)'} {shift.date} {shift.start}-{shift.end}: "
                            f"unknown participant_id {shift.participant_id!r}, not priced")
            continue
        ls, ws = price_shift(shift, p)
        lines.extend(ls)
        warnings.extend(w for w in ws if w not in warnings)
    return lines, warnings
