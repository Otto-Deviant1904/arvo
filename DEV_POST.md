---
title: '"Locked the pantry": offline Gemma 4 NDIS invoicing that caught 20 of 22 restraints'
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

Mel is not a real person: she is a composite built from published rate guides and NDIS Commission material. The job is real. She is an independent NDIS support worker on an ABN. Nobody pays her for the hours it takes to turn that diary into invoices, a wrong item number bounces the invoice at the plan manager, and that one line holds two traps.

**The price.** Melbourne Cup Day is a public holiday in Melbourne and most of Victoria, and in no other state, so all 5.5 hours go on the public-holiday item at $163.46 an hour, not the weekday $73.58. On an ordinary Tuesday the same shift would cross 8pm, and the NDIS Pricing Schedule 2026-27 (s2.4(c), p5) says: "Where a support a support crosses between different times of day or days of week and is delivered by a single worker, the higher of the amounts applies to the whole support." (The doubled words are in the official PDF.) Splitting the shift at 8pm, the obvious move, underclaims.

**The pantry.** Locking a pantry so someone stops snacking restricts his free access to his own environment. Under the NDIS (Restrictive Practices and Behaviour Support) Rules 2018 that is an environmental restraint, one of five regulated restrictive practices. For a registered provider, unauthorised use is a reportable incident: 5 business days to notify the NDIS Commission, or 24 hours if it caused harm. An unregistered sole trader may not use a restrictive practice at all, and the Commission asks for it to be raised with them. Either way, it reads like an ordinary shift note, which is the problem. Mel would have invoiced the shift and moved on.

Arvo does the Sunday-night job and asks the awkward question. Type, photograph or dictate the week; get back invoice lines a plan manager will accept, a printable invoice per participant, a CSV, and a red flag that quotes the exact sentence and gives a report-by date. It all runs on Gemma 4 through Ollama on the worker's own laptop. Nothing is sent anywhere.

**Who pays.** Independent ABN support workers, at a proposed $12 a month or $99 a year. The platforms that already do NDIS invoicing are priced for agencies: [ShiftCare](https://shiftcare.com/pricing), for example, charges per user and says "All plans start at a minimum of five staff". Her alternative is a spreadsheet, the price schedule PDF, and an hour she does not bill for.

## Demo

https://otto-deviant1904.github.io/arvo/ [TODO: confirm live]

![Screen recording: the week's diary goes in, "Read and price this week" is pressed, and the red restrictive-practice panel, the shifts Gemma read and the per-participant invoice lines appear](https://raw.githubusercontent.com/Otto-Deviant1904/arvo/main/docs/img/arvo-demo.gif)

*A live run on my laptop: 13.6 seconds from button to invoices. The wait is sped up in the recording; the counter on the button shows real seconds. Video: [`docs/img/arvo-demo.mp4`](https://github.com/Otto-Deviant1904/arvo/blob/main/docs/img/arvo-demo.mp4).*

The page shows a saved run of `gemma4:e4b` on the week in `docs/demo/diary.txt`: 7 shifts, 10 invoice lines, 3 flags, 13.3 seconds end to end on a laptop RTX 4050 (6 GB). It calls no model; it is `docs/demo/run.json` rendered. To run your own diary: `ollama pull gemma4:e4b` (a 6.6 GB download; on a 6 GB card Ollama keeps what doesn't fit in system RAM), clone, `python -m arvo serve`. Python 3.12 standard library, no other dependencies.

### A worked example

Three lines from the demo week (ending Sunday 8 November 2026):

| Diary line | Gemma reads | Code decides | Invoice line |
|---|---|---|---|
| `Tues (Cup day!!) - Jake 3 till 8:30ish` | jake, 2026-11-03, 15:00-20:30 | Tue 3 Nov 2026 is Melbourne Cup Day, a Victorian public holiday | `04_102_0125_6_1` Public Holiday, 5.5 h x $163.46 = **$899.03** |
| `Thurs night - Mrs B again 7pm-9:30pm` | nonna, 2026-11-05, 19:00-21:30 | Crosses 8pm, so s2.4(c): the whole support goes in the higher band | `01_015_0107_1_1` Weekday Evening, 2.5 h x $81.07 = **$202.68** |
| `Sun - T.O. 10-3 ... 22 km` | tom, 2026-11-08, 10:00-15:00, 22 km | Sunday band; km claimed as Activity Based Transport | `04_106_0125_6_1` Sunday, 5 h x $133.50 = **$667.50**, plus 22 km x $0.99 = $21.78 |

![The "Check before you invoice" panel: the pantry note flagged as an environmental restraint, not authorised, with a registered-provider notify-by date of Tuesday 10 November 2026; the PRN and bed-rail notes flagged as authorised, "record it as the plan says"](https://raw.githubusercontent.com/Otto-Deviant1904/arvo/main/docs/img/flags.png)

The flags for the same week:

- **Red.** "Locked the pantry so he would stop snacking before dinner": environmental restraint, not authorised; a registered provider would have to notify by Tue 10 Nov 2026.
- **Authorised, record only.** "Gave PRN lorazepam 0.5mg as per plan at 11:15" (chemical) and "Bed rails up as per plan" (mechanical) match the authorisations in Priya's and Nonna's roster entries. Still restrictive practices, still shown, no report-by date.
- **Not flagged.** "He asked me to hang onto his phone during the game." Holding a phone because the person asked is not a restraint.

Every line and flag in that week is right. It is one week, and I had seen it while building. The held-out numbers are further down.

## Code

{% github Otto-Deviant1904/arvo %}

MIT licence. The pieces:

- `arvo/extract.py`: diary to shifts (one Gemma call per week, then checks in code).
- `arvo/rp.py`: restrictive-practice screen (one Gemma call per note, s 6 definitions).
- `arvo/pricing.py`, `calendar_au.py`, `prices.py`: bands, holidays, deadlines, prices from `data/ndis_prices_2026_27.json`.
- `arvo/voice.py`: voice memos, heard by Gemma 4 directly.
- `arvo/server.py`, `web/index.html`: stdlib server on 127.0.0.1, one HTML file.
- `eval/`: fixtures, gold labels, every result file, frozen copies with SHA-256 sums.

## How I Built It

### The model reads, code decides

Gemma turns messy text into structured shifts. It never picks a price, an item number or a deadline. Those come from a JSON file in which every figure cites its source document and page, and from `pricing.py`, which implements the Schedule's definitions as written.

Take Nonna's Thursday evening. Gemma's entire contribution is `{"participant_id": "nonna", "date": "2026-11-05", "start": "19:00", "end": "21:30"}`. Everything after that, the band, the item number, the $81.07, is code reading the Schedule. The model never saw a dollar sign.

![What Gemma read from the demo diary, row by row with the exact span the times came from, above the invoice lines code priced from it](https://raw.githubusercontent.com/Otto-Deviant1904/arvo/main/docs/img/shifts-invoice.png)

The same split applies to the flags. Gemma must return its evidence as a sentence "copied character for character" from the note, and `find_verbatim` checks that it is. If the quote is not in the note, the flag is dropped and the worker sees a warning saying so. A flag she cannot point to in her own words is one she cannot act on, and a model that paraphrases is a model that can invent. On the 42 held-out notes, 0 flags were dropped by this check.

I measured what happens without the split. Give Gemma e4b the diary, the roster, the week's dates with holiday names and the full price table, and ask it to write the invoice lines itself: 0 of 16 test weeks right to the cent, line recall 49.5%. With code pricing the same model's shifts: 10 of 16 and 95.0%.

### The evaluation

Everything in the eval is synthetic. No real participant data was used anywhere. The 24 template diary weeks come from `eval/gen_fixtures.py`, with gold labels from the generator, never from a model. The 8 "wild" weeks were written by a different AI agent imitating the way tired people write: run-on prose, dictation with no punctuation, strike-through corrections, "Pri same as Tuesday", "odo 45213 to 45231". A second model that never saw the gold labelled all 8 weeks blind and agreed on 58 of 58 shifts. The voice memos are Piper TTS voices, not phone recordings. The 42 restrictive-practice notes were written for this eval by another agent; a test fails if any 5-word run of one appears in the prompt.

Prompts and code were tuned on 8 dev weeks only. Everything else was run once, on code frozen at git tag `eval-freeze-1`, with the result files copied into `eval/results/frozen/` under SHA-256 sums. On dev, Gemma e4b scored 100% exact shifts and 8 of 8 weeks to the cent. That overstated it, as dev numbers do.

### What the numbers say

| Held-out set | Arvo (Gemma 4 e4b reads, code prices) | Baselines |
|---|---|---|
| Synthetic test split: 16 weeks, 119 shifts | 93.3% of shifts exact; 10/16 weeks right to the cent | code-only parser 91.6%, 9/16; Gemma pricing the week itself 0/16 |
| Wild diaries: 8 weeks, 58 shifts | 75.9% exact; $121 mean error per week; 2/8 to the cent | code-only 39.7%, $1,207 per week, 0/8; Gemma alone $366 per week, 0/8 |
| Restrictive-practice notes: 42 (22 restraints, 20 innocent notes with trap words) | detection F1 88.9% (precision 87.0%, recall 90.9%); 1/20 innocent notes flagged | keyword list F1 45.7%, 5/20 flagged; `gemma4:e2b` F1 41.4% |
| Photos of a paper diary: 4 weeks | 90.0% exact; 2/4 to the cent | `gemma4:e2b` 76.7%, 1/4 |
| Voice memos: 10, in a voice never used in development | 6/10 with every field right; participant, date and start 10/10; word error rate 12.0% | (the memos I tuned on: 11/12) |

Full tables: `eval/results/summary_test.md`, `eval/results/summary_wild.md`, `eval/voice/heldout/RESULTS.md`.

The first row is the awkward one. On the template-generated test split, a hand-written parser with no model at all gets 91.6% exact shifts against Gemma's 93.3%, and its dollar error is lower ($132 a week against $195). The templates were too regular to prove anything; a regex handles "half 9 to 1" as well as a model does.

The second row is where the model earns its place. On the free-form weeks the parser collapses to 39.7% and $1,207 a week; Gemma holds 75.9% and $121. The smaller e2b sits between at 65.5% and $260.

The third row is where size matters. e2b reads shifts almost as well as e4b (89.1% against 93.3% on test), but on the restrictive-practice notes its recall is 27.3%: it misses 16 of 22 restraints. e4b finds 20 of 22. Of its 3 false positives, 2 are real restraints filed under the wrong type (a latched screen door it called environmental rather than seclusion) and 1 is an innocent note: "usual night meds at 8 off the chart", where "off the chart" means read from the medication chart. The innocent notes were written with trap words ("Hardware shop had already locked up so we went to Coles instead", "strapped her new watch on"). The keyword list flags 5 of those 20. Size buys judgement, not transcription.

Where Gemma loses: on photos, 2 of 4 weeks right to the cent is not good enough to send unread. On voice, 4 of 10 held-out memos got a field wrong: 3 are end times said as "half 11", "half 4" and "half 5"; the fourth is a car-noise memo that came out mangled ("Massdenic Copper"). The worker sees what Gemma heard, line by line, but that is a warning, not a fix.

### What went wrong: my guardrails overruled right answers

On the wild diaries Arvo got 14 of 58 shifts wrong. When I read them one by one, 7 of the 14 were my own code overwriting a value Gemma had right, and code also invented 2 extra shifts by reading a strike-through correction as a second block of time.

- Wild week 2, dictated with no punctuation: `tom 9 30 till 1 30`. Gemma read 09:30-13:30. My time parser took "9" and "1" as the hours, decided the written times were unambiguous, and wrote 09:00-13:00 over the top. The warning it left reads `start set to 09:00 from '9 30 till 1 30' (model said 09:30)`. Four more shifts that week went the same way.
- Same week: `twenty two k`. Gemma returned 22. Code looked for the digits "22" in the diary, found none, and zeroed it: `model gave 22 km but no such km figure is in the diary: set to 0`. On week 7's odometer pair (`odo 61044 to 61058`) Gemma got the subtraction wrong, 10 instead of 14, and code zeroed that too. Neither was right.
- Test week 18: `pri 9:30 to 12:15pm Sundy`. Gemma dated it Sunday 31 January. Code did not recognise "Sundy", fell back to the previous heading (`29/1 - Priya`) and moved the shift to the Friday, which changes the rate.

Those guardrails exist because a model can invent a time or a km figure. Tuned on 8 template weeks, they were overconfident. The fix is a principle, not a patch: code overrules the model only when its own reading is unambiguous and the model's value is impossible. Otherwise the model's value stands, and the disagreement becomes a warning the worker sees.

The numbers after that change are not held out any more: I had seen these errors.

| | Frozen (held out) | After the fix (not held out) |
|---|---|---|
| Test split, exact shifts | 93.3% | 95.0% |
| Test split, weeks right to the cent | 10/16 | 11/16 |
| Wild, exact shifts | 75.9% | 94.8% |
| Wild, weeks right to the cent | 2/8 | 7/8 |
| Wild, mean $ error per week | $121 | $68 |
| Voice memos with every field right | 6/10 | 8/10 |

The dev weeks stayed at 100%. Two things got worse, and they are the cost of the rule. In one test week the model put a shift on the wrong day and a heading would have caught it; now the heading only raises a check, and this time it raised none. In one wild week the model skipped two shifts and the code's fallback added one back on the Thursday, missing the correction on the next line ("that was Fri not Thu"). The wild number is the one I would trust least: I fixed the code while looking at those exact diaries. Files: `eval/results/postfix/`, `eval/voice/heldout/postfix/`.

### Limits

- Victoria, non-remote, standard-intensity self-care and community-access items only. No travel-time claims, sleepovers, remote loadings or other states.
- Synthetic everything: diaries, photos (rendered, not photographed), voices (no Australian accent, no ums). A real worker's diary will be messier.
- 42 notes is a small set. One note moves a per-type F1 a lot.
- Prices change. An award change takes effect 1 December 2026 and the Schedule will be updated. Update the JSON, not the code.
- Registered or unregistered matters. The 5-business-day duty belongs to registered providers. An unregistered sole trader must not use regulated restrictive practices at all, and no official source gives her a deadline for reporting her own. So Arvo labels the date as the registered provider's deadline and gives unregistered workers the Commission's contact details. It flags; it does not decide. It is not legal or compliance advice.

## Why Does Open Innovation Matter?

Shift notes are health information, which makes them "sensitive information" under [s 6 of the Privacy Act](https://www.legislation.gov.au/C2004A03712/latest/text), and as a matter of best practice the [OAIC recommends](https://www.oaic.gov.au/privacy/privacy-guidance-for-organisations-and-government-agencies/guidance-on-privacy-and-the-use-of-commercially-available-ai-products) that organisations do not enter personal information into publicly available generative AI tools. A worker who pastes "Gave PRN lorazepam 0.5mg" and a name into a hosted chatbot has a problem before she has an invoice. With open weights the model runs on her laptop, the server binds to 127.0.0.1, and nothing leaves. That is the product, not a feature of it.

Open also means:

- **Offline.** It works in a car park with no signal, which is where the memo gets recorded.
- **$0 a week.** No per-token bill hiding behind a $12 subscription.
- **Swappable.** Changing model is one flag, and the eval showed why that matters: e2b reads nearly as well as e4b and judges much worse.
- **Small hardware.** A 6 GB laptop GPU is enough; so is a CPU-only GitHub Actions runner, slowly.
- **Inspectable rules.** Prices, band definitions and the boundary rule sit in a JSON file with a document and page for each figure. If a plan manager disputes a line, the argument is about a page of the Schedule, not about what a model was thinking.

## My Agent Session

The honest version: I gave Claude Code the challenge page and one instruction, to pick an extremely niche idea with a "war council" of agents and build it end to end with no input from me, and then I was away for the afternoon. The agents picked the problem, set their own rules (held-out sets, no model in the pricing path, no real data), wrote the code, ran the evals and drafted this post. [TODO: say what you reviewed, changed or rewrote after you got back.]

It started as a six-seat "war council": five seats brainstormed through different lenses (privacy, Australian paying customer, wild niche, story, small multimodal models) and a sixth scouted what had already been entered. More than 100 ideas. Four of the five idea seats landed on the NDIS independently. Then parallel agents built extraction, pricing, UI, eval and voice against one spec. The log is `JOURNEY.md`.

[TODO: link session if exported]

## My First User

[TODO: first user. If none, delete this section.]

[Guidance: a 15-minute session with anyone who does, or did, NDIS support work on an ABN, or a plan manager. They type last week's diary with names changed. Write down their exact words: how they invoice now, what Arvo got wrong, whether the flag is useful or frightening, whether $12 a month is worth it. Quote only with permission. Never write this section without a real person.]

## Prize Categories

**Best Use of Gemma.** Gemma 4 (`gemma4:e4b` and `gemma4:e2b`, open weights) through Ollama, on the worker's own machine, for all three inputs: typed text, a photo of a paper diary (vision) and a voice memo (audio input, no separate speech model). The held-out eval above is the case for it, including the places it loses.

**Best Use of GitHub Copilot.** The category text says "automate your project with GitHub Actions". `ci.yml` runs the tests on every push. `gemma-smoke.yml` installs Ollama on a CPU-only runner, pulls `gemma4:e2b` and runs the whole pipeline on a diary, then a one-week eval, with no GPU and no key: [run 38347559687](https://github.com/Otto-Deviant1904/arvo/actions/runs/38347559687). I did not use the Copilot coding agent.
