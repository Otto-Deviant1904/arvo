---
title: '"Locked the pantry": the invoice tool that noticed a reportable incident'
published: false
tags: devchallenge, hf26challenge, gemma, opensource
---

*This is a submission for the [Hacktoberfest Open-Source AI Challenge Week 2: Side Hustle](https://dev.to/challenges/hacktoberfest-week2-2026-10-12)*

## What I Built

It is Sunday night in Melbourne's south-east. Mel has four participants, about 25 shifts a fortnight, and a phone full of notes like this one:

```
Tues (Cup day!!) - Jake 3 till 8:30ish. Footy training then tea at his place.
Locked the pantry so he would stop snacking before dinner, he was pretty upset about it.
```

Mel is not a real person: she is a composite built from published rate guides, NDIS Commission material and support workers' public posts about their admin. The job is real. She is an independent NDIS support worker on an ABN. Nobody pays her for the hours it takes to turn that diary into invoices, a wrong item number bounces the invoice at the plan manager, and that one line holds two traps.

**The price.** Melbourne Cup Day is a public holiday in Melbourne and most of Victoria, and in no other state, so all 5.5 hours go on the public-holiday item at $163.46 an hour, not the weekday $73.58. On an ordinary Tuesday the same shift would cross 8pm, and the NDIS Pricing Schedule 2026-27 says, at s2.4(c): "Where a support a support crosses between different times of day or days of week and is delivered by a single worker, the higher of the amounts applies to the whole support." (The doubled "a support a support" is in the official PDF. I have left it.) The whole shift goes at the evening rate. Splitting it at 8pm, the obvious move, underclaims.

**The pantry.** Locking a pantry so someone stops snacking restricts his free access to his own environment. Under the NDIS (Restrictive Practices and Behaviour Support) Rules 2018 that is an environmental restraint, one of five regulated restrictive practices. Used without authorisation it is a reportable incident: 5 business days to notify the NDIS Commission, or 24 hours if it caused harm. It reads like an ordinary shift note, which is the problem. Mel would have invoiced the shift and moved on.

Arvo does the Sunday-night job and asks the awkward question. Type, photograph or dictate the week; get back invoice lines a plan manager will accept, a printable invoice per participant, a CSV, and a red flag that quotes the exact sentence and gives a report-by date. It all runs on Gemma 4 through Ollama on the worker's own laptop. Nothing is sent anywhere.

**Who pays.** Independent ABN support workers, at a proposed $12 a month or $99 a year. The platforms that already do NDIS invoicing are priced for agencies, with per-seat plans and staff minimums a one-person business cannot fill. Her alternative is a spreadsheet, the price schedule PDF, and an hour she does not bill for.

## Demo

https://otto-deviant1904.github.io/arvo/ [TODO: confirm live]

![Arvo's demo page: the week's diary on the left; on the right, 7 shifts, 4 invoices, $3,063.07 to invoice, 3 notes to check, above a red "Check before you invoice" panel](https://raw.githubusercontent.com/Otto-Deviant1904/arvo/main/docs/img/hero.png)

The page shows a saved run of `gemma4:e4b` on the week in `docs/demo/diary.txt`: 7 shifts, 10 invoice lines, 3 flags, 13.3 seconds end to end on a laptop RTX 4050 (6 GB). It calls no model; it is `docs/demo/run.json` rendered. To run your own diary: `ollama pull gemma4:e4b` (about 7 GB), clone, `python -m arvo serve`. Python 3.12 standard library, no other dependencies.

### A worked example

Three lines from the demo week (ending Sunday 8 November 2026):

| Diary line | Gemma reads | Code decides | Invoice line |
|---|---|---|---|
| `Tues (Cup day!!) - Jake 3 till 8:30ish` | jake, 2026-11-03, 15:00-20:30 | Tue 3 Nov 2026 is Melbourne Cup Day, a Victorian public holiday | `04_102_0125_6_1` Public Holiday, 5.5 h x $163.46 = **$899.03** |
| `Thurs night - Mrs B again 7pm-9:30pm` | nonna, 2026-11-05, 19:00-21:30 | Starts before 8pm, ends after it: neither the Daytime nor the Evening definition fits, so s2.4(c) puts the whole support in the higher band | `01_015_0107_1_1` Weekday Evening, 2.5 h x $81.07 = **$202.68** |
| `Sun - T.O. 10-3 ... 22 km` | tom, 2026-11-08, 10:00-15:00, 22 km | Sunday band; km claimed as Activity Based Transport | `04_106_0125_6_1` Sunday, 5 h x $133.50 = **$667.50**, plus 22 km x $0.99 = $21.78 |

![The "Check before you invoice" panel: the pantry note flagged as an environmental restraint, not authorised, report by Tuesday 10 November 2026; the PRN and bed-rail notes flagged as authorised, "record it as the plan says"](https://raw.githubusercontent.com/Otto-Deviant1904/arvo/main/docs/img/flags.png)

The flags for the same week:

- **Red.** "Locked the pantry so he would stop snacking before dinner": environmental restraint, not authorised, report by Tue 10 Nov 2026.
- **Authorised, record only.** "Gave PRN lorazepam 0.5mg as per plan at 11:15" (chemical) and "Bed rails up as per plan" (mechanical) match the authorisations in Priya's and Nonna's roster entries. Still restrictive practices, still shown, no report-by date.
- **Not flagged.** "He asked me to hang onto his phone during the game." Holding a phone because the person asked is not a restraint.

Every line and flag in that week is right. It is one week, and I had seen it while building. The held-out numbers are further down.

## Code

{% github Otto-Deviant1904/arvo %}

MIT licence. The pieces:

- `arvo/extract.py`: one Gemma call per week returns shifts as JSON (participant, date, start, end, km, the worker's own note). Code then checks each field against the diary text.
- `arvo/rp.py`: one Gemma call per note, with the five definitions from s 6 of the Rules. A flag survives only if its evidence quote is really in the note.
- `arvo/pricing.py`, `arvo/calendar_au.py`, `arvo/prices.py`: time bands, the whole-support boundary rule, Victorian public holidays, business-day deadlines, prices from `data/ndis_prices_2026_27.json`.
- `arvo/voice.py`: Gemma 4 listens to a voice memo directly (audio input) and the text path takes over.
- `arvo/server.py` and `web/index.html`: a stdlib HTTP server bound to 127.0.0.1, one HTML file.
- `eval/`: fixtures, gold labels, `run_eval.py`, every result file, frozen copies with checksums.

## How I Built It

### The model reads, code decides

Gemma turns messy text into structured shifts. It never picks a price, an item number or a deadline. Those come from a JSON file in which every figure cites its source document and page, and from `pricing.py`, which implements the Schedule's definitions as written.

Take Nonna's Thursday evening. Gemma's entire contribution is `{"participant_id": "nonna", "date": "2026-11-05", "start": "19:00", "end": "21:30"}`. Code then asks: weekday? Yes. Starts at or after 6am and ends at or before 8pm? No, it ends at 9:30. Starts at or after 8pm? No. It fits neither definition in Part 4 Table 61, so s2.4(c) applies and the whole 2.5 hours goes on the Weekday Evening item at $81.07. The model never saw a dollar sign.

![What Gemma read from the demo diary, row by row with the exact span the times came from, above the invoice lines code priced from it](https://raw.githubusercontent.com/Otto-Deviant1904/arvo/main/docs/img/shifts-invoice.png)

The same split applies to the flags. Gemma must return its evidence as a sentence "copied character for character" from the note, and `find_verbatim` checks that it is. If the quote is not in the note, the flag is dropped and the worker sees a warning saying so. A flag she cannot point to in her own words is one she cannot act on, and a model that paraphrases is a model that can invent. On the 42 held-out notes, 0 flags were dropped by this check.

I measured what happens without the split. Give Gemma e4b the diary, the roster, the week's dates with holiday names and the full price table, and ask it to write the invoice lines itself: 0 of 16 test weeks right to the cent, line recall 49.5%. With code pricing the same model's shifts: 10 of 16 and 95.0%.

### The evaluation

Everything in the eval is synthetic. No real participant data was used anywhere. The 24 template diary weeks come from `eval/gen_fixtures.py`, with gold labels from the generator, never from a model. The 8 "wild" weeks were written by a different AI agent in the styles tired people actually write: run-on prose, dictation with no punctuation, strike-through corrections, "Pri same as Tuesday", "odo 45213 to 45231". A second model that never saw the gold labelled all 8 weeks blind and agreed on 58 of 58 shifts. The voice memos are Piper TTS voices, not phone recordings. The 42 restrictive-practice notes were written for this eval; a test fails if any 5-word run of one appears in the prompt.

Prompts and code were tuned on 8 dev weeks only. Everything else was run once, on code frozen at git tag `eval-freeze-1`, with the result files copied into `eval/results/frozen/` under SHA-256 sums. On dev, Gemma e4b scored 100% exact shifts and 8 of 8 weeks to the cent. That overstated it, as dev numbers do.

### What the numbers say

| Held-out set | Arvo (Gemma 4 e4b reads, code prices) | Baselines |
|---|---|---|
| Synthetic test split: 16 weeks, 119 shifts | 93.3% of shifts exact; 10/16 weeks right to the cent | code-only parser 91.6%, 9/16; Gemma pricing the week itself 0/16 |
| Wild diaries: 8 weeks, 58 shifts | 75.9% exact; $121 mean error per week; 2/8 to the cent | code-only 39.7%, $1,207 per week, 0/8; Gemma alone $366 per week, 0/8 |
| Restrictive-practice notes: 42 (22 restraints, 20 innocent notes with trap words) | detection F1 88.9% (precision 87.0%, recall 90.9%); 1/20 innocent notes flagged | keyword list F1 45.7%, 5/20 flagged; `gemma4:e2b` F1 41.4% |
| Photos of a paper diary: 4 weeks | 90.0% exact; 2/4 to the cent | `gemma4:e2b` 76.7%, 1/4 |
| Voice memos: 10, in a voice never used in development | 6/10 with every field right; participant, date and start 10/10; word error rate 12.0% | the tuned set: 11/12, 3.7% |

Full tables: `eval/results/summary_test.md`, `eval/results/summary_wild.md`, `eval/voice/heldout/RESULTS.md`.

The first row is the awkward one. On the template-generated test split, a hand-written parser with no model at all gets 91.6% exact shifts against Gemma's 93.3%, and its dollar error is lower ($132 a week against $195). The templates were too regular to prove anything; a regex learns "half 9 to 1" as well as a model does.

The second row is where the model earns its place. On the free-form weeks the parser collapses to 39.7% and $1,207 a week; Gemma holds 75.9% and $121. The smaller e2b sits between at 65.5% and $260.

The third row is where size matters. e2b reads shifts almost as well as e4b (89.1% against 93.3% on test), but on the restrictive-practice notes its recall is 27.3%: it misses 16 of 22 restraints. e4b finds 20 of 22 and flags 1 of the 20 innocent notes, which were written with trap words ("Hardware shop had already locked up so we went to Coles instead", "strapped her new watch on"). The keyword list flags 5 of those 20. Size buys judgement, not transcription.

Where Gemma loses: on photos, 2 of 4 weeks right to the cent is not good enough to send unread. On voice, 4 of 10 held-out memos got a field wrong: 3 are end times said as "half 11", "half 4" and "half 5"; the fourth is a car-noise memo that came out mangled ("Massdenic Copper"). The worker sees what Gemma heard, line by line, but that is a warning, not a fix.

### What went wrong, and it was not the model

When I read the held-out failures one by one, most of Gemma's "errors" were my own code overriding a correct answer.

- Wild week 2, dictated with no punctuation: `tom 9 30 till 1 30`. Gemma read 09:30-13:30. My time parser took "9" and "1" as the hours, decided the written times were unambiguous, and wrote 09:00-13:00 over the top. The warning it left reads `start set to 09:00 from '9 30 till 1 30' (model said 09:30)`. Four more shifts that week went the same way.
- Same week: `twenty two k`. Gemma returned 22. Code looked for the digits "22" in the diary, found none, and zeroed it: `model gave 22 km but no such km figure is in the diary: set to 0`. On week 7's odometer pair (`odo 61044 to 61058`) Gemma got the subtraction wrong, 10 instead of 14, and code zeroed that too. Neither was right.
- Test week 18: `pri 9:30 to 12:15pm Sundy`. Gemma dated it Sunday 31 January. Code did not recognise "Sundy", fell back to the previous heading (`29/1 - Priya`) and moved the shift to the Friday, which changes the rate.

Those guardrails exist because a model can invent a time or a km figure. Tuned on 8 template weeks, they were overconfident. The fix is a principle, not a patch: code overrules the model only when its own reading is unambiguous and the model's value is impossible. Otherwise the model's value stands, and the disagreement becomes a warning the worker sees.

The numbers after that change are not held out any more: I had seen these errors.

| | Frozen (held out) | After the fix (not held out) |
|---|---|---|
| Test split, exact shifts | 93.3% | [TODO POSTFIX: test exact shifts] |
| Test split, weeks right to the cent | 10/16 | [TODO POSTFIX: test weeks to the cent] |
| Wild, exact shifts | 75.9% | [TODO POSTFIX: wild exact shifts] |
| Wild, mean $ error per week | $121 | [TODO POSTFIX: wild $ per week] |

### Limits

- Victoria, non-remote, standard-intensity self-care and community-access items only. No travel-time claims, sleepovers, remote loadings or other states.
- Synthetic everything: diaries, photos (rendered, not photographed), voices (no Australian accent, no ums). A real worker's diary will be messier.
- 42 notes is a small set. One note moves a per-type F1 a lot.
- Prices change. An award change takes effect 1 December 2026 and the Schedule will be updated. Update the JSON, not the code.
- Registered or unregistered matters. The 5-business-day duty belongs to registered providers. An unregistered sole trader must not use regulated restrictive practices at all, and no official source gives her a deadline for reporting her own. So Arvo says "talk to your provider or the NDIS Commission". It flags; it does not decide. It is not legal or compliance advice.

## Why Does Open Innovation Matter?

Shift notes are disability "sensitive information" under the Privacy Act, and the OAIC's guidance is not to put personal information into public generative AI tools. A worker who pastes "Gave PRN lorazepam 0.5mg" and a name into a hosted chatbot has a problem before she has an invoice. Open weights are the only way this tool can exist: the model runs on her laptop, the server binds to 127.0.0.1, and nothing leaves.

Open also means:

- **Offline.** It works in a car park with no signal, which is where the memo gets recorded.
- **$0 a week.** No per-token bill hiding behind a $12 subscription.
- **Swappable.** The eval runs `gemma4:e4b` and `gemma4:e2b` on the same held-out sets; a third model is one flag away. The answer was not obvious in advance: e2b reads nearly as well and judges much worse.
- **Small hardware.** e4b runs on a 6 GB laptop GPU at about 100 tokens a second. e2b runs on a CPU-only GitHub Actions runner with no API key, at about 6 minutes per diary week.
- **Inspectable rules.** Prices, band definitions and the boundary rule sit in a JSON file with a document and page for each figure. If a plan manager disputes a line, the argument is about a page of the Schedule, not about what a model was thinking.

## My Agent Session

The honest version: I gave Claude Code the challenge page and one instruction, to pick an extremely niche idea with a "war council" of agents and build it end to end with no input from me, and then I was away for the afternoon. The agents picked the problem, set their own rules (held-out sets, no model in the pricing path, no real data), wrote the code, ran the evals and drafted this post. [TODO: say what you reviewed, changed or rewrote after you got back.]

It started as a six-seat "war council": five seats brainstormed through different lenses (privacy, Australian paying customer, wild niche, story, small multimodal models) and a sixth scouted what had already been entered. More than 100 ideas. Four of the five idea seats landed on the NDIS independently; the scout found 30 Week 2 entries in the first 8 hours, none Australian and none in care. Then parallel agents built extraction, pricing, UI, eval and voice against one spec. The log is `JOURNEY.md`.

[TODO: link session if exported]

## My First User

[TODO: first user. If none, delete this section.]

[Guidance: a 15-minute session with anyone who does, or did, NDIS support work on an ABN, or a plan manager. They type last week's diary with names changed. Write down their exact words: how they invoice now, what Arvo got wrong, whether the flag is useful or frightening, whether $12 a month is worth it. Quote only with permission. Never write this section without a real person.]

## Prize Categories

**Best Use of Gemma.** Gemma 4 (`gemma4:e4b` and `gemma4:e2b`, open weights) through Ollama, on the worker's own machine, for all three inputs: typed text, a photo of a paper diary (vision) and a voice memo (audio input, no separate speech model). The held-out eval above is the case for it, including the places it loses.

**Best Use of GitHub Copilot.** The category text says "automate your project with GitHub Actions". `ci.yml` runs the tests on every push. `gemma-smoke.yml` installs Ollama on a CPU-only runner, pulls `gemma4:e2b` and runs the whole pipeline on a diary, then a one-week eval, with no GPU and no key: [run 38342510549](https://github.com/Otto-Deviant1904/arvo/actions/runs/38342510549). I did not use the Copilot coding agent.
