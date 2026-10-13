"""Victorian public holidays and business-day arithmetic, from data/vic_public_holidays.json.

A holiday listed with a null date (not yet declared, e.g. the 2027 Friday before the AFL Grand
Final) is treated as NOT a holiday; `data_warnings()` says so. Years with no data in the file are
not checked at all; `coverage_warning(iso_date)` says so, and pricing surfaces it.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from functools import cache
from pathlib import Path

DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "vic_public_holidays.json"


@cache
def _load() -> tuple[dict[str, str], frozenset[int], tuple[tuple[int, str], ...]]:
    raw = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    holidays: dict[str, str] = {}
    years: set[int] = set()
    warnings: list[tuple[int, str]] = []
    for key, entries in raw.items():
        if not key.isdigit():
            continue
        years.add(int(key))
        for e in entries:
            if e.get("date"):
                holidays[e["date"]] = e["name"]
            else:
                warnings.append((int(key), f"{e.get('name', 'unnamed holiday')} {key}: not yet declared in "
                                 f"{DATA_PATH.name}; treated as an ordinary day"))
    return holidays, frozenset(years), tuple(warnings)


def _d(iso_date: str) -> date:
    return date.fromisoformat(iso_date)


def is_public_holiday(iso_date: str) -> bool:
    _d(iso_date)  # validate
    return iso_date in _load()[0]


def holiday_name(iso_date: str) -> str | None:
    _d(iso_date)
    return _load()[0].get(iso_date)


def data_warnings(year: int | None = None) -> list[str]:
    """Holidays in the file whose date is not declared yet (all years, or one year)."""
    return [msg for y, msg in _load()[2] if year is None or y == year]


def covered_years() -> frozenset[int]:
    return _load()[1]


def coverage_warning(iso_date: str) -> str | None:
    """A warning if the holiday file has no data for this date's year (holidays cannot be checked)."""
    y = _d(iso_date).year
    if y in covered_years():
        return None
    return (f"no Victorian public-holiday data for {y} in {DATA_PATH.name}; "
            f"public holidays not checked for {iso_date}")


def weekday_name(iso_date: str) -> str:
    return _d(iso_date).strftime("%A")


def is_business_day(iso_date: str) -> bool:
    return _d(iso_date).weekday() < 5 and not is_public_holiday(iso_date)


def add_business_days(iso_date: str, n: int) -> str:
    """Move n business days from iso_date (skip Sat, Sun, Vic public holidays). n=0 returns iso_date."""
    d = _d(iso_date)
    step = 1 if n >= 0 else -1
    left = abs(n)
    while left:
        d += timedelta(days=step)
        if is_business_day(d.isoformat()):
            left -= 1
    return d.isoformat()
