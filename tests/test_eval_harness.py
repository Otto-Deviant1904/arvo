"""Eval harness tests: deterministic fixtures, sane gold, correct metrics. No network, no Ollama."""

from __future__ import annotations

import json
import re
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval"))
sys.path.insert(0, str(ROOT))

import baselines  # noqa: E402
import gen_fixtures as gf  # noqa: E402
import run_eval as ev  # noqa: E402

FIX = ROOT / "eval" / "fixtures"
HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def golds() -> list[dict]:
    out = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(FIX.glob("week*.gold.json"))]
    assert out, "no fixtures: run eval/gen_fixtures.py"
    return out


# ------------------------------------------------------------------------------- generator
def test_generator_is_deterministic(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    gf.generate(a, images=False)
    gf.generate(b, images=False)
    fa = sorted(p.name for p in a.iterdir())
    assert fa == sorted(p.name for p in b.iterdir())
    assert len([f for f in fa if f.endswith(".txt")]) == gf.N_WEEKS
    for name in fa:
        assert (a / name).read_bytes() == (b / name).read_bytes(), name


def test_committed_fixtures_match_generator(tmp_path):
    gf.generate(tmp_path, images=False)
    for p in sorted(tmp_path.iterdir()):
        if p.suffix in (".txt", ".json", ".jsonl") and p.name != "manifest.json":
            assert (FIX / p.name).read_text(encoding="utf-8") == p.read_text(encoding="utf-8"), \
                f"{p.name} is stale: re-run eval/gen_fixtures.py"


def test_png_render_is_deterministic(tmp_path):
    pytest.importorskip("PIL")
    import random
    text = "Tues - Jake 3 till 8:30ish, Bunnings + footy, 12km 🏉\n  second line\n"
    gf.render_png(text, tmp_path / "a.png", random.Random("x"))
    gf.render_png(text, tmp_path / "b.png", random.Random("x"))
    assert (tmp_path / "a.png").read_bytes() == (tmp_path / "b.png").read_bytes()


def test_every_gold_time_and_date_is_valid():
    for g in golds():
        we = date.fromisoformat(g["week_ending"])
        assert we.weekday() == 6, g["week"]
        week = {(we - timedelta(days=i)).isoformat() for i in range(7)}
        assert 5 <= len(g["shifts"]) <= 10, g["week"]
        for s in g["shifts"]:
            assert HHMM.match(s["start"]) and HHMM.match(s["end"]), s
            assert s["date"] in week, (g["week"], s)
            assert 0 <= s["km"] <= 40
            assert s["participant_id"] in {"jake", "priya", "tom", "nonna"}


def test_gold_times_are_derivable_from_the_text():
    for g in golds():
        text = (FIX / f"{g['week']}.txt").read_text(encoding="utf-8")
        for s in g["shifts"]:
            st, en = gf.parse_range(s["time_text"])
            assert (gf.hhmm(st), gf.hhmm(en)) == (s["start"], s["end"]), s
            assert s["time_text"] in text and s["note"] in text, s
            assert (en >= 1440) == s["overnight"]


def test_fixture_coverage():
    shifts = [s for g in golds() for s in g["shifts"]]
    kinds = {k: sum(1 for s in shifts if s["kind"] == k) for k in {s["kind"] for s in shifts}}
    for k in ("weekday_day", "weekday_cross_20", "weekday_evening", "saturday", "sunday", "public_holiday"):
        assert kinds.get(k, 0) >= 5, kinds
    assert 1 <= kinds.get("overnight", 0) <= 2
    ph_dates = {s["date"] for s in shifts if s["kind"] == "public_holiday"}
    assert ph_dates == {d.isoformat() for d in gf.TARGET_PH}
    assert not {s["date"] for s in shifts} & {d.isoformat() for d in gf.AVOID}
    doubles = sum(1 for g in golds() for k, n in
                  __import__("collections").Counter((s["participant_id"], s["date"]) for s in g["shifts"]).items() if n > 1)
    assert doubles >= 5


def test_rp_labels():
    rows = [json.loads(ln) for ln in (FIX / "rp_notes.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(rows) == len(gf.RP_NOTES) == 42
    pos = [r for r in rows if r["is_rp"] and not r["authorised_in_bsp"]]
    assert {t: sum(r["rp_type"] == t for r in pos) for t in ev.RP_TYPES} == {t: 4 for t in ev.RP_TYPES}
    auth = [r for r in rows if r["authorised_in_bsp"]]
    assert {(r["participant_id"], r["rp_type"]) for r in auth} == {("priya", "chemical"), ("nonna", "mechanical")}
    assert sum(not r["is_rp"] for r in rows) == 20
    assert all(r["rp_type"] is None and not r["harm_mentioned"] for r in rows if not r["is_rp"])
    by_week = {g["week"]: g for g in golds()}
    for r in rows:  # each labelled note sits on exactly one gold shift for that participant and day
        hits = [s for s in by_week[r["week"]]["shifts"]
                if s["participant_id"] == r["participant_id"] and s["date"] == r["date"]]
        assert len(hits) == 1 and r["text"] in hits[0]["note"], r


def test_heldout_notes_do_not_leak_into_prompts():
    """No 5-word run of a held-out RP note may appear in the LLM layer's prompt source."""
    srcs = [p for p in (ROOT / "arvo" / "rp.py", ROOT / "arvo" / "extract.py") if p.exists()]
    if not srcs:
        pytest.skip("arvo prompt modules not present")
    words = lambda t: re.findall(r"[a-z']+", t.lower())  # noqa: E731
    grams = lambda t: {" ".join(w[i:i + 5]) for w in [words(t)] for i in range(len(w) - 4)}  # noqa: E731
    prompt = set().union(*(grams(p.read_text(encoding="utf-8")) for p in srcs))
    leaks = {n["id"]: grams(n["text"]) & prompt for n in gf.RP_NOTES if grams(n["text"]) & prompt}
    assert not leaks, leaks


@pytest.mark.parametrize("text,expect", [
    ("3 till 8:30ish", ("15:00", "20:30")),
    ("half 9 to 1", ("09:30", "13:00")),
    ("7am-9", ("07:00", "09:00")),
    ("quarter to 6 - 9pm", ("17:45", "21:00")),
    ("noon-2PM", ("12:00", "14:00")),
    ("7pm - 1", ("19:00", "01:00")),
    ("15:00-20:30", ("15:00", "20:30")),
    ("from 2.30pm till 6", ("14:30", "18:00")),
])
def test_reference_time_reader(text, expect):
    s, e = gf.parse_range(text)
    assert (gf.hhmm(s), gf.hhmm(e)) == expect


# ------------------------------------------------------------------------------- metrics
def S(pid, d, s, e, km=0, kind="weekday_day"):
    return {"participant_id": pid, "date": d, "start": s, "end": e, "km": km, "kind": kind}


def test_match_shifts_basic_and_doubles():
    gold = [S("nonna", "2026-10-05", "07:00", "09:00"), S("nonna", "2026-10-05", "17:00", "19:00"),
            S("jake", "2026-10-06", "15:00", "20:30", 12)]
    pred = [S("nonna", "2026-10-05", "17:00", "19:00"), S("jake", "2026-10-06", "15:00", "08:30", 12),
            S("nonna", "2026-10-05", "07:00", "09:00")]
    assert ev.match_shifts(gold, pred) == [(0, 2, 2), (1, 0, 2), (2, 1, 2)]
    m = ev.extraction_metrics(ev.extraction_counts(gold, pred))
    assert m["recall"] == 1.0 and m["precision"] == 1.0
    assert m["field_accuracy"]["end"] == round(2 / 3, 4) and m["exact_match"] == round(2 / 3, 4)


def test_match_shifts_wrong_participant_or_date_still_scores_fields():
    gold = [S("tom", "2026-10-07", "16:00", "19:00", 10), S("priya", "2026-10-08", "18:00", "21:00")]
    pred = [S("jake", "2026-10-07", "16:00", "19:00", 10),   # wrong name, same day/time
            S("priya", "2026-10-09", "18:00", "21:00"),      # right person, wrong day
            S("nonna", "2026-10-10", "07:00", "08:00")]      # invented
    pairs = ev.match_shifts(gold, pred)
    assert [(i, j) for i, j, _ in pairs] == [(0, 0), (1, 1)] and all(t == 1 for *_, t in pairs)
    m = ev.extraction_metrics(ev.extraction_counts(gold, pred))
    assert m["recall"] == 0.0 and m["precision"] == 0.0
    assert m["field_accuracy"] == {"participant": 0.5, "date": 0.5, "start": 1.0, "end": 1.0, "km": 1.0}
    assert m["exact_match"] == 0.0


def test_overnight_overlap_and_kind_breakdown():
    g = [S("jake", "2026-11-13", "19:00", "01:00", 8, kind="overnight")]
    assert ev.overlap(g[0], S("jake", "2026-11-13", "23:00", "02:00")) == 120
    m = ev.extraction_metrics(ev.extraction_counts(g, [S("jake", "2026-11-13", "19:00", "01:00", 8)]))
    assert m["exact_by_kind"] == {"overnight": {"n": 1, "exact": 1.0}}
    empty = ev.extraction_metrics(ev.extraction_counts(g, []))
    assert empty["recall"] == 0.0 and empty["precision"] is None


def L(pid, d, item, q, total):
    return {"participant_id": pid, "date": d, "item_number": item, "quantity": q, "total": total}


def test_invoice_week_metrics():
    gold = [L("jake", "2026-10-06", "04_103_0125_6_1", 5.5, 445.89), L("jake", "2026-10-06", "KM", 12, 11.88)]
    same = [L("jake", "2026-10-06", "04_103_0125_6_1", 5.5, 445.89), L("jake", "2026-10-06", "KM", 12.0, 11.88)]
    w = ev.invoice_week(gold, same)
    assert w["matched"] == 2 and w["total_exact"] and w["lines_exact"] and w["abs_error"] == 0
    wrong = [L("jake", "2026-10-06", "04_104_0125_6_1", 5.5, 404.69)]
    w2 = ev.invoice_week(gold, wrong)
    assert w2["matched"] == 0 and not w2["total_exact"] and w2["abs_error"] == round(445.89 + 11.88 - 404.69, 2)
    m = ev.invoice_metrics([w, w2])
    assert m["line_recall"] == 0.5 and m["line_precision"] == round(2 / 3, 4)
    assert m["weeks_total_exact"] == 1 and m["abs_error_sum"] == w2["abs_error"]


def test_prf_and_latency():
    assert ev.prf(3, 1, 1) == {"tp": 3, "fp": 1, "fn": 1, "precision": 0.75, "recall": 0.75, "f1": 0.75}
    assert ev.prf(0, 0, 2)["precision"] is None and ev.prf(0, 2, 0)["recall"] is None
    assert ev.latency([1, 2, 3, 4, 100]) == {"n": 5, "mean_s": 22.0, "p95_s": 100.0}


def test_rp_metrics_detection_vs_needs_reporting():
    gold = [
        {"participant_id": "jake", "date": "d1", "is_rp": True, "rp_type": "environmental", "authorised_in_bsp": False, "harm_mentioned": False},
        {"participant_id": "priya", "date": "d2", "is_rp": True, "rp_type": "chemical", "authorised_in_bsp": True, "harm_mentioned": False},
        {"participant_id": "tom", "date": "d3", "is_rp": False, "rp_type": None, "authorised_in_bsp": False, "harm_mentioned": False},
        {"participant_id": "nonna", "date": "d4", "is_rp": True, "rp_type": "physical", "authorised_in_bsp": False, "harm_mentioned": True},
    ]
    flags = [
        {"participant_id": "jake", "date": "d1", "rp_type": "environmental", "authorised_in_bsp": False, "harm_mentioned": False},
        {"participant_id": "priya", "date": "d2", "rp_type": "chemical", "authorised_in_bsp": True, "harm_mentioned": False},
        {"participant_id": "tom", "date": "d3", "rp_type": "seclusion", "authorised_in_bsp": False, "harm_mentioned": False},
        {"participant_id": "nonna", "date": "d4", "rp_type": "mechanical", "authorised_in_bsp": False, "harm_mentioned": True},
    ]
    m = ev.rp_metrics(gold, flags)
    assert m["detection"]["overall"] == ev.prf(2, 2, 1)
    assert m["needs_reporting"]["overall"] == ev.prf(1, 2, 1)  # authorised PRN is not a needs-reporting prediction
    assert m["detection"]["any_type_note_level"] == ev.prf(3, 1, 0)
    assert m["detection"]["by_type"]["physical"] == ev.prf(0, 0, 1)
    assert m["hard_negatives_flagged"] == "1/1" and m["authorised_marked_authorised"] == "1/1"
    assert m["harm_correct_on_detected"] == "2/2"


def test_keyword_baseline():
    assert [t for t, _ in baselines.keyword_types("Locked him in his room.")] == ["seclusion"]
    assert [t for t, _ in baselines.keyword_types("We had a nice walk.")] == []
    f = baselines.keyword_rp("Gave her PRN lorazepam. She was fine.", ["PRN lorazepam 0.5mg as per BSP"])
    assert f == [{"rp_type": "chemical", "evidence_quote": "Gave her PRN lorazepam.", "authorised_in_bsp": True,
                  "harm_mentioned": False}]
    assert baselines.keyword_rp("Strapped him in, he got a bruise.")[0]["harm_mentioned"] is True


# ------------------------------------------------------------------------------- splits / --rp-all
def test_split_selection_before_limit():
    weeks = ev.load_fixtures()
    dev, test = ev.select_weeks(weeks, "dev"), ev.select_weeks(weeks, "test")
    assert [w["week"] for w in dev] == [f"week{i:02d}" for i in range(1, 9)]
    assert [w["week"] for w in test] == [f"week{i:02d}" for i in range(9, 25)]
    assert len(ev.select_weeks(weeks, "all")) == 24
    assert [w["week"] for w in ev.select_weeks(weeks, "test", 2)] == ["week09", "week10"]
    assert {w["week"] for w in test if w["image"]} == {"week09", "week13", "week16", "week21"}
    assert {w["week"] for w in dev if w["image"]} == {"week02", "week06"}


def test_parser_and_split_named_outputs():
    a = ev.build_parser().parse_args([])
    assert a.split == "all" and a.rp_all is False and a.limit is None
    a = ev.build_parser().parse_args(["--split", "test", "--rp-all", "--limit", "3"])
    assert (a.split, a.rp_all, a.limit) == ("test", True, 3)
    with pytest.raises(SystemExit):
        ev.build_parser().parse_args(["--split", "train"])
    js, raw, md = ev.result_paths("gemma4:e4b", "test")
    assert (js.name, raw.name, md.name) == ("gemma4_e4b_test.json", "gemma4_e4b_test", "summary_test.md")
    assert ev.result_paths("gemma4:e4b", "dev")[2].name == "summary_dev.md"


def test_rp_note_shifts_cover_every_heldout_note():
    rows = ev.load_rp_notes()
    shifts = ev.rp_note_shifts(rows)
    assert len(shifts) == 42 and [s["note"] for s in shifts] == [r["text"] for r in rows]
    assert len({(s["participant_id"], s["date"]) for s in shifts}) == 42  # keys never collide in rp_metrics


def test_run_model_offline_with_split_and_rp_all(tmp_path, monkeypatch):
    """Whole run_model path with fake model calls (gold in, gold out): no network, no Ollama."""
    import types
    extract = pytest.importorskip("arvo.extract")
    rp = pytest.importorskip("arvo.rp")
    pytest.importorskip("arvo.pricing")
    from arvo.models import RPFlag

    monkeypatch.setattr(ev, "RESULTS", tmp_path)
    monkeypatch.setattr(ev, "RAW", tmp_path / "raw")
    weeks = ev.select_weeks(ev.load_fixtures(), "dev", 2)
    by_we = {w["week_ending"]: w for w in weeks}
    monkeypatch.setattr(extract, "extract_shifts", lambda text, roster, we, model, image_path=None: (
        [ev.to_shift(s) for s in by_we[we]["shifts"]], [], {}))
    rows = ev.load_rp_notes()

    def fake_screen(shifts, roster, model):
        keys = {(s.participant_id, s.date) for s in shifts}
        flags = [RPFlag(r["participant_id"], r["date"], r["rp_type"], "q", r["harm_mentioned"], r["authorised_in_bsp"])
                 for r in rows if r["is_rp"] and (r["participant_id"], r["date"]) in keys]
        return flags, {"per_call_s": [0.1] * len(shifts), "warnings": []}

    monkeypatch.setattr(rp, "screen_notes", fake_screen)
    args = types.SimpleNamespace(split="dev", limit=2, images=False, skip_baseline=True, rp_all=True)
    roster = json.loads((ROOT / "data" / "roster.example.json").read_text(encoding="utf-8"))
    r = ev.run_model("fake", weeks, roster, args)
    assert r["split"] == "dev" and r["weeks"] == ["week01", "week02"]
    assert r["extraction"]["exact_match"] == 1.0 and r["invoice"]["weeks_total_exact"] == 2
    assert r["rp_all"]["n_notes"] == 42
    assert r["rp_all"]["gemma"]["detection"]["overall"]["f1"] == 1.0
    assert r["rp_all"]["gemma"]["needs_reporting"]["overall"] == ev.prf(20, 0, 0)
    assert r["rp_all"]["gemma"]["hard_negatives_flagged"] == "0/20"
    assert (tmp_path / "raw" / "fake_dev" / "week01.json").exists()
    md = ev.summary_md([r], "dev")
    assert md.startswith("# Arvo eval summary: dev split (weeks 01-08)")
    assert "tuned only on dev weeks 1-8" in md and "held-out note set (all 42 notes" in md


# ------------------------------------------------------------------------------- code-only / wild set
def test_derive_kind_matches_generator_kinds():
    pytest.importorskip("arvo.calendar_au")
    for g in golds():
        for s in g["shifts"]:
            assert ev.derive_kind({k: v for k, v in s.items() if k != "kind"}) == s["kind"], s


def _write_wild(dirpath: Path, n: int = 2) -> None:
    """A tiny wild set built from synthetic weeks, with 'kind' and 'week' stripped like hand-written gold."""
    dirpath.mkdir(parents=True, exist_ok=True)
    for g in golds()[:n]:
        gold = {"week_ending": g["week_ending"], "rp": g["rp"],
                "shifts": [{k: v for k, v in s.items() if k != "kind"} for s in g["shifts"]]}
        (dirpath / f"{g['week']}.gold.json").write_text(json.dumps(gold), encoding="utf-8")
        (dirpath / f"{g['week']}.txt").write_text((FIX / f"{g['week']}.txt").read_text(encoding="utf-8"),
                                                 encoding="utf-8")


def test_wild_loader_and_parser(tmp_path, monkeypatch):
    _write_wild(tmp_path / "wild")
    monkeypatch.setattr(ev, "WILD", tmp_path / "wild")
    weeks = ev.load_fixtures("wild")
    assert [w["week"] for w in weeks] == ["week01", "week02"] and all(w["text"] and w["png"] is None for w in weeks)
    assert ev.select_weeks(weeks, "wild") == weeks and ev.select_weeks(weeks, "wild", 1) == weeks[:1]
    a = ev.build_parser().parse_args([])
    assert a.set == "synthetic"
    assert ev.build_parser().parse_args(["--set", "wild", "--models", "code-only"]).set == "wild"
    assert ev.result_paths("code-only", "wild")[0].name == "code-only_wild.json"
    assert ev.result_paths("gemma4:e4b", "wild")[2].name == "summary_wild.md"


def test_code_only_on_wild_offline(tmp_path, monkeypatch):
    """code-only: deterministic extractor only; RP, photos and model-alone baseline are n/a. No network."""
    import types
    extract = pytest.importorskip("arvo.extract")
    rp = pytest.importorskip("arvo.rp")
    pytest.importorskip("arvo.pricing")
    pytest.importorskip("arvo.calendar_au")

    _write_wild(tmp_path / "wild")
    monkeypatch.setattr(ev, "WILD", tmp_path / "wild")
    monkeypatch.setattr(ev, "RESULTS", tmp_path / "results")
    monkeypatch.setattr(ev, "RAW", tmp_path / "results" / "raw")
    weeks = ev.select_weeks(ev.load_fixtures("wild"), "wild")
    by_we = {w["week_ending"]: w for w in weeks}
    monkeypatch.setattr(extract, "extract_shifts_code_only", lambda text, roster, we: (
        [ev.to_shift(s) for s in by_we[we]["shifts"]], [], {"total_s": 0.0}), raising=False)

    def boom(*a, **k):
        raise AssertionError("code-only must not call the model")

    monkeypatch.setattr(rp, "screen_notes", boom)
    monkeypatch.setattr(baselines, "model_alone_lines", boom)
    args = types.SimpleNamespace(set="wild", split="wild", limit=None, images=True, skip_baseline=False, rp_all=True)
    roster = json.loads((ROOT / "data" / "roster.example.json").read_text(encoding="utf-8"))
    r = ev.run_model("code-only", weeks, roster, args)
    assert r["code_only"] and r["split"] == "wild" and r["n_weeks"] == 2
    assert r["extraction"]["exact_match"] == 1.0 and r["invoice"]["weeks_total_exact"] == 2
    assert "n/a" not in r["extraction"]["exact_by_kind"]  # kinds derived from date/time/holidays
    assert r["rp"]["gemma"] is None and r["rp"]["keyword_baseline"]["n_flags"] >= 0
    assert r["rp_all"]["gemma"] is None and r["rp_all"]["n_notes"] == 42
    assert r["images"] is None and r["invoice_model_alone"] is None and r["model_alone_note"] == "n/a (code-only)"
    assert (tmp_path / "results" / "raw" / "code-only_wild" / "week01.json").exists()
    md = ev.summary_md([r], "wild")
    assert md.startswith("# Arvo eval summary: wild set") and "held out" in md
    assert "| code-only | n/a | n/a |" in md
