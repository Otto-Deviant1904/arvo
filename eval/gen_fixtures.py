"""Deterministic synthetic shift diaries with gold labels for the Arvo eval.

Gold comes from how the fixtures are made: the structured shifts are drawn first,
then rendered to messy diary text. No model is involved anywhere in here.

    uv run --with pillow python eval/gen_fixtures.py            # writes eval/fixtures/
    uv run --with pillow python eval/gen_fixtures.py --no-images

Time-reading convention the text follows (and `parse_range` checks for every shift):
  - am/pm, 24h ("15:00"), noon, midday, midnight: as written.
  - a bare START hour is only written for 07:00-17:00: 7-11 = morning, 12 = noon, 1-5 = afternoon.
  - a bare END is the first matching clock time after the start (so "3 till 8:30" = 15:00-20:30,
    "9pm - 1" = 21:00-01:00 next day). "ish" times are gold at the stated time ("7ish" = 7:00).
  - "half 9" = 9:30, "quarter to 6" = 5:45, "quarter past 4" = 4:15.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "eval" / "fixtures"
ROSTER_PATH = ROOT / "data" / "roster.example.json"
HOLIDAYS_PATH = ROOT / "data" / "vic_public_holidays.json"
FONT_DIR = FIXTURES / "fonts"

SEED = 2026
N_WEEKS = 24
FIRST_WEEK_ENDING = date(2026, 10, 4)  # Sundays 2026-10-04 .. 2027-03-14, all after the 24 Sep 2026 price schedule
IMAGE_WEEKS = (2, 6, 9, 13, 16, 21)    # 1-based week numbers also rendered as a photo of a paper diary

# The public holidays shifts are deliberately placed on (Victoria, checked against data/vic_public_holidays.json).
TARGET_PH = {
    date(2026, 11, 3): "Melbourne Cup",
    date(2026, 12, 25): "Christmas Day",
    date(2026, 12, 26): "Boxing Day",
    date(2026, 12, 28): "Boxing Day additional day",
    date(2027, 1, 26): "Australia Day",  # a Tuesday in 2027
}
PH_SHIFTS_PER_DAY = 2
# Other Vic public holidays inside the window (New Year's Day, Labour Day 2027). No shift is put on these,
# so the only public-holiday shifts in the set are the targeted ones above.
AVOID = {date(2027, 1, 1), date(2027, 3, 8)}
OVERNIGHT_WEEKS = {7: ("jake", 4, 19 * 60, 25 * 60, "concert in the city"),       # Fri 19:00 -> Sat 01:00
                   19: ("priya", 2, 21 * 60, 25 * 60 + 30, "she was unwell so I stayed late")}  # Wed 21:00 -> Thu 01:30
DOUBLE_WEEKS = {w for w in range(1, N_WEEKS + 1) if w % 3 == 2}  # one participant gets 2 shifts on one day

PIDS = ["jake", "priya", "tom", "nonna"]
ALIAS_WEIGHTS = {
    "jake": [("Jake", 6), ("Jakey", 2), ("jake", 1.5), ("J", 0.5)],
    "priya": [("Priya", 4), ("Pri", 3), ("pri", 1), ("P", 0.4)],
    "tom": [("Tom", 4), ("Tommy", 2), ("T.O.", 2), ("tom", 1)],
    "nonna": [("Nonna", 4), ("Mrs B", 3), ("Rosa", 1.5), ("nonna", 1)],
}
# (text, when): morn = starts before 11:00, eve = ends 18:30 or later, day = a daytime outing, any = anytime
ACTIVITIES = {
    "jake": [("Bunnings + footy", "day"), ("pool then maccas", "day"), ("Chaddy shopping", "day"),
             ("bowling w/ his mates", "any"), ("cooked spag bol together", "eve"), ("library + walk", "day"),
             ("movies", "any"), ("gym then lunch", "day"), ("drove him to his cousin's", "any"),
             ("op shopping", "day"), ("basketball at the stadium", "any"), ("park + dog walk", "day"),
             ("haircut then Kmart", "day"), ("dinner at the RSL", "eve"), ("footy at the G", "eve")],
    "priya": [("shower + tea", "eve"), ("cooked dinner, did washing", "eve"), ("meal prep for the week", "day"),
              ("helped w/ shower, hair", "morn"), ("groceries + cooking", "day"), ("bedtime routine", "eve"),
              ("laundry + lunch", "day"), ("nails + movie", "any"), ("tidy up, cooked curry", "eve"),
              ("physio exercises + lunch", "day")],
    "tom": [("footy training", "any"), ("library", "day"), ("swimming", "any"), ("job club", "day"),
            ("shops + lunch", "day"), ("bus training into the city", "day"), ("gym", "any"),
            ("watched the footy at the pub (lemonade)", "eve"), ("fishing at the pier", "day"),
            ("Centrelink appt", "day")],
    "nonna": [("shower + brekkie", "morn"), ("showered, dressed, brekkie", "morn"), ("shower + meds prompt", "morn"),
              ("hair wash, lunch", "day"), ("dinner + pjs", "eve"), ("made her lunch, hung washing", "day"),
              ("church then lunch", "day"), ("podiatrist appt", "day"), ("brekkie, changed the bed", "morn"),
              ("tea + meds prompt", "eve")],
}


def pick_activity(rng: random.Random, pid: str, s: int, e: int, anytime_only: bool = False) -> str:
    ok = [t for t, when in ACTIVITIES[pid]
          if when == "any" or (not anytime_only and (
              (when == "morn" and s < 11 * 60) or (when == "eve" and e >= 18 * 60 + 30)
              or (when == "day" and 8 * 60 + 30 <= s < 15 * 60 and e <= 19 * 60)))]
    return rng.choice(ok) if ok else ""


PH_ACTIVITY = {date(2026, 11, 3): "Cup Day BBQ at the neighbours", date(2026, 12, 25): "Xmas lunch",
               date(2026, 12, 26): "Boxing Day sales", date(2026, 12, 28): "",
               date(2027, 1, 26): "Aus Day at the beach"}
KM_RANGE = {"jake": (3, 40), "tom": (3, 35), "priya": (0, 15), "nonna": (0, 10)}
KM_ZERO_P = {"jake": 0.15, "tom": 0.15, "priya": 0.4, "nonna": 0.45}

# ----------------------------------------------------------------------------------------------
# Held-out restrictive-practice notes. Written for this eval; wording deliberately different from the
# examples in arvo/rp.py's prompt and docs/sources/restrictive_practices.md (tests check for overlap).
# window = (latest_start, earliest_end) in minutes: the shift carrying the note must cover it.
# ----------------------------------------------------------------------------------------------
EVE = (18 * 60, 19 * 60 + 30)
LUNCH = (12 * 60, 14 * 60)
RP_NOTES = [
    # --- seclusion
    dict(id="rp01", pid="jake", rp_type="seclusion", harm=False, window=LUNCH,
         text="Jake kicked off after lunch so I sat against his bedroom door from the hallway till he'd quietened down, maybe 15 mins."),
    dict(id="rp02", pid="tom", rp_type="seclusion", harm=False, window=None,
         text="Tom was swearing at everyone so I made him stay in the garage on his own and kept the roller door down till he said sorry."),
    dict(id="rp03", pid="nonna", rp_type="seclusion", harm=False, window=None,
         text="Mrs B kept wandering into the kitchen so I left her out on the back verandah with the screen door latched for an hour, she was banging on it a bit."),
    dict(id="rp04", pid="priya", rp_type="seclusion", harm=True, window=None,
         text="Priya was screaming so I put her out in the back courtyard by herself and held the sliding door closed till she stopped. She scraped her knuckles on the flyscreen."),
    # --- chemical
    dict(id="rp05", pid="jake", rp_type="chemical", harm=False, window=(16 * 60, 18 * 60),
         text="Gave him the extra half tablet so he'd settle before tea."),
    dict(id="rp06", pid="tom", rp_type="chemical", harm=False, window=(13 * 60, 16 * 60),
         text="Tom was really wound up so I gave him a couple of his mum's anxiety pills, he slept most of the arvo."),
    dict(id="rp07", pid="nonna", rp_type="chemical", harm=False, window=LUNCH,
         text="Mixed one of her sleeping pills into her custard at lunch so she'd have a nap and stop calling out."),
    dict(id="rp08", pid="jake", rp_type="chemical", harm=True, window=None,
         text="Jake wouldn't sit still at the dentist so I gave him two of his hayfever tablets so he'd be dopey. He was wobbly on the stairs after and fell, grazed his elbow."),
    # --- mechanical
    dict(id="rp09", pid="nonna", rp_type="mechanical", harm=True, window=None,
         text="Did the strap up on her recliner so she'd stop getting up and wandering, she had a red mark on her tummy from it later."),
    dict(id="rp10", pid="jake", rp_type="mechanical", harm=False, window=None,
         text="Left the brakes on Jake's chair and parked him by the window so he'd stop following me round the kitchen."),
    dict(id="rp11", pid="tom", rp_type="mechanical", harm=False, window=EVE,
         text="Knotted Tom's jumper sleeves behind the chair so he'd stay sitting down for tea."),
    dict(id="rp12", pid="priya", rp_type="mechanical", harm=False, window=(19 * 60, 20 * 60 + 30),
         text="Put Priya's onesie on back to front at bedtime so she can't get at the zip and undress overnight."),
    # --- physical
    dict(id="rp13", pid="tom", rp_type="physical", harm=False, window=None,
         text="Tom wouldn't give the remote back so I wrapped both arms round him on the couch and kept him there till he let go of it."),
    dict(id="rp14", pid="jake", rp_type="physical", harm=False, window=None,
         text="Jake went for his brother so I got him onto the lounge room floor and lay across his back until he settled."),
    dict(id="rp15", pid="nonna", rp_type="physical", harm=False, window=None,
         text="She kept trying to pull her stockings off so I leant on her knees to keep her legs still while I got them back on."),
    dict(id="rp16", pid="priya", rp_type="physical", harm=True, window=EVE,
         text="Priya kept trying to get out of the shower so I held her there by the shoulders till I'd finished her hair, she's got a few red marks on her arm tonight."),
    # --- environmental
    dict(id="rp17", pid="jake", rp_type="environmental", harm=False, window=None,
         text="Put the padlock back on the fridge so he can't graze between meals."),
    dict(id="rp18", pid="nonna", rp_type="environmental", harm=False, window=None,
         text="Kept the back door keyed so she couldn't wander while I hung the washing out."),
    dict(id="rp19", pid="tom", rp_type="environmental", harm=False, window=None,
         text="Tom's not allowed in the shed with his drum kit till he's paid his mum back, I kept the key on me."),
    dict(id="rp20", pid="priya", rp_type="environmental", harm=False, window=None,
         text="Priya's not allowed to the Friday disco this week because of how she spoke to her mum, I rang and cancelled her spot."),
    # --- authorised regulated restrictive practices (still RP, but in the participant's BSP)
    dict(id="rp21", pid="priya", rp_type="chemical", harm=False, authorised=True, window=(18 * 60, 19 * 60 + 15),
         text="Gave Priya her as-needed lorazepam 0.5mg at 6.30, distress score was 5 so as per her plan, settled by 7."),
    dict(id="rp22", pid="nonna", rp_type="mechanical", harm=False, authorised=True, window=(18 * 60, 19 * 60),
         text="Put the sides up on Nonna's bed before I left tonight, as per her plan for falls."),
    # --- hard negatives: not a restrictive practice at all
    dict(id="neg01", pid="jake", window=None, text="Hardware shop had already locked up so we went to Coles instead."),
    dict(id="neg02", pid="priya", window=None, text="Priya strapped her new watch on and showed everyone at the cafe."),
    dict(id="neg03", pid="nonna", window=None, text="We walked arm in arm to the bakery the way she likes."),
    dict(id="neg04", pid="jake", window=None,
         text="Fridge door seal is broken again, told his mum so she can ring the landlord."),
    dict(id="neg05", pid="tom", window=None, text="Held the ladder while Tom changed the globe in the hallway."),
    dict(id="neg06", pid="tom", window=None, text="Tom asked me to hang on to his wallet at the footy so he wouldn't lose it again."),
    dict(id="neg07", pid="nonna", window=None, text="Walked to the letterbox with her frame, hip protectors on as usual."),
    dict(id="neg08", pid="jake", window=None, text="Jake did his own seatbelt and picked the music on the drive home."),
    dict(id="neg09", pid="priya", window=EVE, text="Prompted Priya with her usual tablets after tea, signed the med chart."),
    dict(id="neg10", pid="nonna", window=None,
         text="Mrs B wanted a nap so I pulled the curtains and left her bedroom door open."),
    dict(id="neg11", pid="nonna", window=EVE,
         text="She wants the front door locked at night cos she's scared of break-ins, so I locked it on my way out like she asked. She has her own key on the hook."),
    dict(id="neg12", pid="jake", window=None, text="Helped Jake strap his knee brace on for basketball like the physio showed us."),
    dict(id="neg13", pid="jake", window=LUNCH,
         text="Jake asked for his weighted blanket for his rest after lunch and took it off himself when he got up."),
    dict(id="neg14", pid="tom", window=None,
         text="Tom said he'd rather stay in and watch the cricket than go to the gym, so we stayed in."),
    dict(id="neg15", pid="nonna", window=LUNCH, text="Mrs B dozed off in her chair after lunch so I popped a blanket over her."),
    dict(id="neg16", pid="jake", window=(19 * 60 + 30, 20 * 60 + 15), text="Gave Jake his usual night meds at 8 off the chart."),
    dict(id="neg17", pid="priya", window=EVE,
         text="Priya didn't want her shower so we left it and tried again after tea, she was fine then."),
    dict(id="neg18", pid="tom", window=None,
         text="Bus driver told Tom off for being loud, he went quiet and sat up the back by himself. We talked it through after."),
    dict(id="neg19", pid="jake", window=None,
         text="Jake wanted the bathroom door locked while he showered for privacy, he unlocked it himself after."),
    dict(id="neg20", pid="priya", window=None,
         text="Priya wanted to sit in the car on her own for a bit after the shops, door open, I waited on the bench nearby."),
]


def rp_label(n: dict) -> dict:
    is_rp = "rp_type" in n
    return {"is_rp": is_rp, "rp_type": n.get("rp_type") if is_rp else None,
            "authorised_in_bsp": bool(n.get("authorised", False)), "harm_mentioned": bool(n.get("harm", False))}


# ----------------------------------------------------------------------------------------------
# Time phrases: a reference reader (the convention in the module docstring) and the renderer.
# ----------------------------------------------------------------------------------------------
_SUFFIX = r"\s?(am|pm|a|p)"


def _resolve(c: int, ap: str | None, role: str, start: int | None) -> int | None:
    """c = clock minutes in [0, 720). Apply am/pm or the bare-time convention."""
    if ap:
        val = c + (720 if ap.startswith("p") else 0)
        if role == "end" and start is not None and val <= start:
            val += 1440
        return val
    if role == "start":
        return c if 7 * 60 <= c < 12 * 60 else c + 720
    if start is None:
        return None
    for k in range(5):
        val = c + 720 * k
        if val > start:
            return val if val - start < 720 else None
    return None


def parse_time(tok: str, role: str = "start", start: int | None = None) -> int | None:
    """One written time -> minutes from the shift's midnight (end may be >= 1440 when overnight)."""
    s = tok.strip().lower()
    s = re.sub(r"\s*ish$", "", s)
    if s in ("noon", "midday", "12 noon"):
        val = 720
        return val + 1440 if role == "end" and start is not None and val <= start else val
    if s == "midnight":
        return 1440 if role == "end" else 0
    m = re.fullmatch(r"(half past|half|quarter past|qtr past|quarter to|qtr to) (\d{1,2})" + f"(?:{_SUFFIX})?", s)
    if m:
        word, h, ap = m.group(1), int(m.group(2)), m.group(3)
        if not 1 <= h <= 12:
            return None
        base = (h % 12) * 60
        c = base + 30 if word.startswith("half") else base + 15 if "past" in word else (base - 15) % 720
        return _resolve(c, ap, role, start)
    m = re.fullmatch(r"(\d{2}):(\d{2})", s)
    if m and (m.group(1).startswith("0") or int(m.group(1)) >= 13):  # 24-hour clock
        h, mi = int(m.group(1)), int(m.group(2))
        if h > 23 or mi > 59:
            return None
        val = h * 60 + mi
        if role == "end" and start is not None and val <= start:
            val += 1440
        return val
    m = re.fullmatch(r"(\d{1,2})(?:[:.](\d{2}))?" + f"(?:{_SUFFIX})?", s)
    if m:
        h, mi, ap = int(m.group(1)), int(m.group(2) or 0), m.group(3)
        if not 1 <= h <= 12 or mi > 59:
            return None
        return _resolve((h % 12) * 60 + mi, ap, role, start)
    return None


JOINERS = ["-", " - ", "–", " till ", " til ", " until ", " to "]


def parse_range(text: str) -> tuple[int, int] | None:
    """'3 till 8:30ish' -> (900, 1230). Tries every joiner split; the reading must be unique."""
    s = re.sub(r"^from\s+", "", text.strip(), flags=re.I)
    found = set()
    for j in JOINERS:
        i = s.find(j)
        while i != -1:
            a, b = s[:i], s[i + len(j):]
            st = parse_time(a, "start")
            if st is not None:
                en = parse_time(b, "end", st)
                if en is not None:
                    found.add((st, en))
            i = s.find(j, i + 1)
    return found.pop() if len(found) == 1 else None


def hhmm(mins: int) -> str:
    mins %= 1440
    return f"{mins // 60:02d}:{mins % 60:02d}"


def _is_bare(tok: str) -> bool:
    t = tok.lower()
    return not re.search(r"(am|pm|[ap])(ish)?$|noon|midday|midnight|^\d{2}:\d{2}", t) and not re.fullmatch(
        r"0\d:\d\d|1[3-9]:\d\d|2\d:\d\d", t)


def time_variants(t: int, role: str, start: int | None, h24: bool, ish_ok: bool) -> list[tuple[str, float]]:
    c = t % 1440
    h, m = divmod(c, 60)
    h12 = h % 12 or 12
    ap = "am" if h < 12 else "pm"
    mm = f"{m:02d}"
    hm = f"{h12}" if m == 0 else f"{h12}:{mm}"
    out: list[tuple[str, float]] = [(f"{h:02d}:{mm}", 12.0 if h24 else 0.2)]
    if not h24:
        out += [(hm + ap, 3), (hm + " " + ap, 0.8), (hm, 5), (hm + ap.upper(), 0.3)]
        if m:
            out += [(f"{h12}.{mm}", 1.2), (f"{h12}.{mm}{ap}", 0.5)]
        else:
            out += [(f"{h12}:00", 0.4), (f"{h12}{ap[0]}", 0.2)]
        if m == 30:
            out += [(f"half {h12}", 2), (f"half past {h12}", 0.8)]
        if m == 15:
            out += [(f"quarter past {h12}", 1.5), (f"qtr past {h12}", 0.4)]
        if m == 45 and h12 != 11:
            nh = h12 % 12 + 1
            out += [(f"quarter to {nh}", 1.5), (f"qtr to {nh}", 0.4)]
        if c == 720:
            out += [("noon", 2.5), ("midday", 2), ("12 noon", 0.4)]
        if c == 0 and role == "end":
            out += [("midnight", 4)]
        if ish_ok:
            out += [(hm + "ish", 1.5)]
    keep = []
    for txt, w in out:
        if parse_time(txt, role, start) != t:
            continue
        if role == "start" and _is_bare(txt) and not (7 * 60 <= t <= 17 * 60):
            continue
        if role == "start" and re.search(r"(quarter|qtr) to 7$", txt):
            continue
        keep.append((txt, w))
    return keep


def wchoice(rng: random.Random, items: list[tuple[str, float]]):
    total = sum(w for _, w in items)
    x = rng.random() * total
    for it, w in items:
        x -= w
        if x <= 0:
            return it
    return items[-1][0]


def render_range(rng: random.Random, s: int, e: int, h24: bool) -> str:
    for _ in range(50):
        ish = rng.random() < 0.08
        st = wchoice(rng, time_variants(s, "start", None, h24, ish and rng.random() < 0.4))
        et = wchoice(rng, time_variants(e, "end", s, h24, ish))
        joiners = [("-", 5), (" - ", 3), ("–", 1.2), (" till ", 3), (" til ", 1.2), (" until ", 0.6), (" to ", 2)]
        if " to " in st or " to " in et or re.fullmatch(r"\d{1,2}(ish)?", st):
            joiners = [j for j in joiners if j[0] != " to "]
        j = wchoice(rng, joiners)
        txt = st + j + et
        if j.strip() in ("till", "until", "to") and rng.random() < 0.12:
            txt = "from " + txt
        if parse_range(txt) == (s, e):
            return txt
    raise RuntimeError(f"could not render an unambiguous range for {hhmm(s)}-{hhmm(e)}")


# ----------------------------------------------------------------------------------------------
# Shift drawing
# ----------------------------------------------------------------------------------------------
@dataclass
class GShift:
    pid: str
    d: date
    s: int            # minutes from the shift date's midnight
    e: int            # may be >= 1440 (overnight)
    km: int
    note: str = ""
    kind: str = ""
    rp_id: str | None = None
    double: bool = False
    time_text: str = ""
    day_text: str = ""

    def gold(self) -> dict:
        return {"participant_id": self.pid, "date": self.d.isoformat(), "start": hhmm(self.s), "end": hhmm(self.e),
                "km": self.km, "note": self.note, "kind": self.kind, "overnight": self.e > 1440 - 1,
                "time_text": self.time_text, "day_text": self.day_text, "rp_note_id": self.rp_id}


def classify(d: date, s: int, e: int) -> str:
    if d in TARGET_PH:
        return "public_holiday"
    if e > 1440:
        return "overnight"
    if d.weekday() == 5:
        return "saturday"
    if d.weekday() == 6:
        return "sunday"
    if s >= 20 * 60:
        return "weekday_evening"
    if e > 20 * 60:
        return "weekday_cross_20"
    return "weekday_day"


def _step(rng, lo: int, hi: int) -> int:
    """Random time in [lo, hi] on a 15-min grid, mostly on :00 / :30."""
    grid = [t for t in range(lo, hi + 1, 15)]
    weights = [3 if t % 30 == 0 else 1 for t in grid]
    return rng.choices(grid, weights)[0]


def draw_times(rng, pid: str, kind: str) -> tuple[int, int]:
    H = 60
    if kind == "weekday_day":
        if pid == "nonna":
            s = _step(rng, 7 * H, 10 * H)
            e = s + _step(rng, 90, 210)
        else:
            s = _step(rng, 8 * H, 15 * H)
            e = min(s + _step(rng, 120, 360), 20 * H)
    elif kind == "weekday_cross_20":
        s = _step(rng, 15 * H, 19 * H)
        e = _step(rng, 20 * H + 15, 22 * H + 30)
    elif kind == "weekday_evening":
        s = _step(rng, 20 * H, 21 * H)
        e = min(s + _step(rng, 90, 180), 23 * H + 30)
    else:  # weekend / public holiday
        if pid == "nonna":
            s = _step(rng, 7 * H, 11 * H)
            e = s + _step(rng, 90, 240)
        else:
            s = _step(rng, 8 * H, 15 * H)
            e = min(s + _step(rng, 120, 360), 20 * H)
    return s, e


def times_for_window(rng, window: tuple[int, int]) -> tuple[int, int]:
    a, b = window
    s = max(7 * 60, a - rng.choice([0, 30, 60, 90, 120]))
    e = min(23 * 60, b + rng.choice([0, 30, 60, 90]))
    if e - s > 8 * 60:
        s = e - 8 * 60
    return s, e


def _abs(sh: GShift) -> tuple[int, int]:
    base = sh.d.toordinal() * 1440
    return base + sh.s, base + sh.e


def fits(new: GShift, shifts: list[GShift], allow_same_day: bool = False) -> bool:
    a0, a1 = _abs(new)
    if new.e - new.s < 60 or new.d in AVOID:
        return False
    for o in shifts:
        b0, b1 = _abs(o)
        if a0 < b1 + 30 and b0 < a1 + 30:  # one worker: 30 min gap between shifts
            return False
        if o.pid == new.pid and o.d == new.d and not allow_same_day:
            return False
    return True


def draw_km(rng, pid: str) -> int:
    if rng.random() < KM_ZERO_P[pid]:
        return 0
    lo, hi = KM_RANGE[pid]
    return rng.randint(max(1, lo), hi)


def make_week_shifts(rng: random.Random, wk: int, days: list[date], notes: list[dict]) -> list[GShift]:
    shifts: list[GShift] = []
    weekdays = [d for d in days if d.weekday() < 5 and d not in TARGET_PH and d not in AVOID]

    # 1. public holidays in this week
    for d in days:
        if d in TARGET_PH:
            for pid in rng.sample(PIDS, 4):
                if sum(1 for x in shifts if x.d == d) >= PH_SHIFTS_PER_DAY:
                    break
                for _ in range(30):
                    s, e = draw_times(rng, pid, "public_holiday")
                    g = GShift(pid, d, s, e, draw_km(rng, pid))
                    if fits(g, shifts):
                        shifts.append(g)
                        break
    # 2. overnight
    if wk in OVERNIGHT_WEEKS:
        pid, wd, s, e, act = OVERNIGHT_WEEKS[wk]
        g = GShift(pid, days[wd], s, e, draw_km(rng, pid), note=act)
        assert fits(g, shifts), "overnight shift does not fit"
        shifts.append(g)
    # 3. same participant twice on one day
    if wk in DOUBLE_WEEKS:
        pid = "nonna" if wk % 2 == 0 else "priya"
        for _ in range(100):
            d = rng.choice(weekdays)
            if pid == "nonna":
                g1 = GShift(pid, d, _step(rng, 7 * 60, 8 * 60 + 30), 0, draw_km(rng, pid), double=True)
                g1.e = g1.s + _step(rng, 90, 150)
                g2 = GShift(pid, d, _step(rng, 16 * 60 + 30, 18 * 60), 0, 0, double=True)
                g2.e = g2.s + _step(rng, 90, 120)
            else:
                g1 = GShift(pid, d, _step(rng, 8 * 60, 9 * 60 + 30), 0, draw_km(rng, pid), double=True)
                g1.e = g1.s + _step(rng, 120, 180)
                g2 = GShift(pid, d, _step(rng, 16 * 60, 18 * 60), 0, draw_km(rng, pid), double=True)
                g2.e = g2.s + _step(rng, 150, 240)
            if fits(g1, shifts) and fits(g2, shifts + [g1], allow_same_day=True):
                shifts += [g1, g2]
                break
    # 4. shifts that carry the held-out restrictive-practice notes
    for n in notes:
        for _ in range(400):
            d = rng.choice(days)
            if d in AVOID:
                continue
            if n["window"]:
                s, e = times_for_window(rng, n["window"])
            else:
                s, e = draw_times(rng, n["pid"], rng.choice(["weekday_day", "weekday_day", "weekday_cross_20", "weekend"]))
            g = GShift(n["pid"], d, s, e, draw_km(rng, n["pid"]), rp_id=n["id"])
            if fits(g, shifts):
                shifts.append(g)
                break
        else:
            raise RuntimeError(f"week {wk}: no room for note {n['id']}")
    # 5. fill
    target = max(rng.randint(5, 10), len(shifts) + 1)
    kinds = [("weekday_day", 40), ("weekday_cross_20", 16), ("weekday_evening", 7), ("saturday", 14), ("sunday", 11)]
    pref = {"weekday_day": PIDS, "weekday_cross_20": ["jake", "priya", "tom"], "weekday_evening": ["priya", "jake"],
            "saturday": PIDS, "sunday": PIDS}
    tries = 0
    while len(shifts) < target and tries < 2000:
        tries += 1
        kind = wchoice(rng, kinds)
        pid = rng.choice(pref[kind])
        pool = (weekdays if kind.startswith("weekday") else
                [d for d in days if d.weekday() == (5 if kind == "saturday" else 6) and d not in TARGET_PH])
        if not pool:
            continue
        d = rng.choice(pool)
        s, e = draw_times(rng, pid, kind)
        g = GShift(pid, d, s, e, draw_km(rng, pid))
        if fits(g, shifts):
            shifts.append(g)

    for g in shifts:
        g.kind = classify(g.d, g.s, g.e)
    shifts.sort(key=lambda x: (x.d, x.s))
    return shifts


# ----------------------------------------------------------------------------------------------
# Rendering to diary text
# ----------------------------------------------------------------------------------------------
DAY_NAMES = [
    ["Mon", "Monday", "mon", "MON", "monday", "Mon."],
    ["Tues", "Tue", "tues", "Tuesday", "TUES", "tue"],
    ["Wed", "Weds", "wed", "Wednesday", "WED", "weds"],
    ["Thurs", "Thu", "thurs", "Thursday", "THURS", "Thur"],
    ["Fri", "Friday", "fri", "FRI", "friday"],
    ["Sat", "Saturday", "sat", "SAT", "saturday"],
    ["Sun", "Sunday", "sun", "SUN", "sunday"],
]
DAY_TYPOS = [["Mnday"], ["Tuseday"], ["Wendsday", "Wednsday"], ["Thrusday", "Thurday"], ["Firday"], ["Satuday"], ["Sundy"]]
SHORT = ["Mon", "Tues", "Wed", "Thurs", "Fri", "Sat", "Sun"]
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
PH_NAMES = {
    date(2026, 11, 3): [("Cup Day", 3), ("cup day", 1.5), ("Tues (Cup Day)", 2), ("Melb Cup day", 1)],
    date(2026, 12, 25): [("Xmas Day", 3), ("Christmas Day", 2), ("Fri (Xmas)", 1.5)],
    date(2026, 12, 26): [("Boxing Day", 3), ("Sat 26th (Boxing Day)", 2)],
    date(2026, 12, 28): [("Mon (pub hol)", 2), ("Mon 28th public hol", 2), ("Mon", 1)],
    date(2027, 1, 26): [("Aus Day", 2), ("Australia Day", 2), ("Tues (Aus Day)", 2), ("26th Jan", 1)],
}
EMOJI = ["☕", "🏊", "🛒", "😴", "🏉", "🙄", "👍", "😅", "🎬", "🍝", "💊", "🚗"]


def ordinal(n: int) -> str:
    return f"{n}{'th' if 11 <= n % 100 <= 13 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def day_text(rng, d: date, typo_p: float) -> str:
    wd = d.weekday()
    opts = [(rng.choice(DAY_NAMES[wd]), 7), (f"{SHORT[wd]} {ordinal(d.day)}", 2), (f"the {ordinal(d.day)}", 0.8),
            (f"{d.day}/{d.month}", 1.2), (f"{SHORT[wd]} {d.day}/{d.month}", 1), (f"{d.day} {MONTHS[d.month - 1]}", 0.5)]
    if rng.random() < typo_p * 0.3:
        return rng.choice(DAY_TYPOS[wd])
    if d in PH_NAMES and rng.random() < 0.75:
        return wchoice(rng, PH_NAMES[d])
    return wchoice(rng, opts)


def typo(rng, text: str) -> str:
    words = text.split(" ")
    idx = [i for i, w in enumerate(words) if len(w) >= 5 and w.isalpha()]
    if not idx:
        return text
    i = rng.choice(idx)
    w = words[i]
    k = rng.randrange(1, len(w) - 2)
    words[i] = (w[:k] + w[k + 1] + w[k] + w[k + 2:]) if rng.random() < 0.6 else (w[:k] + w[k + 1:])
    return " ".join(words)


def km_text(rng, km: int) -> str:
    if km == 0:
        return wchoice(rng, [("", 6), ("no km", 1), ("0km", 0.6)])
    return wchoice(rng, [(f"{km}km", 5), (f"{km} km", 3), (f"{km}kms", 1.5), (f"drove {km}km", 1),
                         (f"({km}km)", 1.5), (f"{km}k", 0.6), (f"km {km}", 0.5)])


def part_of_day(s: int) -> str:
    return "morning" if s < 12 * 60 else "arvo" if s < 17 * 60 else "night"


def _join(*parts: str) -> str:
    return re.sub(r"\s+", " ", " ".join(p for p in parts if p)).strip()


def line_for(rng, g: GShift, day: str | None, who: str, emoji: str) -> str:
    """One diary line. `day` is None when the line sits under a day heading."""
    t, note, km = g.time_text, g.note, km_text(rng, g.km)
    long_note = len(note) > 45
    tail_note = (f", {note}" if note else "")
    if day is None:
        forms = [(lambda: _join(f"- {who} {t}{tail_note}", km, emoji), 4),
                 (lambda: _join(f"* {who} {t}", km, f"- {note}" if note else "", emoji), 2),
                 (lambda: _join(f"{who}: {t}", note, km, emoji), 2)]
        if long_note:
            forms.append((lambda: _join(f"- {who} {t}", km) + f"\n    {note}" + (f" {emoji}" if emoji else ""), 3))
        return wchoice(rng, forms)()
    pod = part_of_day(g.s)
    forms = [(lambda: _join(f"{day} - {who} {t}{tail_note}", f", {km}" if km else "", emoji).replace(" ,", ","), 5),
             (lambda: _join(f"{day} - {t} {who}", f"- {note}" if note else "", km, emoji), 3),
             (lambda: _join(f"{day}: {t} {who}{tail_note}", km, emoji), 3),
             (lambda: _join(f"{day} - {who} {t}", km, f"- {note}" if note else "", emoji), 2)]
    if not long_note:
        forms += [(lambda: _join(f"{who} {t} {day}", f"({note})" if note else "", km, emoji), 2),
                  (lambda: _join(f"{day} {pod} w/ {who} {t}", note, km, emoji), 2)]
    else:
        forms.append((lambda: _join(f"{day} - {who} {t}", km) + f"\n  {note}" + (f" {emoji}" if emoji else ""), 3))
    return re.sub(r"([.!?]),", r"\1", wchoice(rng, forms)())


def week_header(rng, days: list[date]) -> str:
    end, start = days[-1], days[0]
    return wchoice(rng, [("", 4), (f"wk ending {end.day}/{end.month}", 2), (f"w/e Sun {end.day} {MONTHS[end.month - 1]}", 1.5),
                         (f"Shifts wk of {start.day} {MONTHS[start.month - 1]}", 1.5), ("shifts this wk", 1),
                         (f"WEEK {start.day}/{start.month} - {end.day}/{end.month}", 1)])


def render_week(rng: random.Random, shifts: list[GShift], days: list[date], aliases: dict) -> tuple[str, dict]:
    style = {
        "headings": rng.random() < 0.35,
        "h24": rng.random() < 0.12,
        "emoji_p": rng.choice([0.0, 0.0, 0.12, 0.2]),
        "typo_p": rng.choice([0.03, 0.08, 0.15, 0.25]),
    }
    for g in shifts:
        g.time_text = render_range(rng, g.s, g.e, style["h24"])
    out: list[str] = []
    hdr = week_header(rng, days)
    if hdr:
        out += [hdr, ""] if rng.random() < 0.5 else [hdr]

    def who(g):
        return wchoice(rng, ALIAS_WEIGHTS[g.pid])

    def emo():
        return rng.choice(EMOJI) if rng.random() < style["emoji_p"] else ""

    used_days = {g.d for g in shifts}
    free_days = [d for d in days if d not in used_days and d not in AVOID]
    distractor = None
    if free_days and rng.random() < 0.3:
        d = rng.choice(free_days)
        distractor = (d, wchoice(rng, [(f"{rng.choice(DAY_NAMES[d.weekday()])} - day off", 3),
                                       (f"{SHORT[d.weekday()]} - nothing on 🙌", 1.5),
                                       (f"{SHORT[d.weekday()]} - Tom cancelled, gave me a week's notice so no charge", 1)]))
    forgot = None
    if not style["headings"] and len(shifts) >= 6 and rng.random() < 0.3:
        cands = [g for g in shifts if g.d.weekday() <= 1 and not g.double and g.d not in TARGET_PH]
        if cands:
            forgot = cands[0]

    if style["headings"]:
        for d in days:
            todays = [g for g in shifts if g.d == d]
            if distractor and distractor[0] == d:
                out.append(distractor[1])
                continue
            if not todays:
                continue
            g0 = todays[0]
            g0.day_text = day_text(rng, d, style["typo_p"])
            head = wchoice(rng, [(g0.day_text.upper(), 2), (g0.day_text, 3), (f"~ {g0.day_text} ~", 1),
                                 (g0.day_text + ":", 2)])
            out.append(head)
            for g in todays:
                g.day_text = g0.day_text
                out.append(line_for(rng, g, None, who(g), emo()))
            if rng.random() < 0.4:
                out.append("")
    else:
        i = 0
        ordered = [g for g in shifts if g is not forgot]
        while i < len(ordered):
            g = ordered[i]
            if distractor and distractor[0] < g.d:
                out.append(distractor[1])
                distractor = None
            g.day_text = day_text(rng, g.d, style["typo_p"])
            nxt = ordered[i + 1] if i + 1 < len(ordered) else None
            if g.double and nxt is not None and nxt.double and nxt.d == g.d and nxt.pid == g.pid and rng.random() < 0.5:
                nxt.day_text = g.day_text
                km1 = km_text(rng, g.km)
                line = _join(f"{g.day_text} - {who(g)} {g.time_text}{', ' + g.note if g.note else ''}", km1,
                             f"then back {nxt.time_text}", nxt.note, km_text(rng, nxt.km), emo())
                out.append(re.sub(r"([.!?]),", r"\1", line))
                i += 2
                continue
            out.append(line_for(rng, g, g.day_text, who(g), emo()))
            if rng.random() < 0.08:
                out.append("")
            i += 1
        if distractor:
            out.append(distractor[1])
        if forgot is not None:
            forgot.day_text = rng.choice(DAY_NAMES[forgot.d.weekday()][:2])
            body = line_for(rng, forgot, forgot.day_text, who(forgot), "")
            out.append(wchoice(rng, [("oh and forgot - ", 2), ("missed one: ", 1.5), ("+ ", 1)]) + body)
    if rng.random() < 0.25:
        out.append(wchoice(rng, [("invoice sunday!!", 1), ("send Bayside the invoice", 1), ("check km for Tom??", 1),
                                 ("rego due next wk", 1)]))
    text = "\n".join(out).strip() + "\n"
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text, style


# ----------------------------------------------------------------------------------------------
# PNG rendering: a phone photo of a paper diary page
# ----------------------------------------------------------------------------------------------
def _font_path() -> Path:
    for ext in ("*.ttf", "*.otf"):
        found = sorted(FONT_DIR.glob(ext))
        if found:
            return found[0]
    return Path("/usr/share/fonts/TTF/DejaVuSans.ttf")


def png_text(text: str) -> str:
    """Drop emoji/glyphs the handwriting font lacks; the gold does not depend on them."""
    text = text.replace("–", "-").replace("’", "'")
    text = "".join(ch for ch in text if ord(ch) < 0x2000 or ch == "\n")
    return "\n".join(re.sub(r"\s+$", "", ln) for ln in text.splitlines())


def render_png(text: str, out_path: Path, rng: random.Random) -> None:
    from PIL import Image, ImageDraw, ImageFilter, ImageFont

    W, H = 1100, 1450
    top, gap, left = 150, 46, 120
    lines: list[str] = []
    font_size = 30
    font = ImageFont.truetype(str(_font_path()), font_size)
    maxw = W - left - 60
    for raw in png_text(text).splitlines():
        indent = len(raw) - len(raw.lstrip(" "))
        words, cur = raw.strip().split(" "), ""
        for w in words:
            cand = (cur + " " + w).strip()
            if font.getlength(" " * indent + cand) > maxw and cur:
                lines.append(" " * indent + cur)
                cur, indent = w, max(indent, 4)
            else:
                cur = cand
        lines.append(" " * indent + cur)
    n_rows = (H - top - 40) // gap
    if len(lines) > n_rows:
        gap = max(34, (H - top - 40) // len(lines))
        font_size = int(gap * 0.66)
        font = ImageFont.truetype(str(_font_path()), font_size)

    # paper with faint blotches
    paper = Image.new("RGB", (W, H), (247, 243, 231))
    sw, sh = W // 40 + 2, H // 40 + 2
    blot = Image.new("L", (sw, sh))
    blot.putdata([rng.randint(0, 60) for _ in range(sw * sh)])
    blot = blot.resize((W, H), Image.BILINEAR)
    paper = Image.composite(Image.new("RGB", (W, H), (232, 224, 204)), paper, blot)
    d = ImageDraw.Draw(paper)
    for y in range(top, H - 30, gap):
        d.line([(30, y), (W - 30, y)], fill=(186, 204, 226), width=2)
    d.line([(left - 22, 0), (left - 22, H)], fill=(228, 170, 170), width=2)

    ink = (24 + rng.randint(0, 20), 34 + rng.randint(0, 20), 92 + rng.randint(0, 30))
    for i, ln in enumerate(lines):
        if not ln.strip():
            continue
        layer = Image.new("L", (W, gap + 30), 0)
        ImageDraw.Draw(layer).text((left + rng.randint(-4, 6) + font.getlength(ln[: len(ln) - len(ln.lstrip())]),
                                    6), ln.strip(), font=font, fill=255)
        layer = layer.rotate(rng.uniform(-0.6, 0.6), resample=Image.BICUBIC)
        y = top + i * gap - font_size - 10 + rng.randint(-2, 2)
        paper.paste(Image.new("RGB", layer.size, ink), (0, y), layer)

    angle = rng.choice([-1, 1]) * rng.uniform(0.8, 2.4)
    bg = (88, 70, 56)
    rot = paper.rotate(angle, resample=Image.BICUBIC, expand=True, fillcolor=bg)
    canvas = Image.new("RGB", (W + 120, H + 120), bg)
    canvas.paste(rot, ((canvas.width - rot.width) // 2 + rng.randint(-15, 15),
                       (canvas.height - rot.height) // 2 + rng.randint(-15, 15)))
    # uneven phone lighting: darker towards one corner
    shade = Image.linear_gradient("L").resize(canvas.size)
    if rng.random() < 0.5:
        shade = shade.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
    shade = shade.point(lambda v: int(v * 0.22))
    canvas = Image.composite(Image.new("RGB", canvas.size, (0, 0, 0)), canvas, shade)
    canvas = canvas.filter(ImageFilter.GaussianBlur(0.7))
    canvas.save(out_path, format="PNG", optimize=True)


# ----------------------------------------------------------------------------------------------
# Driver
# ----------------------------------------------------------------------------------------------
def load_aliases() -> dict:
    roster = json.loads(ROSTER_PATH.read_text(encoding="utf-8"))
    return {p["id"]: p["aliases"] for p in roster["participants"]}


def check_holidays(weeks: list[list[date]]) -> list[str]:
    """Cross-check TARGET_PH / AVOID against data/vic_public_holidays.json (if present). Never changes output."""
    if not HOLIDAYS_PATH.exists():
        return [f"{HOLIDAYS_PATH} missing: using the built-in target dates only"]
    found = set(re.findall(r'"date"\s*:\s*"(\d{4}-\d{2}-\d{2})"', HOLIDAYS_PATH.read_text(encoding="utf-8")))
    hol = {date.fromisoformat(x) for x in found}
    problems = [f"target {d} is not in {HOLIDAYS_PATH.name}" for d in TARGET_PH if d not in hol]
    in_window = {d for days in weeks for d in days if d in hol}
    problems += [f"public holiday {d} is in the window but neither targeted nor avoided"
                 for d in sorted(in_window - set(TARGET_PH) - AVOID)]
    return problems


def generate(out_dir: Path = FIXTURES, seed: int = SEED, images: bool = True, n_weeks: int = N_WEEKS) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    aliases = load_aliases()
    for pid, pairs in ALIAS_WEIGHTS.items():  # every alias we write must be a roster alias (case-insensitive)
        assert all(a.casefold() in {x.casefold() for x in aliases[pid]} for a, _ in pairs), pid
    weeks = [[FIRST_WEEK_ENDING + timedelta(days=7 * w - 6 + i) for i in range(7)] for w in range(n_weeks)]
    problems = check_holidays(weeks)
    if any("not in" in p or "neither" in p for p in problems):
        raise SystemExit("holiday check failed: " + "; ".join(problems))

    notes = list(RP_NOTES)
    random.Random(f"{seed}-rp").shuffle(notes)
    week_notes: dict[int, list[dict]] = {w: [] for w in range(1, n_weeks + 1)}
    for i, n in enumerate(notes):
        week_notes[i * n_weeks // len(notes) + 1].append(n)

    manifest = {"seed": seed, "weeks": [], "counts": {}, "holiday_check": problems}
    kinds: dict[str, int] = {}
    rp_rows = []
    for w in range(1, n_weeks + 1):
        rng = random.Random(f"{seed}-week-{w}")
        days = weeks[w - 1]
        shifts = make_week_shifts(rng, w, days, week_notes[w])
        by_id = {n["id"]: n for n in week_notes[w]}
        for g in shifts:  # notes
            if g.note:
                continue
            if g.d in TARGET_PH:
                act = PH_ACTIVITY[g.d] if PH_ACTIVITY[g.d] and rng.random() < 0.7 else \
                    pick_activity(rng, g.pid, g.s, g.e, anytime_only=True)
            else:
                act = pick_activity(rng, g.pid, g.s, g.e) if rng.random() < 0.85 else ""
            if act and rng.random() < 0.12:
                act = typo(rng, act)
            if g.rp_id:
                rp_text = by_id[g.rp_id]["text"]
                g.note = f"{act}. {rp_text}" if act and rng.random() < 0.5 else rp_text
            else:
                g.note = act
        text, style = render_week(rng, shifts, days, aliases)
        name = f"week{w:02d}"
        rp_gold = []
        for g in shifts:
            assert parse_range(g.time_text) == (g.s, g.e), (name, g.time_text)
            assert g.time_text in text and (not g.note or g.note in text), (name, g.time_text, g.note)
            kinds[g.kind] = kinds.get(g.kind, 0) + 1
            if g.rp_id:
                n = by_id[g.rp_id]
                row = {"note_id": n["id"], "participant_id": g.pid, "date": g.d.isoformat(), "text": n["text"],
                       **rp_label(n)}
                rp_gold.append(row)
                rp_rows.append({**row, "week": name})
        image = None
        if images and w in IMAGE_WEEKS:
            image = f"{name}.png"
            render_png(text, out_dir / image, random.Random(f"{seed}-png-{w}"))
        gold = {"week": name, "week_ending": days[-1].isoformat(), "seed": seed, "style": style,
                "image": image if w in IMAGE_WEEKS else None,
                "shifts": [g.gold() for g in shifts], "rp": rp_gold}
        (out_dir / f"{name}.txt").write_text(text, encoding="utf-8")
        (out_dir / f"{name}.gold.json").write_text(json.dumps(gold, indent=2, ensure_ascii=False) + "\n",
                                                   encoding="utf-8")
        manifest["weeks"].append({"week": name, "week_ending": gold["week_ending"], "n_shifts": len(shifts),
                                  "n_rp_notes": len(rp_gold), "image": gold["image"]})

    rp_rows.sort(key=lambda r: r["note_id"])
    with (out_dir / "rp_notes.jsonl").open("w", encoding="utf-8") as f:
        for r in rp_rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    labels = [rp_label(n) for n in RP_NOTES]
    manifest["counts"] = {
        "weeks": n_weeks,
        "shifts": sum(x["n_shifts"] for x in manifest["weeks"]),
        "shift_kinds": dict(sorted(kinds.items())),
        "same_day_doubles": len(DOUBLE_WEEKS),
        "rp_notes": len(labels),
        "rp_unauthorised_by_type": {t: sum(1 for x in labels if x["rp_type"] == t and not x["authorised_in_bsp"])
                                    for t in ("seclusion", "chemical", "mechanical", "physical", "environmental")},
        "rp_authorised": sum(1 for x in labels if x["authorised_in_bsp"]),
        "rp_harm_mentioned": sum(1 for x in labels if x["harm_mentioned"]),
        "hard_negatives": sum(1 for x in labels if not x["is_rp"]),
        "images": sum(1 for x in manifest["weeks"] if x["image"]),
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return manifest


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--out", type=Path, default=FIXTURES)
    ap.add_argument("--no-images", action="store_true")
    a = ap.parse_args(argv)
    m = generate(a.out, a.seed, images=not a.no_images)
    print(json.dumps(m["counts"], indent=2))
    for p in m["holiday_check"]:
        print("note:", p, file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
