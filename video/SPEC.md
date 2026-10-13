# Arvo YouTube video: spec (internal, for the agents)

Goal: a ~3 minute (2:40-3:20) 1920x1080 30 fps H.264/AAC video for the DEV Hacktoberfest Week 2 "Side Hustle" submission. Story first, real software on screen, honest numbers. Everything open: narration by an open-weight TTS (Kokoro-82M), app running on Gemma 4 locally.

Facts: use ONLY numbers in /home/ottodev/arvo/DEV_POST.md, README.md, eval/results/*.md, eval/voice/heldout/*. The support worker "Mel" is a composite; say so once on screen (small caption is fine). Not legal advice.

## Directory contract
```
video/SPEC.md            this file
video/script.json        [{id, narration, on_screen_caption?, visual}]  (writer)
video/slides/<id>.html   1920x1080 slide sources; video/slides/<id>.png rendered (slides agent)
video/clips/<id>.mp4     screen recordings, 1920x1080 30fps, no audio (recorder agent)
video/clips/<id>.events.json  [{t: seconds, label}] key moments in the clip (recorder agent)
video/audio/<id>.wav     narration per segment, 24 kHz+ mono (tts agent)
video/tts.py             `python video/tts.py --script video/script.json --voice <v> --out video/audio/` (tts agent)
video/assemble.py        builds video/arvo.mp4 + video/arvo.srt (assembler)
```

## Shot list (ids are fixed; the writer writes narration for each)
| id | visual | notes |
|---|---|---|
| s01_title | slide | "Arvo": Sunday-night invoicing for NDIS support workers, offline on Gemma 4 |
| s02_hook | slide | the diary line appears as if typed: `Tues (Cup day!!) - Jake 3 till 8:30ish ... Locked the pantry so he would stop snacking before dinner` |
| s03_who | slide | who: independent NDIS support worker on an ABN, Victoria; admin unpaid; rates table (weekday $73.58 / evening $81.07 / Sat $103.54 / Sun $133.50 / public holiday $163.46) |
| s04_trap_price | slide | Trap 1: Cup Day is a public holiday (5.5 h x $163.46 = $899.03); a shift crossing 8pm is billed whole at the evening rate (Schedule s2.4(c) quote) |
| s05_trap_pantry | slide | Trap 2: "locked the pantry" = environmental restraint; registered provider: notify within 5 business days (24 h if harm); unregistered: must not use at all, raise with the Commission |
| s06_demo_text | clip | live app: diary pasted, Read and price pressed (timer counts), results appear; scroll flags panel (pantry highlighted, PRN + bed rails authorised), shifts table, invoice lines; click one "Why"; open Print invoice |
| s07_demo_photo | clip | live app: drop a photo of a paper diary (eval/fixtures/week13.png), run, shifts appear |
| s08_demo_voice | clip | live app: add 3 voice memos, run, "What Gemma heard" opens, shifts appear. The assembler plays ~5 s of one memo's audio here |
| s09_how | slide | diagram: diary/photo/voice -> Gemma 4 reads -> shifts JSON -> code decides (bands, holidays, official prices) -> invoice; notes -> Gemma -> flag with verbatim quote. Caption: "Gemma pricing the week itself: 0 of 16 weeks right" |
| s10_results | slide | held-out results table (test 93.3%, wild 75.9% vs code-only 39.7%, RP F1 88.9% vs keyword 45.7%, e2b 41.4%, photos 90.0%, voice 6/10) |
| s11_lesson | slide | "My guardrails overruled right answers": 7 of 14 wrong wild shifts were code overwriting Gemma; fix rule; after fix (not held out) wild 94.8%, 7/8 weeks |
| s12_open | slide | why open: sensitive health info stays on the laptop, offline in a car park, $0 per week, runs on a 6 GB laptop GPU and a CPU-only GitHub runner (small screenshot of the Actions run is welcome) |
| s13_pay | slide | who pays: ~$12/month for solo workers; agency tools charge per user with a five-staff minimum (ShiftCare pricing page) |
| s14_end | slide | links: github.com/Otto-Deviant1904/arvo and otto-deviant1904.github.io/arvo ; "Built with Gemma 4, Ollama, Python. Narration: Kokoro (open weights)." |

## Visual style
Match the app (web/index.html): calm, off-white background (#f4f5f2-ish), deep green accent, red for flags, system sans (Inter/Noto Sans if installed), big type (slide titles 72-96 px, body 40-48 px), generous margins (120 px), max 3 ideas per slide, numbers big. No stock photos, no emoji, no gradients-for-the-sake-of-it. Subtle progress bar at the bottom of slides is fine.

## Timing
Total narration ~420-470 words. The assembler fits each clip to its narration (speeds up waiting, freezes the last frame if short). Slides hold for narration + 0.6 s.

## CHANGE (user request): hand-animated look
- Slides become animated scenes: video/scenes/<id>.mp4, drawn with Rough.js + handwritten OFL fonts (video/vendor/), paper texture, 12 fps "on twos" with boiling lines, things drawn on in narration order. Rendered by video/render_scenes.py from video/scenes/<id>.html (`window.renderAt(t)`), lengths from video/audio/durations.json.
- Screen clips sit inside a hand-drawn laptop frame: video/scenes/frame_overlay.png (transparent screen window) + frame_rect.json.
- Doodle annotations (red rough circles/arrows drawn on) over clips at events with "box" coordinates (video/annotate.py, rendered with Rough.js, transparent PNG frames).
- Captions in a handwritten-style font (Patrick Hand) on a paper-coloured box.
