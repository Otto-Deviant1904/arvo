# Arvo eval summary: test split (weeks 09-24)

Prompts and code were tuned only on dev weeks 1-8; test weeks 9-24 and the RP note set were run once at the end.

Synthetic diaries from `eval/gen_fixtures.py` (seeded); gold labels come from the generator, never a model. Gold invoice lines = gold shifts priced by `arvo.pricing`. RP is screened on the gold notes. `code-only` = the deterministic extractor with no model (no RP, photo or model-alone numbers). Re-run: `uv run --with pillow python eval/run_eval.py --split test --models ...`.

## Shift extraction (typed diary text)

| model | weeks | gold/pred shifts | recall | precision | participant | date | start | end | km | exact shift |
|---|---|---|---|---|---|---|---|---|---|---|
| code-only | 16 | 119/112 | 92.4% | 98.2% | 94.1% | 92.4% | 93.3% | 94.1% | 94.1% | 91.6% |
| gemma4:e2b | 16 | 119/123 | 98.3% | 95.1% | 100.0% | 98.3% | 95.0% | 92.4% | 99.2% | 89.1% |
| gemma4:e4b | 16 | 119/118 | 98.3% | 99.2% | 99.2% | 98.3% | 97.5% | 96.6% | 99.2% | 95.0% |

Exact-shift rate by shift kind:

| model | overnight | public_holiday | saturday | sunday | weekday_cross_20 | weekday_day | weekday_evening |
|---|---|---|---|---|---|---|---|
| code-only | 100.0% (n=1) | 100.0% (n=8) | 83.3% (n=12) | 84.6% (n=13) | 95.5% (n=22) | 91.2% (n=57) | 100.0% (n=6) |
| gemma4:e2b | 100.0% (n=1) | 100.0% (n=8) | 91.7% (n=12) | 84.6% (n=13) | 90.9% (n=22) | 87.7% (n=57) | 83.3% (n=6) |
| gemma4:e4b | 0.0% (n=1) | 100.0% (n=8) | 100.0% (n=12) | 100.0% (n=13) | 95.5% (n=22) | 93.0% (n=57) | 100.0% (n=6) |

## Invoice lines (exact on participant, date, item, quantity, total)

| system | weeks | line precision | line recall | weeks total right to the cent | weeks all lines right | mean abs $ error / week | total abs $ error |
|---|---|---|---|---|---|---|---|
| code-only reads, code prices (Arvo) | 16 | 97.4% | 92.1% | 9/16 | 9/16 | $131.94 | $2111.05 |
| code-only alone (model prices) | n/a (code-only) | | | | | | |
| gemma4:e2b reads, code prices (Arvo) | 16 | 93.1% | 93.6% | 6/16 | 6/16 | $225.35 | $3605.54 |
| gemma4:e2b alone (model prices) | 16 | 35.8% | 30.7% | 0/16 | 0/16 | $742.41 | $11878.63 |
| gemma4:e4b reads, code prices (Arvo) | 16 | 97.0% | 96.5% | 11/16 | 10/16 | $168.21 | $2691.42 |
| gemma4:e4b alone (model prices) | skipped (--skip-baseline) | | | | | | |

## Restrictive-practice flags (on this split's gold notes)

Detection = any regulated RP (authorised or not). Needs reporting = RP not authorised in the BSP (a flag predicts it when authorised_in_bsp is false). Matched on (participant, date, type).

| system | detection P | detection R | detection F1 | needs-reporting P | needs-reporting R | needs-reporting F1 | note-level F1 (any type) | hard negatives flagged | dropped by quote check |
|---|---|---|---|---|---|---|---|---|---|
| code-only | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a |
| keyword baseline | 60.0% | 20.0% | 30.0% | 60.0% | 21.4% | 31.6% | 30.0% | 2/13 | n/a |
| gemma4:e2b | 100.0% | 20.0% | 33.3% | 100.0% | 21.4% | 35.3% | 33.3% | 0/13 | 0 |
| gemma4:e4b | 87.5% | 93.3% | 90.3% | 86.7% | 92.9% | 89.7% | 96.8% | 1/13 | 0 |

Detection F1 by type (detected/positives):

| system | seclusion | chemical | mechanical | physical | environmental |
|---|---|---|---|---|---|
| code-only | n/a | n/a | n/a | n/a | n/a |
| keyword baseline | n/a (0/3) | n/a (0/3) | 0.0% (0/3) | 50.0% (1/3) | 66.7% (2/3) |
| gemma4:e2b | n/a (0/3) | 80.0% (2/3) | n/a (0/3) | 50.0% (1/3) | n/a (0/3) |
| gemma4:e4b | 100.0% (3/3) | 85.7% (3/3) | 80.0% (2/3) | 100.0% (3/3) | 85.7% (3/3) |

## Restrictive-practice flags: held-out note set (all 42 notes in rp_notes.jsonl, any split)

| system | detection P | detection R | detection F1 | needs-reporting P | needs-reporting R | needs-reporting F1 | note-level F1 (any type) | hard negatives flagged | dropped by quote check |
|---|---|---|---|---|---|---|---|---|---|
| code-only | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a |
| keyword baseline | 61.5% | 36.4% | 45.7% | 54.5% | 30.0% | 38.7% | 45.7% | 5/20 | n/a |
| gemma4:e2b | 85.7% | 27.3% | 41.4% | 83.3% | 25.0% | 38.5% | 48.3% | 0/20 | 0 |

Detection F1 by type (detected/positives):

| system | seclusion | chemical | mechanical | physical | environmental |
|---|---|---|---|---|---|
| code-only | n/a | n/a | n/a | n/a | n/a |
| keyword baseline | 40.0% (1/4) | 57.1% (2/5) | 25.0% (1/5) | 40.0% (1/4) | 60.0% (3/4) |
| gemma4:e2b | 40.0% (1/4) | 88.9% (4/5) | n/a (0/5) | 33.3% (1/4) | n/a (0/4) |

## Photos of a paper diary (handwriting-style PNGs in this split)

| model | gold/pred shifts | recall | precision | exact shift | weeks total right to the cent | mean abs $ error / week |
|---|---|---|---|---|---|---|
| code-only | n/a | n/a | n/a | n/a | n/a | n/a |
| gemma4:e2b | 30/33 | 90.0% | 81.8% | 76.7% | 1/4 | $93.89 |
| gemma4:e4b | n/a | n/a | n/a | n/a | n/a | n/a |

## Latency (seconds, this machine)

| model | extract / diary mean | p95 | RP / note mean | p95 | photo / diary mean | p95 | model-alone / diary mean | wall time |
|---|---|---|---|---|---|---|---|---|
| code-only | 0.01 | 0.02 | n/a | n/a | n/a | n/a | n/a | 0.2 |
| gemma4:e2b | 7.17 | 22.95 | 0.33 | 0.36 | 8.46 | 9.21 | 7.29 | 316.7 |
| gemma4:e4b | 8.73 | 11.88 | 0.49 | 1.14 | n/a | n/a | n/a | 193.3 |
