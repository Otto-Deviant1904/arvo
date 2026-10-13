# Held-out voice memo eval (gemma4:e4b, 10 Piper TTS memos)

WER: lower-cased words, number words mapped to digits and k's/km unified (wer_raw: no mapping). Fields: extracted shift vs gold after the full text pipeline; note = 80% of gold note words present; rp = right restrictive-practice type flagged (or none flagged when none).

| set | memos | WER | WER raw | participant | date | start | end | km | note | rp | all fields |
|---|---|---|---|---|---|---|---|---|---|---|---|
| all | 10 | 0.120 | 0.276 | 1.00 | 1.00 | 1.00 | 0.60 | 1.00 | 0.80 | 1.00 | 0.60 |
| clean | 7 | 0.075 | 0.220 | 1.00 | 1.00 | 1.00 | 0.57 | 1.00 | 0.86 | 1.00 | 0.57 |
| car noise | 3 | 0.224 | 0.408 | 1.00 | 1.00 | 1.00 | 0.67 | 1.00 | 0.67 | 1.00 | 0.67 |
| en_GB-northern_english_male-medium | 10 | 0.120 | 0.276 | 1.00 | 1.00 | 1.00 | 0.60 | 1.00 | 0.80 | 1.00 | 0.60 |
| tag: crosses_8pm | 2 | 0.022 | 0.226 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| tag: last_night | 1 | 0.000 | 0.160 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| tag: no_day_spoken | 1 | 0.500 | 0.682 | 1.00 | 1.00 | 1.00 | 0.00 | 1.00 | 0.00 | 1.00 | 0.00 |
| tag: public_holiday | 2 | 0.077 | 0.209 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| tag: rp | 2 | 0.091 | 0.217 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| tag: trap_words | 2 | 0.080 | 0.177 | 1.00 | 1.00 | 1.00 | 0.50 | 1.00 | 1.00 | 1.00 | 0.50 |

Mean audio 8.18 s/memo. Transcription 2.96 s/memo; end to end (transcribe + extract + RP screen) 4.88 s/memo. Extracted shifts minus gold shifts: 0.

| memo | noise | WER | wrong fields | transcript |
|---|---|---|---|---|
| ho-01 | 12.0 dB | 0.043 | - | Jakey, Monday, quarter to 5 till 20 past 8. Ten pin bowling in Morabin, then fish and chips down the beach. 22 km. |
| ho-02 | - | 0.061 | end | Nonna Tuesday morning 8 till half 11 gave her the morning tablets from the Webster pack did her hair and we locked up the house and walked to the bakery no case today |
| ho-03 | - | 0.000 | - | Tom, last night half 6 till quarter past 9. We drove round to see the Christmas lights in Boronia then got a burger. 14 km. |
| ho-04 | - | 0.091 | end | Priya Wednesday arvo, midday till half 4. Christmas shopping at Safelands, then we wrapped all the presents at her place. 19 km. |
| ho-05 | - | 0.000 | - | Tom Thursday morning half 7 till 11. Gym session, then I helped him clean out the fridge and write a shopping list. 8 km. |
| ho-06 | 12.0 dB | 0.128 | - | Jake Christmas Eve 1 till 6. Drove down to his nan's in Frankston, 31 km. He was bouncing off the walls about Santa, so his mum bought me to Crosha Fenagon and to his cordial to make him drowsy. |
| ho-07 | - | 0.100 | - | Priya Christmas day 10 till 2 lunch our cousins in Dandenong she held her baby niece for ages and she got a sparkly new belt from Santa 16 km |
| ho-08 | - | 0.054 | - | Tommy, Boxing Day, half 9 till 1. Boxing Day sales at Highpoint, 27 km. He kept on clipping himself at the traffic lights, so I snapped the plastic guard over his buckle so he couldn't get it undone. |
| ho-09 | 12.0 dB | 0.500 | end, note | Rosa quarter past 9 till 2:1. Took her to Massdenic Copper and left her with a puffer hose. 4 km. |
| ho-10 | - | 0.222 | end, note | Priya off Sunday 2 till half 5. Walk along the beach at St Kildona gelato. 13 km. |

## Notes (read before quoting these numbers)

- Held-out: scripts written after the dev set was frozen, never used to tune prompts or code. Run it once
  per release; if a change is made because of a miss here, this set is no longer held out.
- Audio is Piper TTS (en_GB northern_english_male, a voice the dev set does not use), encoded as
  WhatsApp-style Ogg Opus voice notes. Still clean synthetic speech with no Australian accent. Car noise
  (brown, low-passed at 350 Hz, 12 dB SNR) on 3 memos.
- Week of Christmas 2026: Christmas Day (Fri 25) and Boxing Day (Sat 26) are Victorian public holidays.
  Covers 2 shifts crossing 8 pm, one "last night" memo, one memo with no day spoken, Australian number
  phrasing, 2 restrictive practices (chemical, mechanical) and 2 innocent notes with trap words
  (tablets, locked, held, belt). Tag rows are subsets of these 10 memos (small n).
- Pricing is not scored here; invoice lines are kept in results.json under runs[].lines.
