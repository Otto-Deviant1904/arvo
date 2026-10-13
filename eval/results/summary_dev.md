# Arvo eval summary: dev split (weeks 01-08)

Prompts and code were tuned only on dev weeks 1-8; test weeks 9-24 and the RP note set were run once at the end.

Synthetic diaries from `eval/gen_fixtures.py` (seeded); gold labels come from the generator, never a model. Gold invoice lines = gold shifts priced by `arvo.pricing`. RP is screened on the gold notes. Re-run: `uv run --with pillow python eval/run_eval.py --split dev --models ...`.

## Shift extraction (typed diary text)

| model | weeks | gold/pred shifts | recall | precision | participant | date | start | end | km | exact shift |
|---|---|---|---|---|---|---|---|---|---|---|
| gemma4:e4b | 8 | 65/65 | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% |

Exact-shift rate by shift kind:

| model | overnight | public_holiday | saturday | sunday | weekday_cross_20 | weekday_day | weekday_evening |
|---|---|---|---|---|---|---|---|
| gemma4:e4b | 100.0% (n=1) | 100.0% (n=2) | 100.0% (n=7) | 100.0% (n=10) | 100.0% (n=7) | 100.0% (n=32) | 100.0% (n=6) |

## Invoice lines (exact on participant, date, item, quantity, total)

| system | weeks | line precision | line recall | weeks total right to the cent | weeks all lines right | mean abs $ error / week | total abs $ error |
|---|---|---|---|---|---|---|---|
| gemma4:e4b reads, code prices (Arvo) | 8 | 100.0% | 100.0% | 8/8 | 8/8 | $0.00 | $0.00 |
| gemma4:e4b alone (model prices) | skipped (--skip-baseline) | | | | | | |

## Restrictive-practice flags (on this split's gold notes)

Detection = any regulated RP (authorised or not). Needs reporting = RP not authorised in the BSP (a flag predicts it when authorised_in_bsp is false). Matched on (participant, date, type).

| system | detection P | detection R | detection F1 | needs-reporting P | needs-reporting R | needs-reporting F1 | note-level F1 (any type) | hard negatives flagged | dropped by quote check |
|---|---|---|---|---|---|---|---|---|---|
| gemma4:e4b | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 0/7 | 0 |
| keyword baseline | 62.5% | 71.4% | 66.7% | 50.0% | 50.0% | 50.0% | 66.7% | 3/7 | n/a |

Detection F1 by type (detected/positives):

| system | seclusion | chemical | mechanical | physical | environmental |
|---|---|---|---|---|---|
| gemma4:e4b | 100.0% (1/1) | 100.0% (2/2) | 100.0% (2/2) | 100.0% (1/1) | 100.0% (1/1) |
| keyword baseline | 100.0% (1/1) | 100.0% (2/2) | 50.0% (1/2) | n/a (0/1) | 50.0% (1/1) |

## Latency (seconds, this machine)

| model | extract / diary mean | p95 | RP / note mean | p95 | photo / diary mean | p95 | model-alone / diary mean | wall time |
|---|---|---|---|---|---|---|---|---|
| gemma4:e4b | 9.10 | 10.84 | 0.48 | 1.16 | n/a | n/a | n/a | 101.6 |
