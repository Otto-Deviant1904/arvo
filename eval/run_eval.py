"""Arvo eval: extraction, invoice lines, restrictive-practice screening, photos, latency.

    uv run --with pillow python eval/run_eval.py --split test --models gemma4:e4b,gemma4:e2b --images --rp-all
    uv run --with pillow python eval/run_eval.py --split dev --models gemma4:e4b --limit 2 --skip-baseline  # smoke

Splits: dev = weeks 01-08 (prompts/code may be tuned on these), test = weeks 09-24 (run once at the end),
all = 01-24. The split is applied before --limit. --rp-all also screens the 42 held-out notes in
eval/fixtures/rp_notes.jsonl, whatever the split.
--models code-only: the no-model extractor arvo.extract.extract_shifts_code_only (no RP, photos or baseline).
--set wild: eval/wild/weekNN.txt + weekNN.gold.json (held out, no split); results named <model>_wild.

Gold comes only from eval/fixtures/*.gold.json (made by eval/gen_fixtures.py). Gold invoice lines are
the gold shifts priced by arvo.pricing, so line metrics measure what extraction errors cost in dollars.
RP is screened on the GOLD shifts' notes, so RP numbers are not confounded by extraction.

Writes eval/results/<model>_<split>.json, eval/results/summary_<split>.md, raw predictions in
eval/results/raw/<model>_<split>/.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
import traceback
import urllib.request
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "eval" / "fixtures"
WILD = ROOT / "eval" / "wild"
RESULTS = ROOT / "eval" / "results"
RAW = RESULTS / "raw"
ROSTER_PATH = ROOT / "data" / "roster.example.json"
for p in (str(ROOT), str(ROOT / "eval")):
    if p not in sys.path:
        sys.path.insert(0, p)

RP_TYPES = ("seclusion", "chemical", "mechanical", "physical", "environmental")
SPLITS = {"dev": range(1, 9), "test": range(9, 25), "all": range(1, 25)}
SPLIT_LABEL = {"dev": "dev split (weeks 01-08)", "test": "test split (weeks 09-24)", "all": "all weeks (01-24)",
               "wild": "wild set (eval/wild, held out)"}
CODE_ONLY = "code-only"  # pseudo-model: deterministic extractor, no LLM
SHIFT_FIELDS = ("participant", "date", "start", "end", "km")


# =============================================================================================
# Pure metric functions (unit-tested in tests/test_eval_harness.py; no arvo imports needed)
# =============================================================================================
def _get(x, k, default=None):
    return x.get(k, default) if isinstance(x, dict) else getattr(x, k, default)


def tmin(hhmm: str) -> int:
    h, m = str(hhmm).split(":")
    return int(h) * 60 + int(m)


def interval(sh) -> tuple[int, int]:
    """Minutes from the shift date's midnight; an end at/before the start means it finished next day."""
    s, e = tmin(_get(sh, "start")), tmin(_get(sh, "end"))
    return (s, e + 1440) if e <= s else (s, e)


def overlap(a, b) -> int:
    (a0, a1), (b0, b1) = interval(a), interval(b)
    return max(0, min(a1, b1) - max(a0, b0))


def same_time(a: str, b: str) -> bool:
    try:
        return tmin(a) % 1440 == tmin(b) % 1440
    except (ValueError, AttributeError, TypeError):
        return False


def match_shifts(gold: list, pred: list) -> list[tuple[int, int, int]]:
    """Greedy one-to-one matching. Returns [(gold_idx, pred_idx, tier)].
    tier 2: same participant and date (ranked by time overlap); tier 1: only one of participant/date
    agrees but the times overlap (so a wrong name or wrong day still counts against that field)."""
    cands = []
    for i, g in enumerate(gold):
        for j, p in enumerate(pred):
            same_pid = _get(g, "participant_id") == _get(p, "participant_id")
            same_date = _get(g, "date") == _get(p, "date")
            try:
                ov = overlap(g, p)
                dstart = abs(tmin(_get(g, "start")) - tmin(_get(p, "start")))
            except (ValueError, AttributeError, TypeError):
                ov, dstart = 0, 10_000
            if same_pid and same_date:
                tier = 2
            elif (same_pid or same_date) and ov > 0:
                tier = 1
            else:
                continue
            cands.append((tier, ov, -dstart, -i, -j))
    cands.sort(reverse=True)
    used_g, used_p, out = set(), set(), []
    for tier, _, _, ni, nj in cands:
        i, j = -ni, -nj
        if i in used_g or j in used_p:
            continue
        used_g.add(i)
        used_p.add(j)
        out.append((i, j, tier))
    return sorted(out)


def field_hits(g, p) -> dict[str, bool]:
    return {
        "participant": _get(g, "participant_id") == _get(p, "participant_id"),
        "date": _get(g, "date") == _get(p, "date"),
        "start": same_time(_get(g, "start"), _get(p, "start")),
        "end": same_time(_get(g, "end"), _get(p, "end")),
        "km": abs(float(_get(g, "km") or 0) - float(_get(p, "km") or 0)) < 0.05,
    }


def extraction_counts(gold: list, pred: list) -> dict:
    """Raw counts for one week; sum them with add_counts, then finish with extraction_metrics."""
    c = Counter(n_gold=len(gold), n_pred=len(pred))
    for i, j, tier in match_shifts(gold, pred):
        hits = field_hits(gold[i], pred[j])
        if tier == 2:
            c["found"] += 1
        for f, ok in hits.items():
            c[f"ok_{f}"] += ok
        if all(hits.values()):
            c["exact"] += 1
            c[f"exact_kind_{_get(gold[i], 'kind', 'unknown')}"] += 1
    for g in gold:
        c[f"n_kind_{_get(g, 'kind', 'unknown')}"] += 1
    return dict(c)


def add_counts(total: dict, c: dict) -> dict:
    for k, v in c.items():
        total[k] = total.get(k, 0) + v
    return total


def _ratio(a: float, b: float) -> float | None:
    return round(a / b, 4) if b else None


def extraction_metrics(c: dict) -> dict:
    ng, npred = c.get("n_gold", 0), c.get("n_pred", 0)
    out = {"n_gold": ng, "n_pred": npred,
           "recall": _ratio(c.get("found", 0), ng), "precision": _ratio(c.get("found", 0), npred),
           "field_accuracy": {f: _ratio(c.get(f"ok_{f}", 0), ng) for f in SHIFT_FIELDS},
           "exact_match": _ratio(c.get("exact", 0), ng)}
    kinds = sorted(k[len("n_kind_"):] for k in c if k.startswith("n_kind_"))
    out["exact_by_kind"] = {k: {"n": c[f"n_kind_{k}"], "exact": _ratio(c.get(f"exact_kind_{k}", 0), c[f"n_kind_{k}"])}
                            for k in kinds}
    return out


def derive_kind(s) -> str:
    """Shift kind from date/times/Vic holidays (same rules as gen_fixtures.classify), for gold without 'kind'."""
    from datetime import date as _date
    try:
        from arvo.calendar_au import is_public_holiday
    except ImportError:
        return "n/a"
    try:
        st, en = tmin(_get(s, "start")), tmin(_get(s, "end"))
        d = _date.fromisoformat(_get(s, "date"))
        ph = is_public_holiday(d.isoformat())
    except Exception:  # noqa: BLE001
        return "n/a"
    if ph:
        return "public_holiday"
    if en <= st:
        return "overnight"
    if d.weekday() >= 5:
        return "saturday" if d.weekday() == 5 else "sunday"
    if st >= 20 * 60:
        return "weekday_evening"
    return "weekday_cross_20" if en > 20 * 60 else "weekday_day"


def with_kinds(shifts: list[dict]) -> list[dict]:
    return [s if s.get("kind") else {**s, "kind": derive_kind(s)} for s in shifts]


def line_key(ln) -> tuple:
    return (_get(ln, "participant_id"), _get(ln, "date"), str(_get(ln, "item_number") or "").strip(),
            round(float(_get(ln, "quantity") or 0) + 1e-9, 2), round(float(_get(ln, "total") or 0) + 1e-9, 2))


def invoice_week(gold_lines: list, pred_lines: list) -> dict:
    """Line multiset match on (participant, date, item, quantity, total) + the week's dollar error."""
    g, p = Counter(map(line_key, gold_lines)), Counter(map(line_key, pred_lines))
    matched = sum((g & p).values())
    gt = round(sum(float(_get(x, "total") or 0) for x in gold_lines) + 1e-9, 2)
    pt = round(sum(float(_get(x, "total") or 0) for x in pred_lines) + 1e-9, 2)
    err = round(abs(pt - gt) + 1e-9, 2)
    return {"n_gold": len(gold_lines), "n_pred": len(pred_lines), "matched": matched,
            "gold_total": gt, "pred_total": pt, "abs_error": err,
            "total_exact": err < 0.005, "lines_exact": g == p}


def invoice_metrics(weeks: list[dict]) -> dict:
    ng = sum(w["n_gold"] for w in weeks)
    npred = sum(w["n_pred"] for w in weeks)
    m = sum(w["matched"] for w in weeks)
    errs = [w["abs_error"] for w in weeks]
    return {"weeks": len(weeks), "n_gold_lines": ng, "n_pred_lines": npred,
            "line_precision": _ratio(m, npred), "line_recall": _ratio(m, ng),
            "line_f1": _ratio(2 * m, ng + npred),
            "weeks_total_exact": sum(w["total_exact"] for w in weeks),
            "weeks_lines_exact": sum(w["lines_exact"] for w in weeks),
            "abs_error_sum": round(sum(errs) + 1e-9, 2),
            "abs_error_mean": round(sum(errs) / len(errs) + 1e-9, 2) if errs else None,
            "gold_dollars": round(sum(w["gold_total"] for w in weeks) + 1e-9, 2)}


def prf(tp: int, fp: int, fn: int) -> dict:
    p = tp / (tp + fp) if tp + fp else None
    r = tp / (tp + fn) if tp + fn else None
    f = 2 * p * r / (p + r) if p and r else (0.0 if (p is not None and r is not None) else None)
    rnd = (lambda x: round(x, 4) if x is not None else None)
    return {"tp": tp, "fp": fp, "fn": fn, "precision": rnd(p), "recall": rnd(r), "f1": rnd(f)}


def _set_prf(gold: set, pred: set) -> dict:
    return prf(len(gold & pred), len(pred - gold), len(gold - pred))


def rp_metrics(gold_rows: list[dict], flags: list) -> dict:
    """gold_rows: labelled notes {participant_id, date, is_rp, rp_type, authorised_in_bsp, harm_mentioned}.
    flags: model or baseline flags {participant_id, date, rp_type, authorised_in_bsp, harm_mentioned}.
    (1) detection: any regulated RP, authorised or not. (2) needs_reporting: RP not authorised in the BSP;
    a flag predicts needs-reporting when its authorised_in_bsp is false. Keys are (participant, date, type)."""
    fkey = [(_get(f, "participant_id"), _get(f, "date"), _get(f, "rp_type")) for f in flags]
    pos = {(r["participant_id"], r["date"], r["rp_type"]) for r in gold_rows if r["is_rp"]}
    pos_rep = {(r["participant_id"], r["date"], r["rp_type"]) for r in gold_rows
               if r["is_rp"] and not r["authorised_in_bsp"]}
    pred = set(fkey)
    pred_rep = {k for k, f in zip(fkey, flags) if not _get(f, "authorised_in_bsp")}

    def by_type(g, p):
        return {t: _set_prf({k for k in g if k[2] == t}, {k for k in p if k[2] == t}) for t in RP_TYPES}

    note = lambda s: {k[:2] for k in s}  # noqa: E731
    neg_notes = {(r["participant_id"], r["date"]) for r in gold_rows if not r["is_rp"]}
    labelled = {(r["participant_id"], r["date"]) for r in gold_rows}
    tp_keys = pos & pred
    harm_gold = {(r["participant_id"], r["date"], r["rp_type"]): r["harm_mentioned"] for r in gold_rows if r["is_rp"]}
    harm_pred: dict = {}
    for k, f in zip(fkey, flags):
        harm_pred[k] = harm_pred.get(k, False) or bool(_get(f, "harm_mentioned"))
    auth_rows = [(r["participant_id"], r["date"], r["rp_type"]) for r in gold_rows if r["is_rp"] and r["authorised_in_bsp"]]
    auth_ok = sum(1 for k in auth_rows if k in pred and k not in pred_rep)
    return {
        "detection": {"overall": _set_prf(pos, pred), "by_type": by_type(pos, pred),
                      "any_type_note_level": _set_prf(note(pos), note(pred))},
        "needs_reporting": {"overall": _set_prf(pos_rep, pred_rep), "by_type": by_type(pos_rep, pred_rep),
                            "any_type_note_level": _set_prf(note(pos_rep), note(pred_rep))},
        "hard_negatives_flagged": f"{len(neg_notes & note(pred))}/{len(neg_notes)}",
        "unlabelled_notes_flagged": len(note(pred) - labelled),
        "harm_correct_on_detected": f"{sum(harm_pred[k] == harm_gold[k] for k in tp_keys)}/{len(tp_keys)}",
        "authorised_marked_authorised": f"{auth_ok}/{len(auth_rows)}",
        "n_flags": len(flags), "n_flag_keys": len(pred),
    }


def latency(values: list[float]) -> dict:
    v = sorted(float(x) for x in values if x is not None)
    if not v:
        return {"n": 0, "mean_s": None, "p95_s": None}
    return {"n": len(v), "mean_s": round(sum(v) / len(v), 3), "p95_s": round(v[max(0, math.ceil(0.95 * len(v)) - 1)], 3)}


# =============================================================================================
# Running the system
# =============================================================================================
def select_weeks(weeks: list[dict], split: str = "all", limit: int | None = None) -> list[dict]:
    """Keep the split's weeks (by week number), then the first `limit` of them."""
    keep = weeks if split not in SPLITS else [w for w in weeks if int(w["week"][4:]) in SPLITS[split]]
    return keep[:limit] if limit else keep


def rp_note_shifts(rows: list[dict]) -> list[dict]:
    """rp_notes.jsonl rows -> one shift-like dict per note (times are placeholders; only the note is screened)."""
    return [{"participant_id": r["participant_id"], "date": r["date"], "start": "09:00", "end": "10:00",
             "km": 0.0, "note": r["text"]} for r in rows]


def load_rp_notes() -> list[dict]:
    path = FIXTURES / "rp_notes.jsonl"
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def result_paths(model: str, split: str) -> tuple[Path, Path, Path]:
    """(results json, raw dir, summary md) for one model and split, so dev runs never overwrite test ones."""
    return (RESULTS / f"{slug(model)}_{split}.json", RAW / f"{slug(model)}_{split}", RESULTS / f"summary_{split}.md")


def load_fixtures(set_name: str = "synthetic") -> list[dict]:
    """weekNN.txt + weekNN.gold.json pairs from eval/fixtures (synthetic) or eval/wild (wild)."""
    base = FIXTURES if set_name == "synthetic" else WILD
    weeks = []
    for gp in sorted(base.glob("week*.gold.json")):
        stem = gp.name[: -len(".gold.json")]
        gold = json.loads(gp.read_text(encoding="utf-8"))
        gold.setdefault("week", stem)
        gold["text"] = (base / f"{stem}.txt").read_text(encoding="utf-8")
        gold["rp"] = gold.get("rp") or []
        gold["png"] = str(base / gold["image"]) if gold.get("image") and (base / gold["image"]).exists() else None
        weeks.append(gold)
    return weeks


def to_shift(d: dict):
    from arvo.models import Shift
    return Shift(participant_id=d["participant_id"], date=d["date"], start=d["start"], end=d["end"],
                 km=float(d["km"]), note=d.get("note", ""))


def as_dict(x) -> dict:
    from dataclasses import asdict, is_dataclass
    return asdict(x) if is_dataclass(x) else dict(x)


def slug(model: str) -> str:
    return model.replace(":", "_").replace("/", "_")


def check_ollama(models: list[str]) -> None:
    from arvo import llm
    models = [m for m in models if m != CODE_ONLY]
    if not models:
        return
    try:
        with urllib.request.urlopen(llm.OLLAMA_URL + "/api/tags", timeout=5) as r:
            have = {m["name"] for m in json.loads(r.read()).get("models", [])}
    except Exception as e:  # noqa: BLE001
        raise SystemExit(f"Ollama not reachable at {llm.OLLAMA_URL}: {e}")
    missing = [m for m in models if m not in have and f"{m}:latest" not in have]
    if missing:
        raise SystemExit(f"models not pulled in Ollama: {missing} (have {sorted(have)})")


def price(shifts, roster) -> tuple[list[dict], list[str]]:
    from arvo.pricing import price_shifts
    lines, warns = price_shifts(shifts, roster)
    return [as_dict(x) for x in lines], list(warns)


def run_model(model: str, weeks: list[dict], roster: dict, args) -> dict:
    import baselines

    code_only = model == CODE_ONLY
    if code_only:  # no LLM: no RP screen, no photos, no model-alone baseline
        try:
            from arvo.extract import extract_shifts_code_only
        except ImportError as e:
            raise SystemExit(f"code-only needs arvo.extract.extract_shifts_code_only: {e}")

        def extract_shifts(text, roster_, week_ending, _model, image_path=None):
            return extract_shifts_code_only(text, roster_, week_ending)
        screen_notes = None
    else:
        from arvo.extract import extract_shifts
        from arvo.rp import screen_notes

    t_all = time.perf_counter()
    split = getattr(args, "split", "all")
    raw_dir = result_paths(model, split)[1]
    raw_dir.mkdir(parents=True, exist_ok=True)
    ex_c, img_c = {}, {}
    inv, inv_base, inv_img = [], [], []
    rp_gold, rp_flags, kw_flags = [], [], []
    lat = {"extract_s": [], "rp_note_s": [], "image_s": [], "baseline_s": []}
    dropped_quotes, errors, base_skipped = 0, [], False

    for wk in weeks:
        name = wk["week"]
        gold = [to_shift(s) for s in wk["shifts"]]
        gold_kinds = with_kinds(wk["shifts"])  # same order; 'kind' derived if the gold has none
        gold_lines, _ = price(gold, roster)
        rec = {"week": name, "week_ending": wk["week_ending"], "gold_lines": gold_lines}
        print(f"[{model}] {name} ...", flush=True)

        # --- extraction from text
        t0 = time.perf_counter()
        try:
            pred, warns, meta = extract_shifts(wk["text"], roster, wk["week_ending"], model)
        except Exception as e:  # noqa: BLE001  (LLMError, bad JSON...): the week scores as all-missed
            pred, warns, meta = [], [f"ERROR {type(e).__name__}: {e}"], {}
            errors.append(f"{name} extract: {type(e).__name__}: {e}")
        lat["extract_s"].append(time.perf_counter() - t0)
        add_counts(ex_c, extraction_counts(gold_kinds, [as_dict(p) for p in pred]))
        pred_lines, pwarn = price(pred, roster)
        inv.append({"week": name, **invoice_week(gold_lines, pred_lines)})
        rec.update(pred_shifts=[as_dict(p) for p in pred], extract_warnings=warns, extract_meta=meta,
                   pred_lines=pred_lines, pricing_warnings=pwarn)

        # --- RP on the gold notes (not confounded by extraction)
        rp_gold += wk["rp"]
        try:
            flags, rmeta = screen_notes(gold, roster, model) if screen_notes else ([], {})
        except Exception as e:  # noqa: BLE001
            flags, rmeta = [], {"warnings": [f"ERROR {e}"]}
            errors.append(f"{name} rp: {type(e).__name__}: {e}")
        lat["rp_note_s"] += list(rmeta.get("per_call_s", []))
        dropped_quotes += sum(1 for w in rmeta.get("warnings", []) if "quote not found" in w)
        rp_flags += [as_dict(f) for f in flags]
        kw = baselines.keyword_screen([as_dict(s) for s in gold], roster)
        kw_flags += kw
        rec.update(rp_flags=[as_dict(f) for f in flags], rp_meta=rmeta, keyword_flags=kw)

        # --- model-alone pricing baseline
        if not args.skip_baseline and not code_only:
            t0 = time.perf_counter()
            try:
                res = baselines.model_alone_lines(wk["text"], roster, wk["week_ending"], model)
            except Exception as e:  # noqa: BLE001
                res = ([], {"error": str(e)})
                errors.append(f"{name} baseline: {type(e).__name__}: {e}")
            if res is None:
                base_skipped = True
            else:
                lat["baseline_s"].append(time.perf_counter() - t0)
                inv_base.append({"week": name, **invoice_week(gold_lines, res[0])})
                rec.update(baseline_lines=res[0], baseline_meta=res[1])

        # --- photo of the paper diary
        if args.images and wk.get("png") and not code_only:
            t0 = time.perf_counter()
            try:
                ipred, iwarn, imeta = extract_shifts("", roster, wk["week_ending"], model, image_path=wk["png"])
            except Exception as e:  # noqa: BLE001
                ipred, iwarn, imeta = [], [f"ERROR {e}"], {}
                errors.append(f"{name} image: {type(e).__name__}: {e}")
            lat["image_s"].append(time.perf_counter() - t0)
            add_counts(img_c, extraction_counts(gold_kinds, [as_dict(p) for p in ipred]))
            ilines, _ = price(ipred, roster)
            inv_img.append({"week": name, **invoice_week(gold_lines, ilines)})
            rec.update(image_pred_shifts=[as_dict(p) for p in ipred], image_warnings=iwarn, image_meta=imeta)

        (raw_dir / f"{name}.json").write_text(json.dumps(rec, indent=1, ensure_ascii=False, default=str) + "\n",
                                              encoding="utf-8")

    rp_all = None
    if getattr(args, "rp_all", False):  # the held-out RP note set, screened whatever the split
        rows = load_rp_notes()
        nshifts = [to_shift(s) for s in rp_note_shifts(rows)]
        try:
            aflags, ameta = screen_notes(nshifts, roster, model) if screen_notes else ([], {})
        except Exception as e:  # noqa: BLE001
            aflags, ameta = [], {"warnings": [f"ERROR {e}"]}
            errors.append(f"rp-all: {type(e).__name__}: {e}")
        lat["rp_all_note_s"] = list(ameta.get("per_call_s", []))
        akw = baselines.keyword_screen([as_dict(s) for s in nshifts], roster)
        rp_all = {"gemma": None if code_only else {
                      **rp_metrics(rows, [as_dict(f) for f in aflags]),
                      "dropped_by_quote_check": sum(1 for w in ameta.get("warnings", []) if "quote not found" in w)},
                  "keyword_baseline": rp_metrics(rows, akw), "n_notes": len(rows)}
        (raw_dir / "rp_all.json").write_text(json.dumps(
            {"flags": [as_dict(f) for f in aflags], "meta": ameta, "keyword_flags": akw}, indent=1,
            ensure_ascii=False, default=str) + "\n", encoding="utf-8")

    n_notes = sum(1 for wk in weeks for s in wk["shifts"] if s.get("note"))
    out = {
        "model": model, "split": split, "n_weeks": len(weeks), "weeks": [w["week"] for w in weeks],
        "args": {"set": getattr(args, "set", "synthetic"), "split": split, "limit": args.limit, "images": args.images, "skip_baseline": args.skip_baseline,
                 "rp_all": bool(getattr(args, "rp_all", False))},
        "extraction": extraction_metrics(ex_c),
        "invoice": invoice_metrics(inv), "invoice_by_week": inv,
        "code_only": code_only,
        "invoice_model_alone": (None if args.skip_baseline or base_skipped or code_only else invoice_metrics(inv_base)),
        "invoice_model_alone_by_week": inv_base,
        "model_alone_note": ("n/a (code-only)" if code_only else "skipped (--skip-baseline)" if args.skip_baseline else
                             "skipped: data/ndis_prices_2026_27.json missing" if base_skipped else ""),
        "rp": {"gemma": None if code_only else {**rp_metrics(rp_gold, rp_flags), "dropped_by_quote_check": dropped_quotes},
               "keyword_baseline": rp_metrics(rp_gold, kw_flags),
               "n_labelled_notes": len(rp_gold), "n_notes_with_text": n_notes},
        "rp_all": rp_all,
        "images": ({"extraction": extraction_metrics(img_c), "invoice": invoice_metrics(inv_img)}
                   if args.images and not code_only else None),
        "latency": {"extract_per_diary": latency(lat["extract_s"]), "rp_per_note": latency(lat["rp_note_s"]),
                    "image_per_diary": latency(lat["image_s"]), "model_alone_per_diary": latency(lat["baseline_s"]),
                    "rp_all_per_note": latency(lat.get("rp_all_note_s", []))},
        "errors": errors,
        "wall_s": round(time.perf_counter() - t_all, 1),
    }
    return out


# =============================================================================================
# Summary table
# =============================================================================================
def _pct(x) -> str:
    return "n/a" if x is None else f"{100 * x:.1f}%"


def _s(x) -> str:
    return "n/a" if x is None else f"{x:.2f}"


def _rp_table(L: list[str], results: list[dict], key: str) -> None:
    L += ["| system | detection P | detection R | detection F1 | needs-reporting P | needs-reporting R | "
          "needs-reporting F1 | note-level F1 (any type) | hard negatives flagged | dropped by quote check |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    by_type = []
    seen_kw = False
    for r in results:
        if not r.get(key):
            continue
        rows = [(r["model"], r[key]["gemma"])] + ([] if seen_kw else [("keyword baseline", r[key]["keyword_baseline"])])
        seen_kw = True
        for label, m in rows:
            if m is None:  # code-only: no model RP screen
                L.append(f"| {label} | " + " | ".join(["n/a"] * 9) + " |")
                by_type.append(f"| {label} | " + " | ".join(["n/a"] * len(RP_TYPES)) + " |")
                continue
            d, n = m["detection"]["overall"], m["needs_reporting"]["overall"]
            L.append(f"| {label} | {_pct(d['precision'])} | {_pct(d['recall'])} | {_pct(d['f1'])} | "
                     f"{_pct(n['precision'])} | {_pct(n['recall'])} | {_pct(n['f1'])} | "
                     f"{_pct(m['detection']['any_type_note_level']['f1'])} | {m['hard_negatives_flagged']} | "
                     f"{m.get('dropped_by_quote_check', 'n/a')} |")
            bt = m["detection"]["by_type"]
            by_type.append(f"| {label} | " + " | ".join(
                f"{_pct(bt[t]['f1'])} ({bt[t]['tp']}/{bt[t]['tp'] + bt[t]['fn']})" for t in RP_TYPES) + " |")
    L += ["", "Detection F1 by type (detected/positives):", "", "| system | " + " | ".join(RP_TYPES) + " |",
          "|---|" + "---|" * len(RP_TYPES)] + by_type


def summary_md(results: list[dict], split: str = "all") -> str:
    held_out = ("The wild set is held out: it was never used for tuning and was run once at the end."
                if split == "wild" else
                "Prompts and code were tuned only on dev weeks 1-8; test weeks 9-24 and the RP note set were run "
                "once at the end.")
    source = ("Diaries and gold from `eval/wild/` (gold written by hand, not by a model)." if split == "wild" else
              "Synthetic diaries from `eval/gen_fixtures.py` (seeded); gold labels come from the generator, "
              "never a model.")
    rerun = ("--set wild" if split == "wild" else f"--split {split}")
    L = [f"# Arvo eval summary: {SPLIT_LABEL[split]}", "", held_out, "",
         f"{source} Gold invoice lines = gold shifts priced by `arvo.pricing`. RP is screened on the gold notes. "
         f"`code-only` = the deterministic extractor with no model (no RP, photo or model-alone numbers). "
         f"Re-run: `uv run --with pillow python eval/run_eval.py {rerun} --models ...`.", ""]
    L += ["## Shift extraction (typed diary text)", "",
          "| model | weeks | gold/pred shifts | recall | precision | participant | date | start | end | km | exact shift |",
          "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in results:
        e = r["extraction"]
        fa = e["field_accuracy"]
        L.append(f"| {r['model']} | {r['n_weeks']} | {e['n_gold']}/{e['n_pred']} | {_pct(e['recall'])} | "
                 f"{_pct(e['precision'])} | {_pct(fa['participant'])} | {_pct(fa['date'])} | {_pct(fa['start'])} | "
                 f"{_pct(fa['end'])} | {_pct(fa['km'])} | {_pct(e['exact_match'])} |")
    L += ["", "Exact-shift rate by shift kind:", "",
          "| model | " + " | ".join(sorted({k for r in results for k in r["extraction"]["exact_by_kind"]})) + " |",
          "|---|" + "---|" * len({k for r in results for k in r["extraction"]["exact_by_kind"]})]
    kinds = sorted({k for r in results for k in r["extraction"]["exact_by_kind"]})
    for r in results:
        ebk = r["extraction"]["exact_by_kind"]
        L.append(f"| {r['model']} | " + " | ".join(
            f"{_pct(ebk[k]['exact'])} (n={ebk[k]['n']})" if k in ebk else "n/a" for k in kinds) + " |")
    L += ["", "## Invoice lines (exact on participant, date, item, quantity, total)", "",
          "| system | weeks | line precision | line recall | weeks total right to the cent | weeks all lines right | "
          "mean abs $ error / week | total abs $ error |", "|---|---|---|---|---|---|---|---|"]
    for r in results:
        for label, m in ((f"{r['model']} reads, code prices (Arvo)", r["invoice"]),
                         (f"{r['model']} alone (model prices)", r.get("invoice_model_alone"))):
            if not m:
                if "alone" in label:
                    L.append(f"| {label} | {r['model_alone_note'] or 'n/a'} | | | | | | |")
                continue
            L.append(f"| {label} | {m['weeks']} | {_pct(m['line_precision'])} | {_pct(m['line_recall'])} | "
                     f"{m['weeks_total_exact']}/{m['weeks']} | {m['weeks_lines_exact']}/{m['weeks']} | "
                     f"${_s(m['abs_error_mean'])} | ${_s(m['abs_error_sum'])} |")
    L += ["", "## Restrictive-practice flags (on this split's gold notes)", "",
          "Detection = any regulated RP (authorised or not). Needs reporting = RP not authorised in the BSP "
          "(a flag predicts it when authorised_in_bsp is false). Matched on (participant, date, type).", ""]
    _rp_table(L, results, "rp")
    if any(r.get("rp_all") for r in results):
        n = next(r["rp_all"]["n_notes"] for r in results if r.get("rp_all"))
        L += ["", f"## Restrictive-practice flags: held-out note set (all {n} notes in rp_notes.jsonl, any split)", ""]
        _rp_table(L, results, "rp_all")
    if any(r.get("images") for r in results):
        L += ["", "## Photos of a paper diary (handwriting-style PNGs in this split)", "",
              "| model | gold/pred shifts | recall | precision | exact shift | weeks total right to the cent | "
              "mean abs $ error / week |", "|---|---|---|---|---|---|---|"]
        for r in results:
            if not r.get("images"):
                L.append(f"| {r['model']} | n/a | n/a | n/a | n/a | n/a | n/a |")
                continue
            e, m = r["images"]["extraction"], r["images"]["invoice"]
            L.append(f"| {r['model']} | {e['n_gold']}/{e['n_pred']} | {_pct(e['recall'])} | {_pct(e['precision'])} | "
                     f"{_pct(e['exact_match'])} | {m['weeks_total_exact']}/{m['weeks']} | ${_s(m['abs_error_mean'])} |")
    L += ["", "## Latency (seconds, this machine)", "",
          "| model | extract / diary mean | p95 | RP / note mean | p95 | photo / diary mean | p95 | "
          "model-alone / diary mean | wall time |", "|---|---|---|---|---|---|---|---|---|"]
    for r in results:
        la = r["latency"]
        L.append(f"| {r['model']} | {_s(la['extract_per_diary']['mean_s'])} | {_s(la['extract_per_diary']['p95_s'])} | "
                 f"{_s(la['rp_per_note']['mean_s'])} | {_s(la['rp_per_note']['p95_s'])} | "
                 f"{_s(la['image_per_diary']['mean_s'])} | {_s(la['image_per_diary']['p95_s'])} | "
                 f"{_s(la['model_alone_per_diary']['mean_s'])} | {r['wall_s']} |")
    errs = [(r["model"], e) for r in results for e in r.get("errors", [])]
    if errs:
        L += ["", f"Errors ({len(errs)}): " + "; ".join(f"{m}: {e}" for m, e in errs[:10])]
    return "\n".join(L) + "\n"


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Arvo eval")
    ap.add_argument("--models", default="gemma4:e4b",
                    help=f"comma-separated Ollama models; '{CODE_ONLY}' = the no-model extractor")
    ap.add_argument("--set", choices=["synthetic", "wild"], default="synthetic",
                    help="synthetic = eval/fixtures (split applies); wild = eval/wild (held out, no split)")
    ap.add_argument("--split", choices=sorted(SPLITS), default="all",
                    help="dev = weeks 01-08, test = weeks 09-24, all = 01-24 (applied before --limit)")
    ap.add_argument("--limit", type=int, default=None, help="only the first N weeks of the split")
    ap.add_argument("--images", action="store_true", help="also extract from the split's diary photos")
    ap.add_argument("--skip-baseline", action="store_true", help="skip the model-alone pricing baseline")
    ap.add_argument("--rp-all", action="store_true",
                    help="also screen all 42 held-out notes in rp_notes.jsonl, whatever the split")
    return ap


def write_summary(split: str) -> Path:
    """summary_<split>.md from every <model>_<split>.json present."""
    results = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(RESULTS.glob(f"*_{split}.json"))]
    results = [r for r in results if "extraction" in r and r.get("split") == split]
    path = result_paths("x", split)[2]
    path.write_text(summary_md(results, split), encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    models = [m.strip() for m in args.models.split(",") if m.strip()]

    try:
        import arvo.extract, arvo.pricing  # noqa: F401,E401
        if any(m != CODE_ONLY for m in models):
            import arvo.rp  # noqa: F401
    except ImportError as e:
        raise SystemExit(f"arvo modules not ready: {e}")
    check_ollama(models)
    if args.set == "wild":
        if args.split != "all":
            print(f"note: --split {args.split} ignored for --set wild (the wild set has no split)", file=sys.stderr)
        args.split = "wild"
    weeks = select_weeks(load_fixtures(args.set), args.split, args.limit)
    if not weeks:
        raise SystemExit("no fixtures: run eval/gen_fixtures.py first" if args.set == "synthetic"
                         else f"no weekNN.gold.json files in {WILD}")
    roster = json.loads(ROSTER_PATH.read_text(encoding="utf-8"))
    RESULTS.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()
    for model in models:
        try:
            res = run_model(model, weeks, roster, args)
        except Exception:  # noqa: BLE001
            traceback.print_exc()
            return 1
        result_paths(model, args.split)[0].write_text(json.dumps(res, indent=1, ensure_ascii=False) + "\n",
                                                      encoding="utf-8")
    path = write_summary(args.split)
    print(path.read_text(encoding="utf-8"))
    print(f"total wall time {time.perf_counter() - t0:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
