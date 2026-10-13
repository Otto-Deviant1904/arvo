# Arvo

**Sunday-night invoicing for NDIS support workers, on a laptop, with nothing sent anywhere.**

An independent (ABN) NDIS support worker in Victoria types, photographs or dictates their week of shifts the way they actually write them:

```
Tues (Cup day!!) - Jake 3 till 8:30ish. Footy training then tea at his place.
Locked the pantry so he would stop snacking before dinner, he was pretty upset about it.
```

Arvo gives back:

1. **Invoice lines a plan manager will accept.** Support item number, date, hours, rate and total for every shift, priced by code against the official NDIS Pricing Schedule 2026-27 and the Victorian public-holiday calendar. That shift is on Melbourne Cup Day, so the whole 5.5 hours goes on `04_102_0125_6_1` at $163.46/h. The same shift on an ordinary Tuesday crosses 8pm, so all of it is claimed at the evening rate, not split (Schedule s2.4(c)).
2. **A red flag for the sentence that matters.** "Locked the pantry so he would stop snacking" is an environmental restrictive practice. Used without authorisation it is a reportable incident: the provider has 5 business days, or 24 hours if someone was hurt. Arvo quotes the exact sentence and works out the report-by date. A PRN given *as per the behaviour support plan* is flagged too, but as authorised: record it, no report needed.
3. **A printable invoice per participant**, plus CSV.

Everything runs on **Gemma 4** (`gemma4:e4b`, open weights) through [Ollama](https://ollama.com) on the worker's own machine. Shift notes are disability "sensitive information" under the Privacy Act. They never leave the laptop.

**The model reads, code decides.** Gemma turns messy text, a photo of a paper diary, or a voice memo into structured shifts, and reads each note for restrictive practices. It never picks a price, an item number or a deadline. Those come from `data/ndis_prices_2026_27.json` (every figure cited to the official document and page) and `arvo/pricing.py`.

> Arvo flags, it does not decide. It is not legal or compliance advice; talk to your provider or the NDIS Commission.

## Try it

**Demo (no install):** https://otto-deviant1904.github.io/arvo/ shows a saved run of Gemma on a real week. *(Live once the repo is public; see `SUBMIT_CHECKLIST.md`.)*

**Run it on your laptop:**

```bash
# 1. Ollama + the model (about 7 GB; runs on a 6 GB laptop GPU or on CPU)
ollama pull gemma4:e4b

# 2. The app: stdlib Python 3.12+, no other dependencies
git clone https://github.com/Otto-Deviant1904/arvo && cd arvo
python -m arvo serve                 # open http://127.0.0.1:8765
```

Or from the terminal:

```bash
python -m arvo process docs/demo/diary.txt --week-ending 2026-11-08
python -m arvo process diary-photo.jpg --week-ending 2026-11-08
python -m arvo process memo1.m4a memo2.m4a --week-ending 2026-11-08   # voice memos, one per shift
```

Put your own participants in a roster file shaped like `data/roster.example.json` and pass `--roster`.

## How it works

```
diary text ─┐
photo ──────┼─> Gemma 4 e4b ──> shifts (JSON schema) ──> code checks ──> pricing.py ──> invoice lines
voice memo ─┘   (Ollama, local)     who / day / times       dates in the week,     bands, holidays,
                                     / km / own words         times re-read from     boundary rule,
                                                              the diary, km stated   official prices
each shift note ──> Gemma 4 e4b ──> possible restrictive practice ──> quote must be verbatim ──> report-by date
                                    (5 regulated types)                in the note, or dropped     (business days, Vic holidays)
```

- `arvo/extract.py`: one model call per week. Code then checks every field against the diary: the date must be in the week and agree with the day the worker wrote, times are re-read from the written span ("half 9", "3 till 8:30ish", "1430-1700"), km must actually be written, and the note is the worker's own words.
- `arvo/rp.py`: one model call per note, with the five regulated restrictive-practice types and their official definitions. A flag survives only if its evidence quote is really in the note.
- `arvo/pricing.py`, `arvo/calendar_au.py`, `arvo/prices.py`: the NDIS time bands, the "higher rate applies to the whole support" rule, Victorian public holidays, Activity Based Transport km, 2025-26 prices for back-dated shifts.
- `arvo/voice.py`: Gemma 4 listens to the memo directly (audio input), then the normal text path runs.
- `arvo/server.py` + `web/index.html`: stdlib HTTP server on 127.0.0.1 only, one HTML file, no frameworks.

## Results

RESULTS_PLACEHOLDER

## Data sources

All prices, item numbers, time-band definitions and claiming rules are in `data/ndis_prices_2026_27.json`, each with its source document and page. Public holidays are in `data/vic_public_holidays.json`. Restrictive-practice definitions and reporting timeframes are in `docs/sources/restrictive_practices.md`. The full list is in `docs/sources/SOURCES.md`. Main documents:

- NDIS Pricing Schedule 2026-27 (effective 1 July 2026; Minister's determination version effective 24 September 2026). There is no 2026-27 "Pricing Arrangements and Price Limits" document; travel and km rules come from the PAPL 2025-26 v1.1, which ndis.gov.au still lists as current guidance.
- NDIS Support Catalogue 2026-27.
- NDIS (Restrictive Practices and Behaviour Support) Rules 2018 and NDIS Commission guidance on reportable incidents.
- Business Victoria public holiday list.

Prices change: an award change takes effect 1 December 2026 and the Schedule will be updated. Update the JSON, not the code.

## Limits

- Victoria, non-remote, standard-intensity items for self-care and community access only. No travel-time claims, sleepovers, remote loadings, or other states.
- The tests and evaluation use synthetic diaries and synthetic voices; see `eval/README.md`. A real worker's diary will be messier.
- Restrictive-practice screening is a second pair of eyes. It will miss things and flag things that are fine. A human decides.
- Not affiliated with the NDIA or the NDIS Quality and Safeguards Commission.

## Development

```bash
uv run --with pytest --with pillow pytest -q          # tests, no model needed
uv run --with pillow python eval/run_eval.py --help   # evaluation (needs Ollama)
```

GitHub Actions runs the tests on every push, and a manual workflow (`gemma smoke test`) installs Ollama on a CPU-only runner, pulls `gemma4:e2b` and runs the whole pipeline with no GPU and no API key.

How the project was planned and built: `JOURNEY.md`.

## Credits and licences

- Code: MIT (see `LICENSE`).
- Gemma 4 by Google DeepMind, open weights, run through Ollama.
- Eval voice memos were synthesised with [Piper](https://github.com/rhasspy/piper) voices from [rhasspy/piper-voices](https://huggingface.co/rhasspy/piper-voices): "Jenny (Dioco)" (`en_GB-jenny_dioco`, [dataset terms](https://github.com/dioco-group/jenny-tts-dataset)), `en_GB-alan` (Mimic 3 voice data), and `en_GB-northern_english_male` (OpenSLR 83, CC BY-SA 4.0).
- Comic Neue font (eval photo fixtures): SIL Open Font License, in `eval/fixtures/fonts/`.
- NDIS price data and rules are public information from ndis.gov.au and the NDIS Commission, reproduced with citations.
