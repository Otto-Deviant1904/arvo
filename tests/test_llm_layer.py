"""LLM layer: llm.chat, extract, rp, pipeline, cli. Fake transport only, no network."""

from __future__ import annotations

import json
import sys
import types

import pytest

from arvo import llm
from arvo.extract import (dates_from_day_written, extract_shifts, find_verbatim, match_alias,
                          reconcile_times, week_window)
from arvo.models import Shift
from arvo.rp import screen_notes

WEEK = "2026-11-08"  # Sunday; window Mon 2 Nov .. Sun 8 Nov, Tue 3 Nov = Melbourne Cup day

DIARY = """Tues - Cup day! Jake 3 till 8:30ish, Bunnings + footy, 12km
Wed 4th Priya 9-1. Gave PRN lorazepam 0.5mg as per plan, distress 5.
Thurs Jakey 10am-2pm. Locked the pantry so he would stop snacking.
"""


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
    assert s.note == "Bunnings + footy, 12km" and warns == []


def test_week_window_and_day_written():
    w = week_window(WEEK)
    assert [d.isoformat() for d in (w[0], w[-1])] == ["2026-11-02", "2026-11-08"]
    assert [d.isoformat() for d in dates_from_day_written("Tues", w)] == ["2026-11-03"]
    assert [d.isoformat() for d in dates_from_day_written("3/11", w)] == ["2026-11-03"]  # DD/MM
    assert [d.isoformat() for d in dates_from_day_written("the 7th", w)] == ["2026-11-07"]
    assert [d.isoformat() for d in dates_from_day_written("Cup day", w)] == ["2026-11-03"]
    assert dates_from_day_written("arvo", w) == []


def test_extract_date_outside_window_dropped(fake_llm, roster):
    fake_llm.queue({"shifts": [item(day_written="", date="2026-11-10"), item(day_written="", date="11/03/2026"),
                               item(day_written="", date="03/11/2026")]})
    shifts, warns, _ = extract_shifts(DIARY, roster, WEEK)
    assert [s.date for s in shifts] == ["2026-11-03"]  # numeric dates are DD/MM
    assert sum("outside the week 2026-11-02..2026-11-08" in w for w in warns) == 2


def test_extract_day_written_overrides_model_date(fake_llm, roster):
    fake_llm.queue({"shifts": [item(day_written="Tues", date="2026-11-04")]})
    shifts, _, _ = extract_shifts(DIARY, roster, WEEK)
    assert shifts[0].date == "2026-11-03"
    assert any("date set to 2026-11-03 from 'Tues'" in w for w in shifts[0].warnings)


def test_extract_alias_fallback(fake_llm, roster):
    fake_llm.queue({"shifts": [
        item(participant_id="unknown", name_written="Jakey"),
        item(participant_id="tom", name_written="Pri", date="2026-11-04", day_written="Wed"),
        item(participant_id="unknown", name_written="Bob", date="2026-11-05", day_written="Thu"),
    ]})
    shifts, warns, _ = extract_shifts(DIARY, roster, WEEK)
    assert [s.participant_id for s in shifts] == ["jake", "priya", ""]
    assert any("alias of priya" in w for w in shifts[1].warnings)
    assert any("unknown participant 'Bob'" in w for w in warns)
    assert match_alias("T.O.", [p for p in __import__("arvo.extract").extract.as_participants(roster)]) == "tom"


def test_extract_approximate_time_warning(fake_llm, roster):
    fake_llm.queue({"shifts": [item(), item(source_quote="Jakey 10am-2pm", times_written="10am-2pm",
                                            day_written="Thurs", date="2026-11-05", start="10:00",
                                            end="14:00", km=0, note="")]})
    shifts, _, _ = extract_shifts(DIARY, roster, WEEK)
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
    shifts, warns, _ = extract_shifts(DIARY, roster, WEEK)
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
    shifts, _, _ = extract_shifts(DIARY, roster, WEEK)
    w = " | ".join(shifts[0].warnings)
    assert "not word-for-word" in w and "no such km figure" in w and shifts[0].km == 0


def test_extract_image_path_sends_image(fake_llm, roster, tmp_path):
    img = tmp_path / "page.png"
    img.write_bytes(b"img")
    fake_llm.queue({"shifts": [item(note="Bunings & footy")]})
    shifts, warns, _ = extract_shifts("", roster, WEEK, image_path=str(img))
    msg = fake_llm.calls[0]["messages"][-1]
    assert msg["images"] and "handwritten" in msg["content"]
    assert len(shifts) == 1 and any("photo input" in w for w in warns)


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
    assert len(res.shifts) == 2 and len(res.flags) == 1 and res.flags[0].participant_id == "jake"
    assert "priced elsewhere" in res.warnings
    assert set(res.timings) >= {"extract_s", "pricing_s", "rp_s", "total_s"} and res.timings["rp_calls"] == 2
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
    assert rc == 0 and "[RED] 2026-11-05 jake: environmental" in out and "SHIFTS (2)" in out
    assert json.loads(out_json.read_text())["flags"][0]["rp_type"] == "environmental"


def test_cli_serve_passes_kwargs(monkeypatch):
    from arvo import cli
    got = {}
    fake = types.ModuleType("arvo.server")
    fake.main = lambda **kw: got.update(kw)
    monkeypatch.setitem(sys.modules, "arvo.server", fake)
    assert cli.main(["serve", "--port", "9000"]) == 0 and got == {"port": 9000}
