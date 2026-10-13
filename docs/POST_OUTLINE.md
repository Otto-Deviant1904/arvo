# DEV post outline (internal)

Working title options
- "Locked the pantry": the invoice tool that noticed a reportable incident
- Sunday night, 11pm, 23 shifts: an offline NDIS invoice tool on a 4B model
- Arvo: a support worker's diary goes in, an invoice and one awkward question come out

Required header line (template): *This is a submission for the [Hacktoberfest Open-Source AI Challenge Week 2: Side Hustle](https://dev.to/challenges/hacktoberfest-week2-2026-10-12)*
Tags: devchallenge, hf26challenge (+ gemma, opensource?) max 4 tags on DEV.

Sections (template order): What I Built, Demo, Code, How I Built It, Why Does Open Innovation Matter?, My Agent Session (optional), My First User (only if real), Prize Categories.

Beats
1. The person (composite, labelled as such): ABN support worker in Melbourne's south-east, 4 participants, ~25 shifts a fortnight, Sunday night admin. Admin is unpaid. A wrong item code bounces the invoice and delays pay. Numbers: weekday daytime $73.58/h, Sunday $133.50/h, public holiday $163.46/h (NDIS Pricing Schedule 2026-27).
2. The trap nobody tells you: a shift 3pm to 8:30pm is claimed WHOLE at the evening rate (Schedule s2.4(c), including the duplicated "a support a support" typo). Melbourne Cup Day is a public holiday in Victoria only.
3. The second trap: "locked the pantry so he'd stop snacking" is an environmental restrictive practice. Unauthorised use is a reportable incident (5 business days, 24 h if harm). Workers often don't know.
4. Why local: disability shift notes are sensitive information; OAIC guidance; no participant data to a US API; $0 per week; works offline in a car park.
5. Architecture: Gemma reads (diary -> shifts JSON; note -> RP flag with verbatim quote), code decides (bands, holidays, prices from official JSON, deadlines). The verbatim-quote check.
6. The eval: synthetic diaries with gold labels, Gemma-extract + code vs Gemma-alone pricing; RP Gemma vs keyword baseline; e4b vs e2b; photo of paper diary. Real numbers, real failures.
7. What went wrong (honest): fill from eval failures.
8. Who would pay and how much: $12/month or $99/year vs agency platforms at ~$75/month minimum.
9. Partner categories: Gemma (local via Ollama, e4b + e2b, vision), GitHub Copilot (Actions runs Gemma on a CPU runner with no key).
10. Limits: not legal advice, synthetic data, Victoria only, one worker, no travel-time claims, prices change (1 Dec 2026 award change).
