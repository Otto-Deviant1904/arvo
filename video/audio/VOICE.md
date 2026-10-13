# Narration voice (Kokoro-82M scratch / timing track)

The final narration will be recorded by the author (see `video/prep_voice.py`). The Kokoro
track sets segment timing until then, and is the fallback if no recording exists.

**Choice: `af_heart` at `--speed 0.9`** (kokoro-onnx 0.6.1, model-files-v1.0, lang en-us).

## Audition
Same two sentences, 23 words, `--speed 1.0`, files in `audition/<voice>.wav`. Every file
was trimmed to 0.15 s of silence at each end and normalised to -16 LUFS. wps = words /
(duration - 0.3 s). Grades come from the VOICES.md table on the hexgrad/Kokoro-82M model card.

| voice | accent | HF grade | duration s | wps @1.0 | raw peak | clipped samples |
|---|---|---|---|---|---|---|
| af_heart | US F | **A** | 8.14 | 2.93 | 0.77 | 0 |
| af_bella | US F | A- | 8.37 | 2.85 | 0.81 | 0 |
| bf_emma | GB F | B- | 7.53 | 3.18 | 0.73 | 0 |
| bf_isabella | GB F | C | 7.59 | 3.16 | 0.81 | 0 |
| bm_george | GB M | C | 8.93 | 2.67 | 0.57 | 0 |
| am_michael | US M | C+ | 9.01 | 2.64 | 0.75 | 0 |

## Why af_heart
- It has the highest grade of any English voice (A). bf_emma (B-) is the best British
  voice but is well behind. Kokoro has no Australian voice.
- No clipping in any candidate, so that check does not separate them.
- At 1.0 it reads slightly fast (2.93 wps). At `--speed 0.9` it reads at 2.69 wps (8.84 s),
  inside the 2.3-2.8 target. That is close to the ~2.5-2.6 wps the spec's 420-470 words in
  2:40-3:20 needs, so its durations are a fair stand-in for a human read.
- bm_george and am_michael meet the rate target at 1.0, but both have lower grades (C, C+).

## Pronunciation (checked against the espeak-ng phonemes, not by ear)
`python video/tts.py ... --dry-run` prints the text after the fixes, plus its phonemes.
No fix is needed for "Arvo", which already comes out as AR-voh (US `ˈɑːɹvoʊ`, GB `ˈɑːvəʊ`).
No fix is needed for Gemma, GitHub, PRN, GPU, JSON, e4b or Melbourne either. The fixes table in
`tts.py` covers the rest:
- NDIS and ABN are spelled out.
- Ollama becomes "oh-llama", and s2.4(c) becomes "section 2 point 4 c".
- Dollar amounts, decimals, "x", "h", "7/8" and "8:30" are rewritten, because espeak misreads them.
