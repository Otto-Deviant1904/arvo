# Arvo eval

Synthetic, seeded shift diaries with gold labels that come from how the fixtures are generated, never
from a model. Everything here runs offline against the local Ollama server.

```
uv run --with pillow python eval/gen_fixtures.py                 # (re)write eval/fixtures/
uv run --with pillow python eval/run_eval.py --split dev --models gemma4:e4b --limit 2 --skip-baseline   # smoke
uv run --with pillow python eval/run_eval.py --split dev --models gemma4:e4b,gemma4:e2b --images          # tuning loop
uv run --with pillow python eval/run_eval.py --split test --models gemma4:e4b,gemma4:e2b --images --rp-all  # once, at the end
uv run --with pillow python eval/run_eval.py --split test --models code-only,gemma4:e4b    # no-model extractor alongside
uv run --with pillow python eval/run_eval.py --set wild --models code-only,gemma4:e4b      # held-out wild set
uv run --with pytest --with pillow pytest -q tests/test_eval_harness.py
```

## Dev / test split

**Prompts and code were tuned only on dev weeks 1-8; test weeks 9-24 and the RP note set were run once at the end.**

- `--split dev` = weeks 01-08 (photos: weeks 2, 6), `--split test` = weeks 09-24 (photos: weeks 9, 13, 16, 21),
  `--split all` (default) = 01-24. The split is applied before `--limit`. Extraction, invoice lines, photos and
  the RP screen on gold notes all follow the split.
- `--rp-all` also screens all 42 held-out notes in `eval/fixtures/rp_notes.jsonl`, whatever the split, each as
  its own note. This is the held-out RP set: it is never used for tuning. Reported in its own section.
- Results carry the split in their names: `eval/results/<model>_<split>.json`, `eval/results/summary_<split>.md`,
  `eval/results/raw/<model>_<split>/`, so a dev run never overwrites test results. Each summary is built from
  that split's result files only and says the split in its header.

## Fixtures (`eval/fixtures/`)

- `weekNN.txt`: 24 diary weeks (Sun 4 Oct 2026 to Sun 14 Mar 2027), 184 shifts, 5-10 per week, for the
  4 roster participants. The structured shifts are drawn first, then rendered as a tired worker's phone
  note: day names, dates ("the 14th", "14/10"), holiday names ("Cup Day", "Boxing Day"), roster aliases,
  "half 9 to 1", "quarter to 6", "noon", "7ish", 24h weeks, day headings, a "forgot one" line at the end,
  typos, emoji, days off, reminders.
- `weekNN.gold.json`: `{week_ending, shifts: [...], rp: [...]}`. Each shift has the scored fields
  (`participant_id, date, start, end, km`) plus `note`, `kind`, `time_text` (the exact span its times were
  written as), `day_text`, `rp_note_id`.
- `weekNN.png` for weeks 2, 6, 9, 13, 16, 21: the same diary as a phone photo of a ruled paper page
  (Comic Neue handwriting-style font, OFL, in `fonts/`; slight rotation, off-white paper, uneven light).
  Emoji are dropped in the photo; the gold is unchanged.
- `rp_notes.jsonl`: the 42 held-out restrictive-practice notes with labels and where they sit.
- `manifest.json`: counts.

Shift kinds (classified from date and times): weekday daytime 89, crossing 8pm 29, weekday evening 12,
Saturday 19, Sunday 23, public holiday 10, overnight past midnight 2. Public-holiday shifts sit only on
the five target dates (Tue 3 Nov 2026 Melbourne Cup, Fri 25 Dec, Sat 26 Dec, Mon 28 Dec additional day,
Tue 26 Jan 2027 Australia Day), checked against `data/vic_public_holidays.json`. The other Victorian
holidays inside the window (Fri 1 Jan, Mon 8 Mar 2027) are left empty on purpose. 8 weeks have one
participant twice on the same day. km 0-40.

### How "exactly derivable" is enforced

Every shift's `time_text` is re-read by `gen_fixtures.parse_range`, which implements one written-down
convention: am/pm, 24h, noon/midday/midnight are taken as written; a bare start hour is only ever written
for 07:00-17:00 (7-11 morning, 12 noon, 1-5 afternoon); a bare end is the first matching clock time after
the start ("3 till 8:30" = 15:00-20:30, "7pm - 1" = 19:00-01:00 next day); "ish" is gold at the stated
time. Every joiner split must give the same single reading. The generator refuses to write a range that
fails this, and the tests re-check every committed fixture.

### Restrictive-practice notes (held out)

20 unauthorised positives (4 each: seclusion, chemical, mechanical, physical, environmental; 4 mention
harm), 2 authorised regulated RPs (Priya's PRN lorazepam as per her plan, Nonna's bed sides up as per her
plan: `is_rp: true, authorised_in_bsp: true`), and 20 hard negatives that are not restrictive practices at
all, many with keyword traps ("the hardware shop had already locked up", "strapped her new watch on",
"bathroom door locked for privacy, he unlocked it himself", "seatbelt"). Wording is written for this eval
and avoids the example scenarios in `arvo/rp.py`'s prompt and the example phrasings in
`docs/sources/restrictive_practices.md`; `tests/test_eval_harness.py` fails if any 5-word run of a held-out
note appears in the prompt source. Each note sits on exactly one shift for its participant and day.

## `code-only` and the wild set

- `--models code-only` is a pseudo-model: extraction runs `arvo.extract.extract_shifts_code_only(diary_text,
  roster, week_ending)` (deterministic, no LLM). Its RP, photo and model-alone columns are `n/a`; the keyword
  RP baseline is still reported. It can be mixed with real models in one run (`--models code-only,gemma4:e4b`).
- `--set wild` (default `synthetic`) reads `eval/wild/weekNN.txt` + `weekNN.gold.json` (same gold shape as the
  synthetic set; `kind` may be missing, in which case it is derived from date, times and
  `arvo.calendar_au` with the generator's rules, or `n/a`). The wild set has no split: `--split` is ignored, it is
  held out, never used for tuning, and run once at the end. Results go to `eval/results/<model>_wild.json` and
  `eval/results/summary_wild.md`.

## Metrics (`eval/run_eval.py`)

- **Extraction**: gold and predicted shifts are matched one-to-one greedily (same participant + date first,
  ranked by time overlap; then pairs where only one of participant/date agrees but times overlap, so a
  wrong name or day still counts against that field). Recall/precision count only same-participant,
  same-date matches. Field accuracy (participant, date, start, end, km within 0.05) and exact-shift rate are
  over gold shifts; unmatched gold shifts count as wrong on every field. Also exact rate by shift kind.
- **Invoice lines**: gold lines = gold shifts priced by `arvo.pricing`; predicted lines = predicted shifts
  priced the same way. A line matches on (participant, date, item, quantity, total). Per week: the absolute
  dollar error of the week's total, whether it is right to the cent, whether every line is right.
- **Model-alone baseline** (`baselines.model_alone_lines`): one call per diary with the same diary, roster,
  week dates (with Victorian holiday names), and the NDIS price table (items, verbatim band definitions,
  boundary rule, and the km item/rate the engine uses), asked to write the lines itself. Same line metrics.
- **RP**: `arvo.rp.screen_notes` on the GOLD shifts (so RP is not confounded by extraction), matched on
  (participant, date, type). Two sets: (1) detection of any regulated RP, (2) needs reporting = RP and not
  authorised (a flag predicts it when `authorised_in_bsp` is false). P/R/F1 overall and per type, a
  note-level any-type score, hard negatives flagged, harm accuracy on detected notes, authorised notes
  marked authorised, and flags dropped by the verbatim-quote check (from rp's warnings).
- **Keyword baseline** (`baselines.keyword_screen`): a regex list built from the five NDIS definitions
  and obvious terms (lock, restrain, strap, belt, PRN, sedat, confined, shut in, held down, not allowed...).
  It was written once before any eval run and is frozen; tuning it on these notes would be dishonest.
  Authorised = the participant's BSP text maps to the same type.
- **Photos** (`--images`): extraction and invoice metrics on the 6 PNGs.
- **Latency**: wall seconds per diary (extraction, photo, model-alone) and per note (RP, from the per-call
  timings in rp's meta), mean and p95, plus total wall time.

Outputs: `eval/results/<model>_<split>.json`, `eval/results/summary_<split>.md` (built from every results
JSON of that split, so a `--limit` smoke result shows its week count), raw predictions per week in
`eval/results/raw/<model>_<split>/` (gitignored). A week whose model call errors scores as all-missed and is listed under errors.

## Limits worth stating in the post

The diaries are synthetic and written by the same person who wrote the convention above; real diaries are
messier. 42 RP notes is a small set: one note moves a per-type F1 by a lot. The photo set is rendered, not
photographed. Gold invoice lines inherit any bug in `arvo.pricing` (the line metrics measure what
extraction errors cost, not whether the engine is right).

## Wild set label check

The wild gold (`eval/wild/weekNN.gold.json`) was written by one AI agent from the diary texts it wrote. A second agent, a different model that saw only the diary texts, the roster and the holiday list (never the gold), labelled all 8 weeks blind: `eval/wild/second_annotator/`. The two agreed on 58 of 58 shifts on every scored field (participant, date, start, end, km). Ambiguities the second annotator noted ("till about 4", "pree" for Pri, "Yesterday I also forgot ...") were resolved the same way by both.
