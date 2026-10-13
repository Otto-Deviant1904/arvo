# Arvo eval summary: wild set (eval/wild, held out)

The wild set is held out: it was never used for tuning and was run once at the end.

Diaries and gold from `eval/wild/` (gold written by hand, not by a model). Gold invoice lines = gold shifts priced by `arvo.pricing`. RP is screened on the gold notes. `code-only` = the deterministic extractor with no model (no RP, photo or model-alone numbers). Re-run: `uv run --with pillow python eval/run_eval.py --set wild --models ...`.

## Shift extraction (typed diary text)

| model | weeks | gold/pred shifts | recall | precision | participant | date | start | end | km | exact shift |
|---|---|---|---|---|---|---|---|---|---|---|
| code-only | 8 | 58/30 | 48.3% | 93.3% | 51.7% | 48.3% | 51.7% | 44.8% | 46.6% | 39.7% |
| gemma4:e2b | 8 | 58/63 | 87.9% | 81.0% | 93.1% | 91.4% | 93.1% | 84.5% | 81.0% | 65.5% |
| gemma4:e4b | 8 | 58/58 | 89.7% | 89.7% | 93.1% | 91.4% | 91.4% | 86.2% | 84.5% | 75.9% |

Exact-shift rate by shift kind:

| model | public_holiday | saturday | sunday | weekday_cross_20 | weekday_day | weekday_evening |
|---|---|---|---|---|---|---|
| code-only | 37.5% (n=8) | 44.4% (n=9) | 28.6% (n=7) | 25.0% (n=4) | 41.4% (n=29) | 100.0% (n=1) |
| gemma4:e2b | 62.5% (n=8) | 77.8% (n=9) | 71.4% (n=7) | 50.0% (n=4) | 62.1% (n=29) | 100.0% (n=1) |
| gemma4:e4b | 75.0% (n=8) | 88.9% (n=9) | 71.4% (n=7) | 50.0% (n=4) | 75.9% (n=29) | 100.0% (n=1) |

## Invoice lines (exact on participant, date, item, quantity, total)

| system | weeks | line precision | line recall | weeks total right to the cent | weeks all lines right | mean abs $ error / week | total abs $ error |
|---|---|---|---|---|---|---|---|
| code-only reads, code prices (Arvo) | 8 | 87.2% | 41.4% | 0/8 | 0/8 | $1207.34 | $9658.74 |
| code-only alone (model prices) | n/a (code-only) | | | | | | |
| gemma4:e2b reads, code prices (Arvo) | 8 | 82.4% | 75.8% | 1/8 | 1/8 | $260.42 | $2083.39 |
| gemma4:e2b alone (model prices) | 8 | 30.3% | 33.3% | 0/8 | 0/8 | $8464.24 | $67713.92 |
| gemma4:e4b reads, code prices (Arvo) | 8 | 90.0% | 81.8% | 2/8 | 2/8 | $121.43 | $971.42 |
| gemma4:e4b alone (model prices) | 8 | 67.8% | 59.6% | 0/8 | 0/8 | $365.58 | $2924.66 |

## Restrictive-practice flags (on this split's gold notes)

Detection = any regulated RP (authorised or not). Needs reporting = RP not authorised in the BSP (a flag predicts it when authorised_in_bsp is false). Matched on (participant, date, type).

| system | detection P | detection R | detection F1 | needs-reporting P | needs-reporting R | needs-reporting F1 | note-level F1 (any type) | hard negatives flagged | dropped by quote check |
|---|---|---|---|---|---|---|---|---|---|
| code-only | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a |
| keyword baseline | n/a | n/a | n/a | n/a | n/a | n/a | n/a | 0/0 | n/a |
| gemma4:e2b | n/a | n/a | n/a | n/a | n/a | n/a | n/a | 0/0 | 0 |
| gemma4:e4b | n/a | n/a | n/a | n/a | n/a | n/a | n/a | 0/0 | 0 |

Detection F1 by type (detected/positives):

| system | seclusion | chemical | mechanical | physical | environmental |
|---|---|---|---|---|---|
| code-only | n/a | n/a | n/a | n/a | n/a |
| keyword baseline | n/a (0/0) | n/a (0/0) | n/a (0/0) | n/a (0/0) | n/a (0/0) |
| gemma4:e2b | n/a (0/0) | n/a (0/0) | n/a (0/0) | n/a (0/0) | n/a (0/0) |
| gemma4:e4b | n/a (0/0) | n/a (0/0) | n/a (0/0) | n/a (0/0) | n/a (0/0) |

## Latency (seconds, this machine)

| model | extract / diary mean | p95 | RP / note mean | p95 | photo / diary mean | p95 | model-alone / diary mean | wall time |
|---|---|---|---|---|---|---|---|---|
| code-only | 0.00 | 0.01 | n/a | n/a | n/a | n/a | n/a | 0.0 |
| gemma4:e2b | 8.31 | 23.85 | 0.31 | 0.34 | n/a | n/a | 8.93 | 155.9 |
| gemma4:e4b | 11.34 | 33.50 | 0.40 | 0.49 | n/a | n/a | 10.33 | 196.6 |
