# Voice memo eval (gemma4:e4b, 12 Piper TTS memos)

WER: lower-cased words, number words mapped to digits and k's/km unified (wer_raw: no mapping). Fields: extracted shift vs gold after the full text pipeline; note = 80% of gold note words present; rp = right restrictive-practice type flagged (or none flagged when none).

| set | memos | WER | WER raw | participant | date | start | end | km | note | rp | all fields |
|---|---|---|---|---|---|---|---|---|---|---|---|
| all | 12 | 0.037 | 0.170 | 1.00 | 1.00 | 1.00 | 1.00 | 0.92 | 1.00 | 1.00 | 0.92 |
| clean | 10 | 0.044 | 0.180 | 1.00 | 1.00 | 1.00 | 1.00 | 0.90 | 1.00 | 1.00 | 0.90 |
| car noise | 2 | 0.000 | 0.121 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| en_GB-alan-medium | 6 | 0.012 | 0.150 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| en_GB-jenny_dioco-medium | 6 | 0.061 | 0.190 | 1.00 | 1.00 | 1.00 | 1.00 | 0.83 | 1.00 | 1.00 | 0.83 |

Mean audio 10.11 s/memo. Transcription 0.92 s/memo; end to end (transcribe + extract + RP screen) 2.99 s/memo. Extracted shifts minus gold shifts: 0.

| memo | noise | WER | wrong fields | transcript |
|---|---|---|---|---|
| alan-1 | - | 0.000 | - | Jake, Monday, 3 till half 8. Footy training, then Maccas on the way home. 12 km. |
| alan-2 | - | 0.045 | - | Priya Tuesday morning, 9 till 1, helped her with the shower and brekkie. Then we did the washing together. No case today. |
| alan-3 | - | 0.000 | - | Tommy, Wednesday arvo, quarter past 2 till quarter to 6. Went to Bunnings and the library, 18 km. He got really worked up at the checkout, so I held both his arms down by his sides until he settled. |
| alan-4 | - | 0.000 | - | Mrs B, Thursday, 7 in the morning till half past 10. Breakfast, meds prompt, and a slow walk around the block. Nothing else to report. |
| alan-5 | 12.0 dB | 0.000 | - | Jake again, 4 till 9 tonight. Movies and dinner in the city, 25 km. His mum wants his Xbox controller kept in my car all week so he can't play it, so I've taken it. |
| alan-6 | - | 0.028 | - | Priya, yesterday, 10 till 2:30, shopping at Chadston, 8 km. She wouldn't stop yelling in the car, so I put the child locks on and left her in there for 10 minutes to calm down. |
| jenny-1 | - | 0.062 | - | Jake Monday, 3 till half 8. Physi training, then Maccas on the way home. 12 km. |
| jenny-2 | - | 0.136 | - | Priya, Tuesday morning, 9 till 1, help chair with the shower and brekkie. Then we did the washing together. No case today. |
| jenny-3 | 12.0 dB | 0.000 | - | Tommy, Wednesday arvo, quarter past 2 till quarter to 6, went to Bunnings and the library, 18 km. He got really worked up at the checkout, so I held both his arms down by his sides until he settled. |
| jenny-4 | - | 0.000 | - | Mrs B, Thursday, 7 in the morning till half past 10. Breakfast, meds prompt, and a slow walk around the block. Nothing else to report. |
| jenny-5 | - | 0.000 | - | Jake again, 4 till 9 tonight. Movies and dinner in the city. 25 km. His mum wants his Xbox controller kept in my car all week so he can't play it. So I've taken it. |
| jenny-6 | - | 0.167 | km | Priya, yesterday, 10 till 2:30, chopping a chestnut, AK's, she wouldn't stop yelling in the car, so I put the child lock on and left her in there for 10 minutes to calm down. |

## Notes (read before quoting these numbers)

- Audio is Piper TTS (en_GB alan + jenny_dioco voices), not real phone recordings: clean, fluent, no
  Australian accent, no ums, wind or radio. Car noise is brown noise low-passed at 350 Hz, mixed at
  12 dB SNR on 2 memos. Real-world speech recognition quality is still untested.
- Tuned on this set: the first run headed each memo with its recording date only, and both
  "Priya, yesterday ..." memos (recorded Sunday) came out dated Sunday (date accuracy 0.83; a Sunday
  rate on a Saturday shift). `voice.memo_line` now resolves "yesterday"/"last night" in code and heads
  the line with the shift day. Date 1.00 is therefore not held-out.
- Remaining miss: jenny-6 "eight k's" was heard as "AK's", so km became 0 with no warning; only the
  "heard ..." warning line shows the worker what Gemma heard. Other mishearings ("chopping a chestnut"
  for "shopping at Chadstone", "Physi" for "footy", "No case" for "No k's") did not change any field.
- Transcripts were identical across 3 runs (temperature 0). GPU (RTX 4050 6 GB) was shared with other
  agents, so seconds are indicative.
