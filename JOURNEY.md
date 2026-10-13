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
