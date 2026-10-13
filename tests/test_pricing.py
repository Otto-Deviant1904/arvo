"""Pricing against hand-computed figures from data/ndis_prices_2026_27.json (national column).

2026-27: daytime 73.58, evening 81.07, self-care night 82.57, Saturday 103.54, Sunday 133.50, PH 163.46.
2025-26: self-care daytime 70.23, night 78.81. Provider travel non-labour: $0.99/km.
Dates: 2026-10-14 Wed, 2026-10-16 Fri, 2026-10-17 Sat, 2026-10-18 Sun, 2026-11-03 Tue (Melbourne Cup).
"""

import pytest

from arvo import prices
from arvo.models import Shift
from arvo.pricing import price_shifts

SELF = {"weekday_daytime": "01_011_0107_1_1", "weekday_evening": "01_015_0107_1_1",
        "weekday_night": "01_002_0107_1_1", "saturday": "01_013_0107_1_1",
        "sunday": "01_014_0107_1_1", "public_holiday": "01_012_0107_1_1"}
COMM = {"weekday_daytime": "04_104_0125_6_1", "weekday_evening": "04_103_0125_6_1",
        "saturday": "04_105_0125_6_1", "sunday": "04_106_0125_6_1", "public_holiday": "04_102_0125_6_1"}


def one(roster, pid, d, start, end, km=0.0):
    lines, warnings = price_shifts([Shift(pid, d, start, end, km, "")], roster)
    return lines, warnings


def only(roster, *args):
    lines, warnings = one(roster, *args)
    assert len(lines) == 1, lines
    return lines[0], warnings


# jake/tom = community, priya/nonna = self_care in roster.example.json

def test_weekday_daytime_community(roster):
    ln, w = only(roster, "jake", "2026-10-14", "09:00", "13:00")
    assert (ln.item_number, ln.quantity, ln.unit, ln.unit_price, ln.total) == (COMM["weekday_daytime"], 4.0, "H", 73.58, 294.32)
    assert w == []


def test_crosses_8pm_whole_shift_at_evening_not_split(roster):
    ln, _ = only(roster, "priya", "2026-10-14", "15:00", "20:30")
    # 5.5 x 81.07 = 445.885 -> ROUND_HALF_UP 445.89 (float round() would give 445.88)
    assert (ln.item_number, ln.quantity, ln.unit_price, ln.total) == (SELF["weekday_evening"], 5.5, 81.07, 445.89)
    assert ln.rule.startswith("Crosses 8pm: whole shift at Weekday Evening rate")
    assert "s2.4(c)" in ln.rule


def test_starts_exactly_8pm_is_evening_only(roster):
    ln, _ = only(roster, "priya", "2026-10-14", "20:00", "23:00")
    assert (ln.item_number, ln.quantity, ln.total) == (SELF["weekday_evening"], 3.0, 243.21)
    assert "Crosses" not in ln.rule


def test_ends_exactly_8pm_is_daytime(roster):
    ln, _ = only(roster, "priya", "2026-10-14", "16:00", "20:00")
    assert (ln.item_number, ln.quantity, ln.total) == (SELF["weekday_daytime"], 4.0, 294.32)


def test_evening_to_midnight_is_evening(roster):
    ln, _ = only(roster, "priya", "2026-10-14", "20:00", "00:00")
    assert (ln.item_number, ln.quantity, ln.total) == (SELF["weekday_evening"], 4.0, 324.28)


def test_saturday(roster):
    ln, _ = only(roster, "priya", "2026-10-17", "10:00", "14:00")
    assert (ln.item_number, ln.total) == (SELF["saturday"], 414.16)


def test_sunday(roster):
    ln, _ = only(roster, "jake", "2026-10-18", "10:00", "13:00")
    assert (ln.item_number, ln.total) == (COMM["sunday"], 400.50)


def test_melbourne_cup_is_public_holiday(roster):
    ln, _ = only(roster, "jake", "2026-11-03", "10:00", "14:00")
    assert (ln.item_number, ln.unit_price, ln.total) == (COMM["public_holiday"], 163.46, 653.84)
    assert "Melbourne Cup" in ln.rule and "Victorian public holiday" in ln.rule


def test_friday_night_into_saturday_whole_shift_at_saturday(roster):
    ln, _ = only(roster, "priya", "2026-10-16", "22:00", "01:00")
    assert (ln.item_number, ln.quantity, ln.total) == (SELF["saturday"], 3.0, 310.62)
    assert "midnight into Saturday" in ln.rule


def test_early_morning_self_care_is_night(roster):
    ln, w = only(roster, "priya", "2026-10-14", "05:30", "09:00")
    # 3.5 x 82.57 = 288.995 -> 289.00
    assert (ln.item_number, ln.quantity, ln.total) == (SELF["weekday_night"], 3.5, 289.00)
    assert not any("weekday-night" in x for x in w)


def test_early_morning_community_falls_back_to_evening_with_warning(roster):
    ln, w = only(roster, "jake", "2026-10-14", "05:30", "09:00")
    # 3.5 x 81.07 = 283.745 -> 283.75
    assert (ln.item_number, ln.total) == (COMM["weekday_evening"], 283.75)
    assert any("no weekday-night item exists for community access; priced at weekday evening, "
               "check with the plan manager" in x for x in w)


def test_weekday_overnight_self_care_is_night(roster):
    ln, _ = only(roster, "priya", "2026-10-14", "22:00", "02:00")
    assert (ln.item_number, ln.quantity, ln.total) == (SELF["weekday_night"], 4.0, 330.28)


@pytest.mark.parametrize("d", ["2026-12-25", "2026-12-26", "2026-12-28"])
def test_christmas_boxing_day_and_additional_day_are_public_holidays(roster, d):
    ln, _ = only(roster, "priya", d, "10:00", "12:00")
    assert (ln.item_number, ln.total) == (SELF["public_holiday"], 326.92)


def test_christmas_eve_into_christmas_is_public_holiday_rate(roster):
    ln, _ = only(roster, "priya", "2026-12-24", "22:00", "02:00")
    assert (ln.item_number, ln.total) == (SELF["public_holiday"], 653.84)
    assert "Christmas Day" in ln.rule


def test_2026_06_30_uses_2025_26_prices(roster):
    ln, _ = only(roster, "priya", "2026-06-30", "09:00", "12:00")
    assert (ln.item_number, ln.unit_price, ln.total) == (SELF["weekday_daytime"], 70.23, 210.69)


def test_km_line_is_activity_based_transport(roster):
    lines, _ = one(roster, "jake", "2026-10-14", "09:00", "13:00", 12)
    assert len(lines) == 2
    km = lines[1]
    assert (km.item_number, km.quantity, km.unit, km.unit_price, km.total) == ("04_590_0125_6_1", 12.0, "km", 0.99, 11.88)
    assert km.item_name == "Activity Based Transport"
    assert km.rule == ("Activity Based Transport: km driven with the participant, up to $0.99/km in an unmodified "
                       "vehicle (PAPL 2025-26 p28; 2026-27 catalogue). Claimed as a dollar amount against a $1 "
                       "notional unit.")
    lines, _ = one(roster, "priya", "2026-10-14", "09:00", "13:00", 12)  # self-care: same item
    assert (lines[1].item_number, lines[1].total) == ("04_590_0125_6_1", 11.88)


def test_quantity_rounding_minutes(roster):
    ln, _ = only(roster, "priya", "2026-10-14", "09:00", "09:40")
    assert ln.quantity == 0.67 and ln.total == 49.30  # 0.67 x 73.58 = 49.2986


def test_unknown_participant(roster):
    lines, w = one(roster, "ghost", "2026-10-14", "09:00", "10:00", 5)
    assert lines == [] and any("unknown participant_id 'ghost'" in x for x in w)


def test_long_and_sleepover_warnings_still_priced(roster):
    ln, w = only(roster, "priya", "2026-10-14", "18:00", "07:00")
    assert (ln.item_number, ln.quantity, ln.total) == (SELF["weekday_night"], 13.0, 1073.41)
    assert any("over 12 h" in x for x in w)
    assert any("may be a sleepover support: not priced by Arvo rules, check" in x for x in w)


def test_eight_hours_ending_at_midnight_is_not_sleepover(roster):
    _, w = only(roster, "priya", "2026-10-14", "16:00", "00:00")
    assert not any("sleepover" in x for x in w)


def test_zero_length_warning_still_priced(roster):
    ln, w = only(roster, "priya", "2026-10-14", "09:00", "09:00")
    assert ln.quantity == 0.0 and ln.total == 0.0
    assert any("zero-length" in x for x in w)


def test_date_before_price_data_is_not_priced(roster):
    lines, w = one(roster, "priya", "2025-06-30", "09:00", "10:00")
    assert lines == [] and any("2025-07-01" in x for x in w)


def test_roster_with_participant_objects_and_dict_shifts(roster):
    from arvo.models import Participant
    people = [Participant(**p) for p in roster["participants"]]
    lines, _ = price_shifts([{"participant_id": "tom", "date": "2026-10-14", "start": "09:00", "end": "10:00",
                              "km": 0, "note": ""}], {"participants": people})
    assert lines[0].total == 73.58


# ---- prices.py directly

def test_price_for_periods_and_errors():
    assert prices.price_for(SELF["weekday_daytime"], "2026-10-14")[0] == 73.58
    assert "2026-09-24" in prices.price_for(SELF["weekday_daytime"], "2026-10-14")[1]
    assert "2026-07-01" in prices.price_for(SELF["weekday_daytime"], "2026-08-01")[1]
    assert prices.price_for(COMM["sunday"], "2025-07-01")[0] == 127.43
    with pytest.raises(prices.PriceError, match="2025-07-01"):
        prices.price_for(SELF["weekday_daytime"], "2025-06-30")
    with pytest.raises(prices.PriceError, match="not found"):
        prices.price_for("99_999_9999_9_9", "2026-10-14")


def test_item_for():
    assert prices.item_for("self_care", "sunday") == (SELF["sunday"],
                                                      "Assistance With Self-Care Activities - Standard - Sunday", None)
    num, name, warn = prices.item_for("community", "weekday_night")
    assert num == COMM["weekday_evening"] and name.endswith("Weekday Evening")
    assert warn == prices.COMMUNITY_NIGHT_WARNING
    with pytest.raises(prices.PriceError):
        prices.item_for("gardening", "sunday")


def test_activity_transport_item():
    t = prices.activity_transport_item()
    assert (t.item_number, t.per_km_limit) == ("04_590_0125_6_1", 0.99)


def test_travel_km_item():
    t = prices.travel_km_item("community")
    assert (t.item_number, t.per_km_limit) == ("04_799_0125_6_1", 0.99)
    assert "carried forward" in t.rule
