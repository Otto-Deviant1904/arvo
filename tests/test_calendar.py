"""Vic public holidays + business days, checked against data/vic_public_holidays.json by hand."""

import pytest

from arvo import calendar_au as cal


@pytest.mark.parametrize("iso,name", [
    ("2026-11-03", "Melbourne Cup"),
    ("2026-12-25", "Christmas Day"),
    ("2026-12-26", "Boxing Day"),               # a Saturday, still listed
    ("2026-12-28", "Boxing Day (additional day)"),
    ("2026-09-25", "Friday before the AFL Grand Final"),
    ("2027-12-27", "Christmas Day (additional day)"),
])
def test_listed_holidays(iso, name):
    assert cal.is_public_holiday(iso)
    assert cal.holiday_name(iso) == name


@pytest.mark.parametrize("iso", ["2026-10-14", "2026-11-04", "2026-12-24", "2026-12-27"])
def test_ordinary_days(iso):
    assert not cal.is_public_holiday(iso)
    assert cal.holiday_name(iso) is None


def test_undeclared_2027_grand_final_friday_is_not_a_holiday_but_warned():
    # 2027-09-24 is the last Friday in September 2027; the JSON has date null for it.
    assert not cal.is_public_holiday("2027-09-24")
    ws = cal.data_warnings(2027)
    assert len(ws) == 1 and "Friday before the AFL Grand Final" in ws[0] and "not yet declared" in ws[0]
    assert cal.data_warnings(2026) == []


def test_coverage_warning_for_year_without_data():
    assert cal.coverage_warning("2026-05-01") is None
    assert "2025" in cal.coverage_warning("2025-12-25")


def test_weekday_name():
    assert cal.weekday_name("2026-11-03") == "Tuesday"
    assert cal.weekday_name("2026-12-26") == "Saturday"


def test_add_business_days_skips_weekend_and_melbourne_cup():
    # Fri 30 Oct + 5: Mon 2, (Tue 3 Cup), Wed 4, Thu 5, Fri 6, (weekend), Mon 9
    assert cal.add_business_days("2026-10-30", 5) == "2026-11-09"


def test_add_business_days_christmas_block():
    # Thu 24 Dec + 1: Fri 25 PH, Sat 26 PH, Sun 27, Mon 28 PH (additional) -> Tue 29
    assert cal.add_business_days("2026-12-24", 1) == "2026-12-29"


def test_add_business_days_zero_and_negative():
    assert cal.add_business_days("2026-10-14", 0) == "2026-10-14"
    assert cal.add_business_days("2026-11-04", -1) == "2026-11-02"  # back over the Cup
