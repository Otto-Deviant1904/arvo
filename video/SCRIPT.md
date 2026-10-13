# Arvo video: recording sheet

Record each segment as its own file named exactly `<id>.m4a` (or .wav/.mp3/.ogg), e.g. `s02_hook.m4a`, into one folder.
Phone voice memos are fine. Quiet room, phone 20-30 cm from your mouth, same spot for every take.
Speak at your natural pace. Pauses are fine; silence at the start/end is trimmed automatically.
Scenes are re-timed to YOUR recordings, so you don't need to hit the guide length exactly.

Then run:
```bash
python3 video/prep_voice.py --in ~/arvo-voice --out video/audio/
bash video/build_video.sh
```

| # | file | say this | guide length |
|---|---|---|---|
| 1 | `s01_title` | Arvo. Sunday-night invoicing for NDIS support workers, offline, on Gemma four. | 6.3 s |
| 2 | `s02_hook` | One diary line, two traps. Tuesday, Cup Day. Jake, three till eight thirty-ish. Locked the pantry so he would stop snacking. One trap costs money. The other is a restrictive practice that reads like any other note. | 15.0 s |
| 3 | `s03_who` | Call her Mel. An independent NDIS support worker in Victoria. Nobody pays her for the admin, and a wrong item number bounces the invoice. | 10.2 s |
| 4 | `s04_trap_price` | Trap one. Cup Day is a Victorian public holiday. Five and a half hours at the holiday rate: eight hundred and ninety-nine dollars. On a normal Tuesday it crosses eight at night, and the whole shift bills at the evening rate. Not split. | 15.7 s |
| 5 | `s05_trap_pantry` | Trap two. Locking the pantry is an environmental restraint under the NDIS rules. A registered provider has five business days to notify the Commission, twenty-four hours if it caused harm. An unregistered sole trader must not use it. | 16.9 s |
| 6 | `s06_demo_text` | Paste the week, press Read and price. Gemma reads it offline; the counter shows real seconds, about thirteen. Seven shifts, ten invoice lines, three flags. The red one is the pantry, quoted exactly, with its notify-by date. The PRN and bed rails: authorised, record only. Then the shifts Gemma read, the lines code priced, a Why on each, and a printable invoice per participant. | 25.7 s |
| 7 | `s07_demo_photo` | Same job from a photo of a paper diary. Drop it in and run. All seven shifts come back, read straight from the image, with a note to check them before you invoice. | 11.5 s |
| 8 | `s08_demo_voice` | And voice. Three memos, one per shift. Gemma hears the audio directly; no separate speech model. What Gemma heard opens for checking; the shifts land in the table. | 11.3 s |
| 9 | `s09_how` | The model reads, code decides. Gemma never picks a price, an item number or a deadline. Code does, from the Schedule. Let Gemma price the week itself: zero of sixteen right. A flag must quote the note, or it's dropped. | 15.3 s |
| 10 | `s10_results` | Held-out results. Test split: ninety-three per cent of shifts exact. Wild diaries: seventy-six per cent, where a code-only parser gets forty. Restrictive practices: e-four-b finds twenty of twenty-two restraints. Photos, ninety per cent. Voice, six of ten memos fully right. | 20.3 s |
| 11 | `s11_lesson` | My guardrails overruled right answers. Seven of fourteen wrong wild shifts were my code overwriting Gemma's correct value. New rule: code overrules Gemma only when Gemma's value is impossible. After the fix, no longer held out, wild goes to ninety-five per cent. | 19.0 s |
| 12 | `s12_open` | Why open weights? Shift notes are sensitive health information. On her own laptop, nothing leaves. Offline in a car park, zero dollars a week, on a six gigabyte laptop GPU. | 12.9 s |
| 13 | `s13_pay` | Who pays? Independent workers like Mel, at twelve dollars a month. The agency tools charge per user, five staff minimum. | 8.4 s |
| 14 | `s14_end` | On GitHub: Otto Deviant nineteen-oh-four, slash arvo. Open code, open weights. The model reads, code decides, and nothing leaves the laptop. | 10.5 s |

Total guide narration: 199 s.
