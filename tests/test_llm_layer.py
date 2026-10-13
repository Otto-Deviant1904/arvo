"""LLM layer: llm.chat, extract, rp, pipeline, cli. Fake transport only, no network."""

from __future__ import annotations

import json
import sys
import types

import pytest

from arvo import llm
from arvo.extract import (dates_from_day_written, extract_shifts, find_verbatim, km_figures, match_alias,
                          parse_written_times, reconcile_times, time_ranges, week_window)
from arvo.models import Shift
from arvo.rp import screen_notes

WEEK = "2026-11-08"  # Sunday; window Mon 2 Nov .. Sun 8 Nov, Tue 3 Nov = Melbourne Cup day

DIARY = """Tues - Cup day! Jake 3 till 8:30ish, Bunnings + footy, 12km
Wed 4th Priya 9-1. Gave PRN lorazepam 0.5mg as per plan, distress 5.
Thurs Jakey 10am-2pm. Locked the pantry so he would stop snacking.
"""
ONE = "Tues - Cup day! Jake 3 till 8:30ish, Bunnings + footy, 12km\n"


def item(**kw):
    base = {"day_written": "Tues", "date": "2026-11-03", "source_quote": "Jake 3 till 8:30ish",
            "name_written": "Jake", "participant_id": "jake", "times_written": "3 till 8:30ish",
            "start": "15:00", "end": "20:30", "km": 12, "note": "Bunnings + footy, 12km"}
    base.update(kw)
    return base


def no_calendar(monkeypatch):
    monkeypatch.setitem(sys.modules, "arvo.calendar_au", None)  # import -> ImportError


# ----------------------------------------------------------------------------- llm.chat

def test_chat_payload_shape(fake_llm, tmp_path):
    img = tmp_path / "d.png"
    img.write_bytes(b"\x89PNGfake")
    schema = {"type": "object", "properties": {"x": {"type": "integer"}}, "required": ["x"]}
    fake_llm.queue({"x": 1})
    obj, meta = llm.chat([{"role": "system", "content": "s"}, {"role": "user", "content": "u"}],
                         schema, images=[str(img)])
    p = fake_llm.calls[0]
    assert obj == {"x": 1}
    assert p["model"] == "gemma4:e4b" and p["stream"] is False and p["think"] is False
    assert p["options"]["temperature"] == 0 and p["format"] == schema
    assert p["messages"][1]["images"] == ["iVBOR2Zha2U="] and "images" not in p["messages"][0]
    assert set(meta) >= {"model", "total_s", "load_s", "prompt_tokens", "eval_tokens"}
    assert meta["load_s"] == 0.1 and meta["prompt_tokens"] == 50 and meta["eval_tokens"] == 20


def test_chat_retries_once_then_fails(fake_llm):
    fake_llm.queue("not json {", {"ok": True})
    obj, meta = llm.chat([{"role": "user", "content": "u"}], {"type": "object"})
    assert obj == {"ok": True} and meta["attempts"] == 2
    assert fake_llm.calls[1]["messages"][-1]["content"] == llm.RETRY_NUDGE
    fake_llm.queue("nope", "[1, 2]")
    with pytest.raises(llm.LLMError, match="invalid JSON twice"):
        llm.chat([{"role": "user", "content": "u"}], {"type": "object"})


# ----------------------------------------------------------------------------- extract

def test_extract_prompt_and_schema(fake_llm, roster):
    fake_llm.queue({"shifts": [item()]})
    shifts, warns, meta = extract_shifts(DIARY, roster, WEEK, "gemma4:e4b")
    assert len(fake_llm.calls) == 1
    p = fake_llm.calls[0]
    text = fake_llm.user_text()
    assert "Tuesday the 3rd (03 Nov) = 2026-11-03 (Melbourne Cup day)" in text
    assert "Monday the 2nd (02 Nov) = 2026-11-02" in text and "Sunday the 8th (08 Nov) = 2026-11-08" in text
    assert "Jake, J, Jakey, Jake Morrison -> jake" in text and "Lorazepam" not in text
    assert DIARY.strip() in text and '"3 till 8:30" = 15:00 to 20:30' in text
    items = p["format"]["properties"]["shifts"]["items"]
    assert set(items["required"]) == set(items["properties"])
    assert items["properties"]["participant_id"]["enum"] == ["jake", "priya", "tom", "nonna", "unknown"]
    s = shifts[0]
    assert (s.participant_id, s.date, s.start, s.end, s.km) == ("jake", "2026-11-03", "15:00", "20:30", 12)
    assert s.note == "Bunnings + footy, 12km" and s.source_quote == "Jake 3 till 8:30ish"
    # the two lines the fake model skipped are read by code, with a warning each
    assert [(x.participant_id, x.date, x.start, x.end) for x in shifts[1:]] == [
        ("priya", "2026-11-04", "09:00", "13:00"), ("jake", "2026-11-05", "10:00", "14:00")]
    assert len(warns) == 2 and all("added by code" in w for w in warns)


def test_week_window_and_day_written():
    w = week_window(WEEK)
    assert [d.isoformat() for d in (w[0], w[-1])] == ["2026-11-02", "2026-11-08"]
    assert [d.isoformat() for d in dates_from_day_written("Tues", w)] == ["2026-11-03"]
    assert [d.isoformat() for d in dates_from_day_written("3/11", w)] == ["2026-11-03"]  # DD/MM
    assert [d.isoformat() for d in dates_from_day_written("the 7th", w)] == ["2026-11-07"]
    assert [d.isoformat() for d in dates_from_day_written("Cup day", w)] == ["2026-11-03"]
    assert dates_from_day_written("Mnday", w)[0].isoformat() == "2026-11-02"
    assert dates_from_day_written("today", w) == []
    for words in ("5 Nov -", "Nov 5th", "Thurs 5th of November", "thrusday", "[memo recorded Thu 2026-11-05]"):
        assert [d.isoformat() for d in dates_from_day_written(words, w)] == ["2026-11-05"], words
    assert dates_from_day_written("arvo", w) == []


def test_extract_date_outside_window_dropped(fake_llm, roster):
    fake_llm.queue({"shifts": [item(day_written="", date="2026-11-10"), item(day_written="", date="11/03/2026"),
                               item(day_written="", date="03/11/2026")]})
    shifts, warns, _ = extract_shifts("Jake 3 till 8:30ish\n", roster, WEEK)
    assert [s.date for s in shifts] == ["2026-11-03"]  # numeric dates are DD/MM
    assert sum("outside the week 2026-11-02..2026-11-08" in w for w in warns) == 2


def test_extract_day_written_overrides_model_date(fake_llm, roster):
    fake_llm.queue({"shifts": [item(day_written="Tues", date="2026-11-04")]})
    shifts, _, _ = extract_shifts(ONE, roster, WEEK)
    assert shifts[0].date == "2026-11-03"
    assert any("date set to 2026-11-03 from the diary's 'Tues - Cup day!" in w for w in shifts[0].warnings)
    # with no day in the diary text, the model's day_written still beats its date
    fake_llm.queue({"shifts": [item(day_written="Tues", date="2026-11-04")]})
    shifts, _, _ = extract_shifts("Jake 3 till 8:30ish\n", roster, WEEK)
    assert shifts[0].date == "2026-11-03" and any("from 'Tues'" in w for w in shifts[0].warnings)


def test_extract_alias_fallback(fake_llm, roster):
    fake_llm.queue({"shifts": [
        item(participant_id="unknown", name_written="Jakey"),
        item(participant_id="tom", name_written="Pri", date="2026-11-04", day_written="Wed"),
        item(participant_id="unknown", name_written="Bob", date="2026-11-05", day_written="Thu"),
    ]})
    shifts, warns, _ = extract_shifts("Tues Jakey 3 till 8:30ish\nWed Pri 3 till 8:30ish\nThu Bob 3 till 8:30ish",
                                      roster, WEEK)
    assert [s.participant_id for s in shifts] == ["jake", "priya", ""]
    assert any("alias of priya" in w for w in shifts[1].warnings)
    assert any("unknown participant 'Bob'" in w for w in warns)
    assert match_alias("T.O.", [p for p in __import__("arvo.extract").extract.as_participants(roster)]) == "tom"


def test_extract_approximate_time_warning(fake_llm, roster):
    fake_llm.queue({"shifts": [item(), item(source_quote="Jakey 10am-2pm", times_written="10am-2pm",
                                            day_written="Thurs", date="2026-11-05", start="10:00",
                                            end="14:00", km=0, note="")]})
    shifts, _, _ = extract_shifts(ONE + "Thurs Jakey 10am-2pm\n", roster, WEEK)
    assert any("approximate time in '3 till 8:30ish'" in w for w in shifts[0].warnings)
    assert not any("approximate" in w for w in shifts[1].warnings)


def test_extract_time_rules(fake_llm, roster):
    fake_llm.queue({"shifts": [
        item(start="15:00", end="08:30"),                                    # ambiguous end -> +12h
        item(day_written="Thurs", date="2026-11-05", times_written="10am-2pm", source_quote="Jakey 10am-2pm",
             start="10:00", end="02:00", km=0, note=""),                     # explicit pm wins
        item(day_written="Sat", date="2026-11-07", times_written="10pm till 6:30am",
             source_quote="Jake 10pm till 6:30am", start="22:00", end="06:30", km=0, note=""),  # overnight
        item(day_written="Fri", date="2026-11-06", start="3pm", end="nonsense", km=0, note=""),
    ]})
    text = ONE + "Thurs Jakey 10am-2pm\nSat Jake 10pm till 6:30am\n"
    shifts, warns, _ = extract_shifts(text, roster, WEEK)
    assert [(s.start, s.end) for s in shifts] == [("15:00", "20:30"), ("10:00", "14:00"), ("22:00", "06:30")]
    assert any("overnight" in w for w in shifts[2].warnings)
    assert any("times not HH:MM" in w for w in warns)
    assert reconcile_times("half 3 - 7ish", "15:30", "19:00") == ("15:30", "19:00", [])


def test_extract_note_widened_to_diary_line(fake_llm, roster):
    text = "Mon - Tom 9:30-1:30, shopping at Northland, 18km. All good.\nTues Jake 3-5\nlocked pantry\n"
    fake_llm.queue({"shifts": [
        item(day_written="Mon", date="2026-11-02", name_written="Tom", participant_id="tom",
             source_quote="Tom 9:30-1:30", times_written="9:30-1:30", start="09:30", end="13:30",
             km=18, note="All good."),
        item(source_quote="Jake 3-5", times_written="3-5", start="15:00", end="17:00", km=0, note=""),
    ]})
    shifts, _, _ = extract_shifts(text, roster, WEEK)
    assert shifts[0].note == "shopping at Northland, 18km. All good." and shifts[0].warnings == []
    assert shifts[1].note == ""  # next line is not glued onto a shift the model left empty


def test_extract_note_and_km_checks(fake_llm, roster):
    fake_llm.queue({"shifts": [item(note="Went to Bunnings and the footy", km=30)]})
    shifts, _, _ = extract_shifts(ONE, roster, WEEK)
    w = " | ".join(shifts[0].warnings)
    assert "not word-for-word" in w and "km set to 12 from the diary (model said 30)" in w and shifts[0].km == 12
    fake_llm.queue({"shifts": [item(note="", km=30)]})
    shifts, _, _ = extract_shifts("Tues Jake 3 till 8:30ish\n", roster, WEEK)
    assert "no such km figure" in " | ".join(shifts[0].warnings) and shifts[0].km == 0


def test_extract_image_path_sends_image(fake_llm, roster, tmp_path):
    img = tmp_path / "page.png"
    img.write_bytes(b"img")
    fake_llm.queue({"shifts": [item(note="Bunings & footy")]})
    shifts, warns, _ = extract_shifts("", roster, WEEK, image_path=str(img))
    msg = fake_llm.calls[0]["messages"][-1]
    assert msg["images"] and "handwritten" in msg["content"]
    assert len(shifts) == 1 and any("photo input" in w for w in warns)


def test_km_figures_either_order():
    assert km_figures("hair km 11") == [11.0] and km_figures("Jake 12:30 til 3:30PM km 29") == [29.0]
    assert km_figures("library 8kms, 3 kms back, 0km, kms: 4, drove 9km") == [8.0, 3.0, 0.0, 4.0, 9.0]
    assert km_figures("check km for Tom?? no km") == []
    # km figures, ordinals and d/m dates are not times
    assert parse_written_times("Wed 4th 21/10 Pri 3-5 km 11 drove 9km") == [(3, 0, False), (5, 0, False)]
    assert parse_written_times("[memo recorded Tue 2026-11-03] 3/11/26 one to one") == []
    assert time_ranges("1-1 support") == []


def test_extract_km_unit_first_kept_and_filled(fake_llm, roster):
    text = "Wed - Pri 10-2 km 11, shopping\nThu Tom 9-1 footy kms 14\n"
    fake_llm.queue({"shifts": [
        item(day_written="Wed", date="2026-11-04", name_written="Pri", participant_id="priya",
             times_written="10-2", start="10:00", end="14:00", km=11, note="shopping"),
        item(day_written="Thu", date="2026-11-05", name_written="Tom", participant_id="tom",
             times_written="9-1", start="09:00", end="13:00", km=0, note="footy"),
    ]})
    shifts, _, _ = extract_shifts(text, roster, WEEK)
    assert [s.km for s in shifts] == [11, 14]
    assert any("km set to 14 from the diary (model said 0)" in w for w in shifts[1].warnings)


def test_extract_splits_two_blocks_on_one_line(fake_llm, roster):
    text = "Fri - Rosa 9-11am, shopping, then back half past 3-5:30 tea + meds 6km\n"
    merged = item(day_written="Fri", date="2026-11-06", name_written="Rosa", participant_id="nonna",
                  times_written="9-11am", start="09:00", end="17:30", km=6, note="shopping, then back")
    for model_item in (merged, {**merged, "times_written": "9-11am, then back half past 3-5:30"}):
        fake_llm.queue({"shifts": [model_item]})
        shifts, warns, _ = extract_shifts(text, roster, WEEK)
        assert [(s.start, s.end) for s in shifts] == [("09:00", "11:00"), ("15:30", "17:30")]
        assert shifts[0].note == "shopping, then back" and shifts[1].note == "tea + meds 6km"
        assert all(any(w.startswith("split:") for w in s.warnings) for s in shifts)
    # the model listed only the first block: code adds the second, same person and day
    fake_llm.queue({"shifts": [{**merged, "end": "11:00"}]})
    shifts, warns, _ = extract_shifts(text, roster, WEEK)
    assert [(s.participant_id, s.date, s.start, s.end) for s in shifts] == [
        ("nonna", "2026-11-06", "09:00", "11:00"), ("nonna", "2026-11-06", "15:30", "17:30")]


def test_extract_date_from_diary_headings(fake_llm, roster):
    text = ("wk ending 8/11\nMONDAY\nT.O. 9-11 swim\n~ Wed 4/11 ~\n* Pri 10am till quarter to 1\n"
            "    she was tired today\n- Rosa half 10 to 2:30\nTuseday: 08:00-09:30 Jake\n")
    fake_llm.queue({"shifts": [
        item(day_written="MONDAY", date="2026-11-02", name_written="T.O.", participant_id="tom",
             times_written="9-11", start="09:00", end="11:00", km=0, note="swim"),
        item(day_written="MONDAY", date="2026-11-02", name_written="Pri", participant_id="priya",
             times_written="10am till quarter to 1", start="10:00", end="12:45", km=0, note=""),
        item(day_written="MONDAY", date="2026-11-08", name_written="Rosa", participant_id="nonna",
             times_written="half 10 to 2:30", start="10:30", end="14:30", km=0, note=""),
        item(day_written="Tuseday", date="2026-11-08", name_written="Jake", participant_id="jake",
             times_written="08:00-09:30", start="08:00", end="09:30", km=0, note=""),
    ]})
    shifts, _, _ = extract_shifts(text, roster, WEEK)
    got = {(s.participant_id, s.date) for s in shifts}
    assert got == {("tom", "2026-11-02"), ("priya", "2026-11-04"), ("nonna", "2026-11-04"), ("jake", "2026-11-03")}
    # a day the code cannot place on the shift's own line: keep the model's date, never borrow from above
    fake_llm.queue({"shifts": [item(day_written="", date="2026-11-05", times_written="3 till 8:30ish")]})
    shifts, _, _ = extract_shifts("Wed\nJake 9-11\nyesterday - Jake 3 till 8:30ish\n", roster, WEEK)
    assert any((s.date, s.start) == ("2026-11-05", "15:00") for s in shifts)


def test_extract_recovers_skipped_line_but_not_cancelled_or_note_times(fake_llm, roster):
    text = ("Tues Jake 1-5, movies 2-4\nThu Tom 3-5 cancelled, he was sick\n"
            "forgot one - Mon - Rosa 8\u20139:30, shower, 0km\nSun Pri 2-4 (3km) gym class. Later I cancelled her spot\n")
    fake_llm.queue({"shifts": [item(day_written="Tues", name_written="Jake", times_written="1-5",
                                    start="13:00", end="17:00", km=0, note="movies 2-4")]})
    shifts, warns, _ = extract_shifts(text, roster, WEEK)
    assert [(s.participant_id, s.date, s.start, s.end, s.km) for s in shifts] == [
        ("nonna", "2026-11-02", "08:00", "09:30", 0), ("jake", "2026-11-03", "13:00", "17:00", 0),
        ("priya", "2026-11-08", "14:00", "16:00", 3)]
    assert "added by code" in shifts[0].warnings[0] and len(warns) == 2
    assert time_ranges("half past 4\u20136:30")[0][2:] == ((4, 30, False), (6, 30, False))


# ----------------------------------------------------------------------------- rp

def _shift(note, pid="jake", d="2026-11-05"):
    return Shift(participant_id=pid, date=d, start="10:00", end="14:00", km=0, note=note)


def test_rp_prompt_shape_and_skips_empty(fake_llm, roster):
    fake_llm.queue({"flags": []})
    flags, meta = screen_notes([_shift(""), _shift("12km"), _shift("Gave PRN lorazepam as per plan.", "priya")],
                               roster, "gemma4:e4b")
    assert flags == [] and meta["calls"] == 1 and meta["skipped"] == 2
    text = fake_llm.user_text()
    for must in ("seclusion", "chemical", "mechanical", "physical", "environmental",
                 "offering choices", "chose to go to their room", "cross a road",
                 "PRN lorazepam 0.5mg as per behaviour support plan", "Gave PRN lorazepam as per plan.",
                 "STILL a restrictive practice"):
        assert must in text
    assert "Webster" not in text  # eval hard-negative phrasing stays out of the prompt
    schema = fake_llm.calls[0]["format"]["properties"]["flags"]["items"]
    assert schema["properties"]["rp_type"]["enum"] == ["seclusion", "chemical", "mechanical",
                                                        "physical", "environmental"]


def test_rp_rejects_non_verbatim_quote(fake_llm, roster, monkeypatch):
    no_calendar(monkeypatch)
    note = "Thurs good day. Locked the pantry so he’d stop   snacking. Offered him a choice."
    fake_llm.queue({"flags": [
        {"evidence_quote": "locked the pantry so he'd stop snacking", "explanation": "x",
         "rp_type": "environmental", "harm_mentioned": False, "authorised_in_bsp": True},
        {"evidence_quote": "He was held in his room", "explanation": "y",
         "rp_type": "seclusion", "harm_mentioned": False, "authorised_in_bsp": False},
    ]})
    flags, meta = screen_notes([_shift(note)], roster, "gemma4:e4b")
    assert len(flags) == 1
    f = flags[0]
    assert f.rp_type == "environmental" and f.evidence_quote == "Locked the pantry so he’d stop   snacking"
    assert f.authorised_in_bsp is False  # jake has nothing authorised: code overrides the model
    assert f.report_by == ""  # calendar_au not importable
    assert any("model quote not found in note" in w for w in meta["warnings"])


def test_rp_deadlines(fake_llm, roster, monkeypatch):
    cal = types.ModuleType("arvo.calendar_au")
    cal.add_business_days = lambda iso, n: f"{iso}+{n}bd"
    monkeypatch.setitem(sys.modules, "arvo.calendar_au", cal)
    note = "Pinned his wrists to stop him hitting. He has a bruise on his arm."
    fake_llm.queue(
        {"flags": [{"evidence_quote": "Pinned his wrists to stop him hitting.", "explanation": "e",
                    "rp_type": "physical", "harm_mentioned": True, "authorised_in_bsp": False}]},
        {"flags": [{"evidence_quote": "pinned his wrists", "explanation": "e",
                    "rp_type": "physical", "harm_mentioned": False, "authorised_in_bsp": False},
                   {"evidence_quote": "pinned his wrists", "explanation": "e",
                    "rp_type": "restraint", "harm_mentioned": False, "authorised_in_bsp": False}]},
    )
    flags, meta = screen_notes([_shift(note), _shift(note, d="2026-11-06")], roster)
    assert [f.report_by for f in flags] == ["within 24 hours of 2026-11-05", "2026-11-06+5bd"]
    assert any("unknown rp_type" in w for w in meta["warnings"])


def test_rp_authorised_prn_flagged_without_deadline(fake_llm, roster, monkeypatch):
    cal = types.ModuleType("arvo.calendar_au")
    cal.add_business_days = lambda iso, n: "2026-11-11"
    monkeypatch.setitem(sys.modules, "arvo.calendar_au", cal)
    note = "Distress 5. Gave PRN lorazepam 0.5mg as per plan at 11:15."
    fake_llm.queue({"flags": [{"evidence_quote": "Gave PRN lorazepam 0.5mg as per plan at 11:15.",
                               "explanation": "e", "rp_type": "chemical", "harm_mentioned": False,
                               "authorised_in_bsp": True}]})
    flags, _ = screen_notes([_shift(note, "priya", "2026-11-04")], roster)
    assert flags[0].authorised_in_bsp is True and flags[0].report_by == ""


def test_find_verbatim_normalisation():
    assert find_verbatim('"Locked  the PANTRY."', "ok. locked the pantry. bye") == "locked the pantry"
    assert find_verbatim("locked the fridge", "locked the pantry") is None


# ----------------------------------------------------------------------------- pipeline + cli

def _router(payload):
    if "shifts" in payload["format"]["properties"]:
        return {"shifts": [item(), item(day_written="Thurs", date="2026-11-05", name_written="Jakey",
                                        source_quote="Jakey 10am-2pm", times_written="10am-2pm",
                                        start="10:00", end="14:00", km=0,
                                        note="Locked the pantry so he would stop snacking.")]}
    if "pantry" in payload["messages"][-1]["content"]:
        return {"flags": [{"evidence_quote": "Locked the pantry so he would stop snacking.",
                           "explanation": "Access to food was restricted.", "rp_type": "environmental",
                           "harm_mentioned": False, "authorised_in_bsp": False}]}
    return {"flags": []}


def test_pipeline_run(fake_llm, roster, monkeypatch):
    from arvo import pipeline
    no_calendar(monkeypatch)
    monkeypatch.setattr(pipeline, "_price", lambda shifts, roster: ([], ["priced elsewhere"]))
    fake_llm.handler = _router
    res = pipeline.run(DIARY, roster, WEEK)
    assert len(res.shifts) == 3 and len(res.flags) == 1 and res.flags[0].participant_id == "jake"
    assert "priced elsewhere" in res.warnings
    assert set(res.timings) >= {"extract_s", "pricing_s", "rp_s", "total_s"} and res.timings["rp_calls"] == 3
    json.dumps(res.to_dict())


def test_cli_process(fake_llm, monkeypatch, tmp_path, capsys):
    from arvo import cli, pipeline
    no_calendar(monkeypatch)
    monkeypatch.setattr(pipeline, "_price", lambda shifts, roster: ([], []))
    fake_llm.handler = _router
    diary = tmp_path / "week.txt"
    diary.write_text(DIARY)
    out_json = tmp_path / "out.json"
    rc = cli.main(["process", str(diary), "--week-ending", WEEK, "--json", str(out_json)])
    out = capsys.readouterr().out
    assert rc == 0 and "[RED] 2026-11-05 jake: environmental" in out and "SHIFTS (3)" in out
    assert json.loads(out_json.read_text())["flags"][0]["rp_type"] == "environmental"


def test_cli_serve_passes_kwargs(monkeypatch):
    from arvo import cli
    got = {}
    fake = types.ModuleType("arvo.server")
    fake.main = lambda **kw: got.update(kw)
    monkeypatch.setitem(sys.modules, "arvo.server", fake)
    assert cli.main(["serve", "--port", "9000"]) == 0 and got == {"port": 9000}
