---
title: 'Gemma 4 reads, code decides: offline NDIS invoicing that caught 20 of 22 restraints'
published: false
tags: devchallenge, hf26challenge, gemma, opensource
---

*This is a submission for the [Hacktoberfest Open-Source AI Challenge Week 2: Side Hustle](https://dev.to/challenges/hacktoberfest-week2-2026-10-12)*

## What I Built

Sunday night in Melbourne. Mel has four participants and a phone full of notes like this:

```
Tues (Cup day!!) - Jake 3 till 8:30ish. Footy training then tea at his place.
Locked the pantry so he would stop snacking before dinner, he was pretty upset about it.
```

Mel is not a real person; she is a composite from published rate guides and NDIS Commission material. The job is real: an independent NDIS support worker on an ABN, unpaid for the hours it takes to turn that diary into invoices. That line holds two traps.

**The price.** Melbourne Cup Day is a public holiday in Melbourne and most of Victoria, and in no other state, so all 5.5 hours go on the public-holiday item at $163.46 an hour, not the weekday $73.58. On an ordinary Tuesday the shift crosses 8pm and the whole support takes the higher rate; splitting at 8pm underclaims.

**The pantry.** Locking a pantry to stop someone snacking is an environmental restraint under the NDIS (Restrictive Practices and Behaviour Support) Rules 2018. For a registered provider, unauthorised use is a reportable incident: 5 business days to notify the NDIS Commission, 24 hours if it caused harm. An unregistered sole trader like Mel may not use one at all, and the Commission asks for it to be raised with them. Either way it reads like an ordinary note; Mel would have invoiced it and moved on.

Arvo does the Sunday-night job and asks the awkward question. Type, photograph or dictate the week; get back invoice lines a plan manager will accept, a printable invoice per participant, a CSV, and a red flag quoting the exact sentence with a notify-by date. Gemma 4 runs through Ollama on the worker's laptop; nothing is sent anywhere.

**Who pays.** Independent ABN support workers, at a proposed $12 a month or $99 a year. The platforms that already do NDIS invoicing are priced for agencies: [ShiftCare](https://shiftcare.com/pricing) charges per user and says "All plans start at a minimum of five staff". Her alternative is a spreadsheet and an unbilled hour.

## Demo

{% embed https://youtu.be/dQX90blcKEU %}

The video is silent; the captions tell the story.

Live demo page (a saved real run, no install): https://otto-deviant1904.github.io/arvo/

![Screen recording: diary in, button pressed, red flag panel, shifts and invoice lines out](https://raw.githubusercontent.com/Otto-Deviant1904/arvo/main/docs/img/arvo-demo.gif)

*13.6 seconds from button to invoices (the wait is sped up; the button's counter is real).*

The page is `docs/demo/run.json` rendered: `gemma4:e4b` on `docs/demo/diary.txt`, 7 shifts, 10 invoice lines, 3 flags, 13.3 seconds on a laptop RTX 4050 (6 GB). Your own diary: `ollama pull gemma4:e4b` (6.6 GB), clone, `python -m arvo serve`. Python 3.12 standard library, nothing else.

![The flag panel: the pantry note as an unauthorised environmental restraint, registered-provider notify-by date Tue 10 November 2026; PRN and bed rails flagged as authorised, record only](https://raw.githubusercontent.com/Otto-Deviant1904/arvo/main/docs/img/flags.png)

That week is all right, and I had seen it while building; the held-out numbers are below.

## Code

{% github Otto-Deviant1904/arvo %}

MIT. One shape:

```
diary text ─┐
photo ──────┼─> Gemma 4 reads ─> shifts (who, date, start, end, km) ─> code checks fields against the diary
voice memo ─┘                                                                      │
        invoice lines, printable invoice, CSV <─ pricing from the official JSON <──┘
                                                 (band, Vic holiday, s2.4(c), item number)

each note ─> Gemma 4 reads ─> possible restrictive practice ─> quote must be in the note, or dropped ─> notify-by date
```

`arvo/extract.py` and `arvo/rp.py` make the two model calls; `pricing.py`, `calendar_au.py` and `prices.py` are the rules, fed by `data/ndis_prices_2026_27.json`, where every figure cites a document and page; `voice.py` hands audio to Gemma 4 directly; `server.py` plus one HTML file, on 127.0.0.1; `eval/` holds every fixture, gold label and result, frozen under SHA-256 sums.

## How I Built It

### The model reads, code decides

Gemma turns messy text into shifts and never picks a price, an item number or a deadline. For Nonna's Thursday evening its entire contribution is `{"participant_id": "nonna", "date": "2026-11-05", "start": "19:00", "end": "21:30"}`. The band, the item number and the $202.68 are code reading the Schedule. The model never saw a dollar sign.

![What Gemma read from the demo diary, with the span each time came from, above the invoice lines code priced](https://raw.githubusercontent.com/Otto-Deviant1904/arvo/main/docs/img/shifts-invoice.png)

The rule that matters most is s2.4(c) of the NDIS Pricing Schedule 2026-27 (p5): "Where a support a support crosses between different times of day or days of week and is delivered by a single worker, the higher of the amounts applies to the whole support." (The doubled words are in the official PDF.) In Arvo it is a test, not a prompt:

```python
def test_crosses_8pm_whole_shift_at_evening_not_split(roster):
    ln, _ = only(roster, "priya", "2026-10-14", "15:00", "20:30")
    # 5.5 x 81.07 = 445.885 -> ROUND_HALF_UP 445.89 (float round() would give 445.88)
    assert (ln.item_number, ln.quantity, ln.unit_price, ln.total) == (SELF["weekday_evening"], 5.5, 81.07, 445.89)
    assert ln.rule.startswith("Crosses 8pm: whole shift at Weekday Evening rate")
    assert "s2.4(c)" in ln.rule
```

Flags get the same split. Gemma must return its evidence as a sentence copied from the note, and `find_verbatim` checks it is there; if not, the flag is dropped with a warning. A model that paraphrases is a model that can invent.

### Synthetic data, held-out tests

No real participant data anywhere. 24 template weeks come from `eval/gen_fixtures.py`, gold from the generator, never a model. 8 "wild" weeks were written by another AI agent imitating tired people (run-on prose, unpunctuated dictation, strike-throughs, "odo 45213 to 45231"); a second model labelled them blind and agreed on 58 of 58 shifts. 42 restrictive-practice notes came from another agent; a test fails if any 5-word run of one appears in the prompt. Voice memos are Piper TTS. Prompts and code were tuned on 8 dev weeks only; everything else ran once on code frozen at tag `eval-freeze-1`.

| Held-out set | Arvo (Gemma 4 e4b reads, code prices) | Baselines |
|---|---|---|
| Test split: 16 template weeks, 119 shifts | 93.3% shifts exact; 10/16 weeks right to the cent | code-only parser 91.6%, 9/16; Gemma pricing the week itself 0/16, line recall 49.5% |
| Wild diaries: 8 weeks, 58 shifts | 75.9% exact; $121 mean error per week; 2/8 to the cent | code-only 39.7%, $1,207 per week, 0/8; Gemma alone $366 per week, 0/8 |
| Restrictive-practice notes: 42 (22 restraints, 20 innocent with trap words) | detection F1 88.9% (precision 87.0%, recall 90.9%); 1/20 innocent flagged | keyword list F1 45.7%, 5/20 flagged; `gemma4:e2b` F1 41.4% |
| Photos of a paper diary: 4 weeks | 90.0% exact; 2/4 to the cent | `gemma4:e2b` 76.7%, 1/4 |
| Voice memos: 10, voice never used in development | 6/10 every field right; participant, date, start 10/10; word error rate 12.0% | (memos I tuned on: 11/12) |

The first row embarrassed me: a hand-written parser with no model nearly matches Gemma on the template weeks (91.6% against 93.3%) with lower dollar error ($132 a week against $195). The templates were too regular to prove anything. The wild row is where the model earns its keep, and the notes are where size matters: e2b reads shifts almost as well as e4b (89.1% against 93.3%) and misses 16 of 22 restraints. Size buys judgement, not transcription.

### My guardrails overruled right answers

Arvo got 14 of 58 wild shifts wrong. Read one by one, 7 were my own code overwriting a value Gemma had right, and code invented 2 phantom shifts out of the worker's corrections (`~~12~~ 16km` read as a 12-16 shift; `10-2. actually 10-1` split in two). What it said, against what was true:

- `tom 9 30 till 1 30` (wild week 2, dictated). Gemma: 09:30-13:30, right. My parser took "9" and "1" as the hours and wrote 09:00-13:00 over it: `start set to 09:00 from '9 30 till 1 30' (model said 09:30)`.
- `twenty two k` (same week). Gemma: 22 km, right. Code found no "22" in the diary and zeroed it.
- `odo 61044 to 61058` (week 7). Gemma: 10 km. True: 14. Code zeroed that too.
- `pri 9:30 to 12:15pm Sundy` (test week 18). Gemma: Sunday 31 January, right. Code did not know "Sundy", fell back to the heading `29/1 - Priya` and moved the shift to Friday, which changes the rate.
- "Gave Jake his usual night meds at 8 off the chart". Gemma: chemical restraint. True: innocent; "off the chart" means read off the medication chart.
- "I left her out on the back verandah with the screen door latched for an hour". Gemma: environmental restraint. True: a restraint, but seclusion.
- Same 42 notes, `gemma4:e2b`: 6 of 22 restraints found, 16 missed.
- Held-out voice, end times spoken as "half 11", "half 4" and "half 5": heard right in the transcript, end time wrong on all three. A car-noise memo came out as "Massdenic Copper".

The guardrails exist because a model can invent a time or a km figure; tuned on 8 template weeks, they were overconfident. The fix is a principle: code overrules the model only when its own reading is unambiguous and the model's value is impossible; otherwise the model's value stands and the disagreement becomes a warning the worker sees.

| | Frozen (held out) | After the fix (not held out) |
|---|---|---|
| Test split, exact shifts | 93.3% | 95.0% |
| Test split, weeks right to the cent | 10/16 | 11/16 |
| Wild, exact shifts | 75.9% | 94.8% |
| Wild, weeks right to the cent | 2/8 | 7/8 |
| Wild, mean $ error per week | $121 | $68 |
| Voice memos with every field right | 6/10 | 8/10 |

The right-hand column is not held out: I fixed the code while looking at those exact diaries, so the wild number is the one I trust least. Two things got worse, the cost of the rule (`eval/results/postfix/`).

### What the check can't see

The verbatim-quote check proves the sentence exists in the note, nothing more. It cannot tell that the screen door was seclusion, not environmental restraint, or that "off the chart" is no restraint at all. On the 42 held-out notes it dropped 0 flags: a floor against invention, not evidence of judgement. Pricing is the same: code prices to the cent, but only the shift it is given. Move Priya's Sunday to Friday and the arithmetic is perfect and the invoice is wrong. So the worker sees every shift Gemma read, with its span, before any invoice.

### The document that did not exist

I went looking for the 2026-27 "Pricing Arrangements and Price Limits", the PAPL, where the time-band and travel rules have always lived. There is none: for 2026-27 the NDIA published a prices-only Pricing Schedule, and ndis.gov.au still lists the 2025-26 PAPL v1.1 as current guidance. So the boundary rule comes from the Schedule (s2.4(c), p5), the km rules from the 2025-26 PAPL, and the JSON records the document and page for each figure. If a plan manager disputes a line, the argument is about a page, not about what a model was thinking.

**Limits.** Victoria, non-remote, standard-intensity self-care and community-access items only; 42 notes is a small set. The 5-business-day duty belongs to registered providers; an unregistered sole trader must not use regulated restrictive practices at all, and no official source gives her a deadline, so Arvo labels the date as the registered provider's and gives her the Commission's contact details. It flags; it does not decide. Not legal or compliance advice.

Data and credits: NDIS Pricing Schedule 2026-27 and NDIS Commission material; Business Victoria public holidays; Gemma 4 via Ollama; Piper voices for the synthetic memos; Comic Neue for the synthetic diary photos.

## Why Does Open Innovation Matter?

Shift notes are health information, "sensitive information" under [s 6 of the Privacy Act](https://www.legislation.gov.au/C2004A03712/latest/text), and the [OAIC recommends](https://www.oaic.gov.au/privacy/privacy-guidance-for-organisations-and-government-agencies/guidance-on-privacy-and-the-use-of-commercially-available-ai-products) not entering personal information into publicly available generative AI tools. A worker who pastes "Gave PRN lorazepam 0.5mg" and a name into a hosted chatbot has a problem before she has an invoice. With open weights the model runs on her laptop, the server binds to 127.0.0.1, and nothing leaves. That is the product, not a feature of it.

Where a closed model would win: a frontier model would likely read "9 30 till 1 30" and "half 4" better than a 4B model, and might tell seclusion from environmental restraint. It would still need the same pricing code, because right-to-the-cent is a rules job, and it would send disability health notes to someone else's server. That is the trade; for this job I take the local side.

Open also means offline, where the memo gets recorded; $0 a week in tokens behind a $12 subscription; and a model swap that is one flag, which is how I learned e2b reads nearly as well and judges much worse.

## My Agent Session

I gave Claude Code the challenge page and one instruction: pick an extremely niche idea with a "war council" of agents and build it end to end, with no input from me. Then I was away for the afternoon. Six seats brainstormed through different lenses (privacy, Australian paying customer, wild niche, story, small multimodal models, plus a scout of what was already entered); four of the five idea seats landed on the NDIS independently. Agents then built extraction, pricing, UI, eval and voice in parallel against one spec, ran the evals and drafted this post. When I got back I directed the video. Log: `JOURNEY.md`.

[TODO: one line on what you reviewed or changed yourself]

## Prize Categories

**Best Use of Gemma.** Gemma 4 (`gemma4:e4b` and `gemma4:e2b`, open weights) through Ollama on the worker's machine, for typed text, photos of a paper diary (vision) and voice memos (audio in, no separate speech model). The held-out eval above is the case for it, including where it loses.

**Best Use of GitHub Copilot.** The category text says "automate your project with GitHub Actions". `ci.yml` runs the tests on every push; `gemma-smoke.yml` installs Ollama on a CPU-only runner, pulls `gemma4:e2b` and runs the whole pipeline and a one-week eval with no GPU and no key: [run 38347559687](https://github.com/Otto-Deviant1904/arvo/actions/runs/38347559687). I did not use the Copilot coding agent.
