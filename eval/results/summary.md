# Arvo eval summary

Synthetic diaries from `eval/gen_fixtures.py` (seeded); gold labels come from the generator, never a model. Gold invoice lines = gold shifts priced by `arvo.pricing`. RP is screened on the gold notes. Re-run: `uv run --with pillow python eval/run_eval.py --models ...`.

## Shift extraction (typed diary text)

| model | weeks | gold/pred shifts | recall | precision | participant | date | start | end | km | exact shift |
|---|---|---|---|---|---|---|---|---|---|---|
| gemma4:e4b | 2 | 19/17 | 89.5% | 100.0% | 89.5% | 89.5% | 89.5% | 84.2% | 68.4% | 63.2% |

Exact-shift rate by shift kind:

| model | saturday | sunday | weekday_cross_20 | weekday_day | weekday_evening |
|---|---|---|---|---|---|
| gemma4:e4b | 100.0% (n=1) | 100.0% (n=2) | 100.0% (n=2) | 53.8% (n=13) | 0.0% (n=1) |

## Invoice lines (exact on participant, date, item, quantity, total)

| system | weeks | line precision | line recall | weeks total right to the cent | weeks all lines right | mean abs $ error / week | total abs $ error |
|---|---|---|---|---|---|---|---|
| gemma4:e4b reads, code prices (Arvo) | 2 | 96.2% | 78.1% | 0/2 | 0/2 | $249.90 | $499.79 |
| gemma4:e4b alone (model prices) | skipped (--skip-baseline) | | | | | | |

## Restrictive-practice flags (on gold notes)

Detection = any regulated RP (authorised or not). Needs reporting = RP not authorised in the BSP (a flag predicts it when authorised_in_bsp is false). Matched on (participant, date, type).

| system | detection P | detection R | detection F1 | needs-reporting P | needs-reporting R | needs-reporting F1 | note-level F1 (any type) | hard negatives flagged | dropped by quote check |
|---|---|---|---|---|---|---|---|---|---|
| gemma4:e4b | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 0/3 | 0 |
| keyword baseline | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 1/3 | n/a |

Detection F1 by type:

| system | seclusion | chemical | mechanical | physical | environmental |
|---|---|---|---|---|---|
| gemma4:e4b | n/a (0/0) | n/a (0/0) | n/a (0/0) | 100.0% (1/1) | n/a (0/0) |
| keyword baseline | n/a (0/0) | n/a (0/0) | n/a (0/0) | n/a (0/1) | n/a (0/0) |

## Latency (seconds, this machine)

| model | extract / diary mean | p95 | RP / note mean | p95 | photo / diary mean | p95 | model-alone / diary mean | wall time |
|---|---|---|---|---|---|---|---|---|
| gemma4:e4b | 9.85 | 10.38 | 0.51 | 1.20 | n/a | n/a | n/a | 29.4 |
