"""Voice-memo eval: Gemma 4 transcription WER vs the TTS script, then end-to-end shift extraction vs gold.

For each voice, the 6 memos go through `pipeline.transcribe_memos` (exactly what `pipeline.run(audio_paths=...)`
does first), then the joined diary goes through `pipeline.run` like a typed week. Writes
eval/voice/results.json and eval/voice/RESULTS.md.

    uv run python eval/voice/run_voice_eval.py [--model gemma4:e4b]

`--set heldout` scores the 10 held-out memos instead (eval/voice/heldout/scripts.json + heldout/audio/,
built by heldout/make_heldout.py) and writes eval/voice/heldout/results.json + RESULTS.md. Do not tune on it.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(REPO))

from arvo import pipeline  # noqa: E402
from arvo.extract import norm_text  # noqa: E402

FIELDS = ["participant", "date", "start", "end", "km", "note", "rp"]

NOTES = """## Notes (read before quoting these numbers)

- Audio is Piper TTS (en_GB alan + jenny_dioco voices), not real phone recordings: clean, fluent, no
  Australian accent, no ums, wind or radio. Car noise is brown noise low-passed at 350 Hz, mixed at
  12 dB SNR on 2 memos. Real-world speech recognition quality is still untested.
- Tuned on this set: the first run headed each memo with its recording date only, and both
  "Priya, yesterday ..." memos (recorded Sunday) came out dated Sunday (date accuracy 0.83; a Sunday
  rate on a Saturday shift). `voice.memo_line` now resolves "yesterday"/"last night" in code and heads
  the line with the shift day. Date 1.00 is therefore not held-out.
- Remaining miss: jenny-6 "eight k's" was heard as "AK's", so km became 0 with no warning; only the
  "heard ..." warning line shows the worker what Gemma heard. Other mishearings ("chopping a chestnut"
  for "shopping at Chadstone", "Physi" for "footy", "No case" for "No k's") did not change any field.
- Transcripts were identical across 3 runs (temperature 0). GPU (RTX 4050 6 GB) was shared with other
  agents, so seconds are indicative."""

HELDOUT_NOTES = """## Notes (read before quoting these numbers)

- Held-out: scripts written after the dev set was frozen, never used to tune prompts or code. Run it once
  per release; if a change is made because of a miss here, this set is no longer held out.
- Audio is Piper TTS (en_GB northern_english_male, a voice the dev set does not use), encoded as
  WhatsApp-style Ogg Opus voice notes. Still clean synthetic speech with no Australian accent. Car noise
  (brown, low-passed at 350 Hz, 12 dB SNR) on 3 memos.
- Week of Christmas 2026: Christmas Day (Fri 25) and Boxing Day (Sat 26) are Victorian public holidays.
  Covers 2 shifts crossing 8 pm, one "last night" memo, one memo with no day spoken, Australian number
  phrasing, 2 restrictive practices (chemical, mechanical) and 2 innocent notes with trap words
  (tablets, locked, held, belt). Tag rows are subsets of these 10 memos (small n).
- Pricing is not scored here; invoice lines are kept in results.json under runs[].lines."""

SETS = {
    "dev": dict(gold=HERE / "gold.json", out=HERE, title="Voice memo eval", notes=NOTES),
    "heldout": dict(gold=HERE / "heldout" / "scripts.json", out=HERE / "heldout",
                    title="Held-out voice memo eval", notes=HELDOUT_NOTES),
}

_UNITS = {w: i for i, w in enumerate("zero one two three four five six seven eight nine ten eleven twelve "
                                     "thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split())}
_TENS = {w: 10 * i for i, w in enumerate("_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()) if i > 1}


def words(text: str, numbers: bool = True) -> list[str]:
    """Lowercase word tokens. numbers=True also maps number words to digits and k's/kms/kilometres to km,
    so "twelve k's" == "12 km" and "two thirty" == "2:30"."""
    t = (text or "").casefold().replace("’", "'").replace("‘", "'")
    t = re.sub(r"[^a-z0-9' ]+", " ", t.replace(":", " "))
    toks = [w.strip("'") for w in t.split() if w.strip("'")]
    if not numbers:
        return toks
    out: list[str] = []
    i = 0
    while i < len(toks):
        w = toks[i]
        if w in _TENS:
            n = _TENS[w]
            if i + 1 < len(toks) and toks[i + 1] in _UNITS and 0 < _UNITS[toks[i + 1]] < 10:
                n += _UNITS[toks[i + 1]]
                i += 1
            out.append(str(n))
        elif w in _UNITS:
            out.append(str(_UNITS[w]))
        elif w in {"k's", "ks", "k", "kms", "km", "kilometres", "kilometers", "kays"}:
            out.append("km")
        else:
            out.append(w)
        i += 1
    return out


def wer(ref: list[str], hyp: list[str]) -> float:
    """Word error rate: Levenshtein distance over words / reference length."""
    prev = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        cur = [i] + [0] * len(hyp)
        for j, h in enumerate(hyp, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (r != h))
        prev = cur
    return prev[-1] / max(1, len(ref))


def note_recall(gold_note: str, note: str) -> float:
    g = [w for w in words(gold_note) if not w.isdigit() and w != "km"]
    have = set(words(note))
    return sum(w in have for w in g) / max(1, len(g))


def score(gold: dict, shift: dict | None, flags: list[dict]) -> dict:
    if shift is None:
        return {f: False for f in FIELDS}
    mine = [f["rp_type"] for f in flags if f["participant_id"] == shift["participant_id"] and f["date"] == shift["date"]]
    return {
        "participant": shift["participant_id"] == gold["participant_id"],
        "date": shift["date"] == gold["date"],
        "start": shift["start"] == gold["start"],
        "end": shift["end"] == gold["end"],
        "km": abs(float(shift["km"]) - float(gold["km"])) < 1e-6,
        "note": note_recall(gold["note"], shift["note"]) >= 0.8,
        "rp": (gold["rp_type"] in mine) if gold["rp_type"] else not mine,
    }


def match(golds: list[dict], shifts: list[dict], flags: list[dict]) -> list[dict | None]:
    """Greedy: each gold shift takes the unused extracted shift that agrees on the most fields."""
    used: set[int] = set()
    out = []
    for g in golds:
        best, best_n = None, 0
        for i, s in enumerate(shifts):
            if i in used:
                continue
            n = sum(score(g, s, flags).values()) + 3 * (s["participant_id"] == g["participant_id"])
            if n > best_n:
                best, best_n = i, n
        if best is not None:
            used.add(best)
        out.append(shifts[best] if best is not None else None)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="gemma4:e4b")
    ap.add_argument("--set", default="dev", choices=sorted(SETS),
                    help="dev: gold.json + audio/ (default); heldout: heldout/scripts.json + heldout/audio/")
    args = ap.parse_args()
    cfg = SETS[args.set]
    gold = json.loads(cfg["gold"].read_text(encoding="utf-8"))
    missing = [m["file"] for m in gold["memos"] if not (HERE / m["file"]).is_file()]
    if missing:
        sys.exit(f"missing audio for {len(missing)} memos (e.g. {missing[0]}); "
                 f"generate it first (heldout/make_heldout.py or make_fixtures.py)")
    roster = pipeline.load_roster(REPO / "data" / "roster.example.json")
    voices: dict[str, list[dict]] = {}
    for m in gold["memos"]:
        voices.setdefault(m["voice"], []).append(m)

    per_memo, runs = [], []
    for voice_name, memos in voices.items():
        paths = [str(HERE / m["file"]) for m in memos]
        t0 = time.perf_counter()
        diary, metas = pipeline.transcribe_memos(paths, roster, args.model, use_mtime=False)
        t1 = time.perf_counter()
        res = pipeline.run(diary, roster, gold["week_ending"], model=args.model).to_dict()
        t2 = time.perf_counter()
        runs.append({"voice": voice_name, "diary": diary, "transcribe_s": round(t1 - t0, 2),
                     "pipeline_s": round(t2 - t1, 2), "timings": res["timings"], "warnings": res["warnings"],
                     "shifts": res["shifts"], "flags": res["flags"]})
        if args.set != "dev":
            runs[-1]["lines"] = res["lines"]
        matched = match([m["shift"] for m in memos], res["shifts"], res["flags"])
        for m, meta, s in zip(memos, metas, matched):
            ref, hyp = m["script"], meta["transcript"]
            per_memo.append({
                "id": m["id"], "voice": voice_name, "noise_snr_db": m["noise_snr_db"],
                "duration_s": meta["duration_s"], "transcribe_s": meta["total_s"],
                "script": ref, "transcript": hyp,
                "wer": round(wer(words(ref), words(hyp)), 4),
                "wer_raw": round(wer(words(ref, False), words(hyp, False)), 4),
                "gold": m["shift"],
                "extracted": None if s is None else {k: s[k] for k in ("participant_id", "date", "start", "end",
                                                                          "km", "note", "warnings")},
                "correct": score(m["shift"], s, res["flags"]),
            })
            if m.get("tags"):
                per_memo[-1]["tags"] = m["tags"]
        print(f"{voice_name}: transcribe {t1 - t0:.1f}s, pipeline {t2 - t1:.1f}s, "
              f"{len(res['shifts'])} shifts, {len(res['flags'])} flags", flush=True)

    n = len(per_memo)

    def mean(xs):
        xs = list(xs)
        return round(sum(xs) / max(1, len(xs)), 4)

    groups = {"all": per_memo,
              "clean": [p for p in per_memo if not p["noise_snr_db"]],
              "car noise": [p for p in per_memo if p["noise_snr_db"]],
              **{v: [p for p in per_memo if p["voice"] == v] for v in voices}}
    for tag in sorted({t.split(":", 1)[0] for p in per_memo for t in p.get("tags", [])}):
        groups[f"tag: {tag}"] = [p for p in per_memo if any(t.split(":", 1)[0] == tag for t in p.get("tags", []))]
    summary = {}
    for g, ps in groups.items():
        summary[g] = {"memos": len(ps), "wer": mean(p["wer"] for p in ps),
                      "wer_raw": mean(p["wer_raw"] for p in ps),
                      **{f: mean(p["correct"][f] for p in ps) for f in FIELDS},
                      "all_fields": mean(all(p["correct"].values()) for p in ps)}
    total_transcribe = sum(r["transcribe_s"] for r in runs)
    total_pipeline = sum(r["pipeline_s"] for r in runs)
    extra = sum(len(r["shifts"]) for r in runs) - n
    summary["timing"] = {
        "transcribe_s_per_memo": round(total_transcribe / n, 2),
        "end_to_end_s_per_memo": round((total_transcribe + total_pipeline) / n, 2),
        "audio_s_per_memo": round(sum(p["duration_s"] for p in per_memo) / n, 2),
        "extra_or_missing_shifts": extra,
    }
    out = {"model": args.model, "week_ending": gold["week_ending"], "summary": summary,
           "memos": per_memo, "runs": runs}
    if args.set != "dev":
        out = {"set": args.set, **out}
    (cfg["out"] / "results.json").write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")

    lines = [f"# {cfg['title']} ({args.model}, {n} Piper TTS memos)", "",
             "WER: lower-cased words, number words mapped to digits and k's/km unified (wer_raw: no mapping). "
             "Fields: extracted shift vs gold after the full text pipeline; note = 80% of gold note words present; "
             "rp = right restrictive-practice type flagged (or none flagged when none).", "",
             "| set | memos | WER | WER raw | participant | date | start | end | km | note | rp | all fields |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for g in groups:
        s = summary[g]
        lines.append(f"| {g} | {s['memos']} | {s['wer']:.3f} | {s['wer_raw']:.3f} | "
                     + " | ".join(f"{s[f]:.2f}" for f in FIELDS) + f" | {s['all_fields']:.2f} |")
    t = summary["timing"]
    lines += ["", f"Mean audio {t['audio_s_per_memo']} s/memo. Transcription {t['transcribe_s_per_memo']} s/memo; "
                  f"end to end (transcribe + extract + RP screen) {t['end_to_end_s_per_memo']} s/memo. "
                  f"Extracted shifts minus gold shifts: {t['extra_or_missing_shifts']}.", "",
              "| memo | noise | WER | wrong fields | transcript |", "|---|---|---|---|---|"]
    for p in per_memo:
        wrong = ", ".join(f for f, ok in p["correct"].items() if not ok) or "-"
        lines.append(f"| {p['id']} | {str(p['noise_snr_db']) + ' dB' if p['noise_snr_db'] else '-'} | "
                     f"{p['wer']:.3f} | {wrong} | {p['transcript'].replace('|', '/')} |")
    lines += ["", cfg["notes"]]
    (cfg["out"] / "RESULTS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines[:4 + 2 + len(groups) + 2]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
