# Arvo: build spec (internal, for the build agents)

## Product in one paragraph
Arvo is an offline tool for Australian NDIS independent support workers (ABN sole traders, Victoria first). On Sunday night the worker pastes or photographs their messy shift diary for the week ("Tues - Jake 3 till 8:30ish, Bunnings + footy, 12km"). Arvo returns:
1. claim-ready invoice lines per participant (support item number, date, start/end, hours, unit price, total, km line), priced by deterministic code against the official NDIS price limits and the Victorian public-holiday calendar;
2. a red flag when a shift note describes a possible restrictive practice ("locked the pantry so he'd stop snacking" = environmental restraint), with the verbatim evidence sentence and the reporting deadline;
3. a printable invoice per participant (HTML) plus CSV.
Everything runs locally on Gemma 4 (gemma4:e4b via Ollama). No diary text leaves the laptop. Rule: **the model reads, code decides**. The model never picks a price or an item number.

## Layout (who owns what; do not edit files you do not own without asking the orchestrator)
```
arvo/models.py        shared dataclasses (orchestrator; read-only for agents)
arvo/llm.py           Ollama client: chat(model, messages, schema, images) -> (parsed_json, meta)        [agent LLM]
arvo/extract.py       diary text or image -> list[Shift] (Gemma + code validation)                       [agent LLM]
arvo/rp.py            shift note -> list[RPFlag] (Gemma + verbatim-quote check + deadline via calendar)  [agent LLM]
arvo/prices.py        load data/ndis_prices_2026_27.json, look up items                                 [agent ENGINE]
arvo/calendar_au.py   Vic public holidays, business-day arithmetic                                       [agent ENGINE]
arvo/pricing.py       Shift + Participant -> list[InvoiceLine] (time bands, boundary rule, PH, km)      [agent ENGINE]
arvo/invoice.py       lines -> invoice HTML per participant + CSV                                        [agent ENGINE]
arvo/pipeline.py      run(diary_text|image_path, roster, week_ending, model) -> RunResult                [agent LLM]
arvo/cli.py           `python -m arvo process|serve|eval`                                                [agent LLM]
arvo/server.py        stdlib http.server: serves web/ and POST /api/run                                  [agent UI]
web/index.html        single-file UI: paste diary or drop photo, see lines + flags + invoice. Has a
                      demo mode that loads docs/demo/*.json when no backend is reachable                 [agent UI]
docs/                 GitHub Pages copy of web/ + precomputed demo JSON                                  [agent UI]
data/                 ndis_prices_2026_27.json, vic_public_holidays.json, roster.example.json            [orchestrator]
eval/gen_fixtures.py  programmatic synthetic diaries with gold labels (+ handwriting PNGs)              [agent EVAL]
eval/fixtures/        generated diaries, gold JSON, rp notes set                                         [agent EVAL]
eval/run_eval.py      metrics + baselines, writes eval/results/*.json and a markdown table               [agent EVAL]
tests/                pytest, no network, no Ollama (use a fake LLM)                                     [each agent tests its own modules]
.github/workflows/    ci.yml (pytest), gemma-smoke.yml (workflow_dispatch: ollama + gemma4:e2b smoke)   [orchestrator]
```

## Hard rules
- Python >= 3.12. Core package `arvo/` is **stdlib only** (urllib for Ollama). Pillow allowed only in `eval/gen_fixtures.py`. pytest for tests. Run with `uv run --with pytest pytest -q`.
- Ollama at `http://localhost:11434`, default model `gemma4:e4b`, `options.temperature=0`, `"think": false`, structured output via the `format` JSON schema. Images go as base64 in `messages[].images`.
- Only ONE process should hammer the GPU at a time (6 GB VRAM). Keep probes short; the big eval run is done by the EVAL agent when told.
- All dates ISO, all times 24h HH:MM, money rounded to cents with `round(x + 1e-9, 2)` semantics, Decimal if you prefer.
- Every price, item number and band definition comes from `data/ndis_prices_2026_27.json` (sourced from the official NDIS Pricing Arrangements and Price Limits 2026-27). Never hardcode a dollar figure in code.
- No new frameworks (no FastAPI, no React, no LangChain). No accounts, no API keys, no network calls other than localhost Ollama.

## Out of scope (do not build)
Plan-manager portals, PRODA/myplace submission, auth, databases, multi-user, payroll, GST logic beyond "GST-free", remote/very-remote pricing, non-Victorian holidays, progress-note generation, Docker.

## Done means
- `uv run --with pytest pytest -q` green, pasted output as the receipt.
- `python -m arvo process eval/fixtures/<one>.txt --week-ending YYYY-MM-DD --roster data/roster.example.json` prints lines + flags against live gemma4:e4b.
- eval numbers in `eval/results/summary.md`.
