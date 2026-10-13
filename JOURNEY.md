# Journey log

## 2026-10-13: picking the idea (war council)

Week 2 theme: "Side Hustle", build something with open-weight AI that someone would actually pay for.

Six independent AI "council seats" each brainstormed 15-40 ideas through a different lens and returned their top 3:

| Seat (lens) | Top pick | Also proposed |
|---|---|---|
| Privacy / offline is the product | NDIS shift notes: catch unauthorised restrictive practices | family-violence affidavit location-leak finder; Medicare referral validity checker |
| Paying customer realist (Australia) | NDIS support worker: diary to invoice + restrictive-practice flag | partner-visa evidence sorter; EYLF learning stories |
| Wild niche hunter | NDIS invoice vs price-limit pre-checker for plan managers | knitting pattern stitch-count linter; first-printing book identifier |
| Story first | hospitality award wage-theft detector | fiction continuity checker for NDA'd editors; hidden-allergen matrix |
| Technical edge of small multimodal models | chat screenshots to court chronology | NDIS invoice price checker; partner-visa sorter |
| Scout (what is already entered) | n/a | 30 entries in the first 8 hours: receipts x8, Etsy listings x4, zero Australian or care-sector entries |

Four of the five idea seats independently landed on the NDIS (National Disability Insurance Scheme). The scout found nobody building there. The privacy argument is real: shift notes are disability "sensitive information" under the Privacy Act, and the OAIC's guidance is not to put such data into public generative AI tools.

Chosen: the independent support worker's Sunday-night ritual (diary to invoice), with the restrictive-practice flag as the thing a human misses. Name: Arvo (Australian for afternoon, and the word a 4B model has to understand in "arvo till 7ish").

Probe facts (RTX 4050 6 GB, Ollama 0.35): gemma4:e4b warm about 100 tok/s; JSON-schema output is obeyed structurally but field descriptions are ignored, so normalisation happens in code; e4b swapped day and month on a DD/MM date once; only one model fits in VRAM.

## 2026-10-13: building it (one afternoon, parallel agents)

- **Facts first.** A research agent pulled the official NDIS documents. Finding: there is no 2026-27 "Pricing Arrangements and Price Limits"; it was replaced by a prices-only Pricing Schedule 2026-27 (Minister's determination version effective 24 Sep 2026). Every price, band definition and the boundary rule went into `data/ndis_prices_2026_27.json` with document and page. The boundary rule (s2.4(c)) says a single-worker shift crossing bands is claimed whole at the higher band, so 3pm-8:30pm is all evening rate. Restrictive-practice definitions and reporting rules went into `docs/sources/restrictive_practices.md`, including the registered/unregistered distinction.
- **Four builders in parallel**, each owning its own files against `SPEC.md`: LLM layer (`extract.py`, `rp.py`, pipeline, CLI), pricing engine (`pricing.py`, `calendar_au.py`, `prices.py`, `invoice.py`), UI (`server.py`, `web/index.html`), eval harness (`eval/`). Then voice memos (Gemma 4 audio input, Piper TTS fixtures).
- **km decision.** Diary km are driven with the participant, so they are Activity Based Transport (`04_590_0125_6_1`, $0.99/km), not provider travel.
- **Eval design.** 24 synthetic template weeks split dev (1-8) / test (9-24); 42 held-out restrictive-practice notes with a test that fails if any 5-word run of a note appears in the prompts; 8 free-form "wild" weeks written by a different agent, labelled blind by a second model (58/58 agreement); 10 held-out voice memos in an unused voice. Baselines: a code-only parser, a keyword list, and Gemma pricing the week itself.
- **Tuning on dev only.** Dev went from 78.5% to 100% exact shifts. Code frozen at tag `eval-freeze-1`; test, wild, RP and voice sets run once.
- **Held-out results (frozen).** Test 93.3% exact shifts (code-only 91.6%: the templates were too easy); wild 75.9% (code-only 39.7%); Gemma pricing alone 0/16 test weeks right; RP F1 88.9% vs keyword 45.7%, while `gemma4:e2b` collapsed to 41.4%; photos 90.0%; voice 6/10.
- **The lesson.** Reading the wild failures one by one: 7 of the 14 wrong shifts were code guardrails overwriting a value Gemma had right ("twenty two k" zeroed, dictated "9 30 till 1 30" re-parsed as 09:00-13:00, a misspelt "Sundy" sending a shift to the previous heading's day). Fix: code overrules the model only when its own reading is unambiguous and the model's value is impossible; otherwise the model stands and the worker gets a check. Post-fix (not held out): test 95.0%, wild 94.8%, voice 8/10. Frozen results kept with SHA-256 sums in `eval/results/frozen/`.
- **Product correction from review.** The 5-business-day reporting duty belongs to registered providers; an unregistered sole trader must not use restrictive practices at all. The flag now says "Registered provider: notify by" and gives the Commission's contact for unregistered workers.
- **Demo.** A real `gemma4:e4b` run saved to `docs/demo/run.json` for the static page, a 13.6 s live screen recording (`docs/img/arvo-demo.gif`), and a GitHub Actions workflow that runs the whole pipeline on a CPU-only runner with `gemma4:e2b`.
