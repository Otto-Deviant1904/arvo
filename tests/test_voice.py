"""Voice memos: chunking, ffmpeg argv, memo dates, diary formatting, pipeline/cli wiring. No network, no ffmpeg."""

from __future__ import annotations

import base64
import io
import json
import os
import sys
import types
import wave
from array import array
from datetime import date, datetime

import pytest

from arvo import voice

RATE = voice.RATE


def tone(seconds: float, amp: int = 8000) -> array:
    """Square-ish loud signal (stands in for speech)."""
    n = int(seconds * RATE)
    return array("h", (amp if (i // 20) % 2 else -amp for i in range(n)))


def silence(seconds: float) -> array:
    return array("h", bytes(2 * int(seconds * RATE)))


def write_wav(path, samples, rate=RATE, channels=1):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(array("h", samples).tobytes())
    return path


def wav_seconds(b64: str) -> float:
    with wave.open(io.BytesIO(base64.b64decode(b64)), "rb") as w:
        assert (w.getnchannels(), w.getframerate(), w.getsampwidth()) == (1, RATE, 2)
        return w.getnframes() / w.getframerate()


# ----------------------------------------------------------------------------- chunking

def test_plan_chunks_short_clip_is_one_chunk():
    assert voice.plan_chunks(tone(5)) == [(0, 5 * RATE)]
    assert voice.plan_chunks(tone(28)) == [(0, 28 * RATE)]
    assert voice.plan_chunks(array("h")) == [(0, 0)]


def test_plan_chunks_long_clip_cuts_in_quiet_gaps():
    # 26 s talk, 0.5 s pause, 26 s talk, 0.5 s pause, 10 s talk = 63 s
    s = tone(26) + silence(0.5) + tone(26) + silence(0.5) + tone(10)
    chunks = voice.plan_chunks(s)
    assert len(chunks) == 3
    assert chunks[0][0] == 0 and chunks[-1][1] == len(s)
    assert all(a < b and b - a <= 28 * RATE for a, b in chunks)
    assert all(chunks[i][1] == chunks[i + 1][0] for i in range(len(chunks) - 1))  # no gaps, no overlap
    # first cut lands inside the first pause (26.0 .. 26.5 s)
    assert 26 * RATE <= chunks[0][1] <= 26.5 * RATE
    second_pause = 26.5 * RATE + 26 * RATE
    assert second_pause <= chunks[1][1] <= second_pause + 0.5 * RATE


def test_plan_chunks_no_pause_still_respects_limit():
    s = tone(61)
    chunks = voice.plan_chunks(s)
    assert chunks[-1][1] == len(s) and all(b - a <= 28 * RATE for a, b in chunks)
    assert sum(b - a for a, b in chunks) == len(s)


# ----------------------------------------------------------------------------- ffmpeg

def test_ffmpeg_cmd_shape():
    assert voice.ffmpeg_cmd("memo one.m4a") == [
        "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-i", "memo one.m4a",
        "-vn", "-ac", "1", "-ar", "16000", "-acodec", "pcm_s16le", "-f", "s16le", "-"]
    assert voice.ffmpeg_cmd("x.ogg", "/opt/ff")[0] == "/opt/ff"


def test_load_pcm_skips_ffmpeg_for_16k_mono_wav(tmp_path):
    p = write_wav(tmp_path / "m.wav", tone(1))

    def boom(*a, **k):
        raise AssertionError("ffmpeg should not run")

    samples, converted = voice.load_pcm(p, run=boom)
    assert converted is False and len(samples) == RATE


def test_load_pcm_converts_other_formats(tmp_path, monkeypatch):
    stereo = write_wav(tmp_path / "s.wav", tone(1), rate=44100, channels=2)
    m4a = tmp_path / "memo.m4a"
    m4a.write_bytes(b"not really aac")
    monkeypatch.setattr(voice.shutil, "which", lambda name: "/usr/bin/ffmpeg")
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        return types.SimpleNamespace(returncode=0, stdout=array("h", [1, -2, 3]).tobytes(), stderr=b"")

    for src in (stereo, m4a):
        samples, converted = voice.load_pcm(src, run=fake_run)
        assert converted and list(samples) == [1, -2, 3]
    assert calls == [voice.ffmpeg_cmd(stereo, "/usr/bin/ffmpeg"), voice.ffmpeg_cmd(m4a, "/usr/bin/ffmpeg")]

    def bad_run(cmd, **kw):
        return types.SimpleNamespace(returncode=1, stdout=b"", stderr=b"memo.m4a: Invalid data found")

    with pytest.raises(voice.VoiceError, match="Invalid data found"):
        voice.load_pcm(m4a, run=bad_run)


def test_load_pcm_errors(tmp_path, monkeypatch):
    with pytest.raises(voice.VoiceError, match="no such audio file"):
        voice.load_pcm(tmp_path / "missing.m4a")
    m4a = tmp_path / "memo.m4a"
    m4a.write_bytes(b"x")
    monkeypatch.setattr(voice.shutil, "which", lambda name: None)
    with pytest.raises(voice.VoiceError, match="ffmpeg is not installed"):
        voice.load_pcm(m4a)


# ----------------------------------------------------------------------------- transcribe

def test_normalise_km():
    n = voice.normalise_km
    assert n("Footy, 12 k's.") == "Footy, 12 km."
    assert n("18 ks then 25 kays, 8 kms, 3 kilometres, 4k") == "18 km then 25 km, 8 km, 3 km, 4 km"
    assert n("No k's today. Took 2 kids.") == "No k's today. Took 2 kids."
    assert n("12 km") == "12 km"


def test_transcribe_chunks_and_prompt(fake_llm, tmp_path):
    p = write_wav(tmp_path / "long.wav", tone(20) + silence(0.5) + tone(15))
    fake_llm.queue({"transcript": "Jake, Monday, 3 till  half 8."}, {"transcript": "Footy, 12 k's."})
    text, meta = voice.transcribe(p, vocab=["Jake", "Mrs B", "Jake"])
    assert text == "Jake, Monday, 3 till half 8. Footy, 12 km."
    assert meta["chunks"] == 2 and meta["converted"] is False and meta["duration_s"] == 35.5
    assert meta["prompt_tokens"] == 100 and meta["eval_tokens"] == 40
    for call in fake_llm.calls:
        assert call["format"] == voice.TRANSCRIPT_SCHEMA and call["options"]["temperature"] == 0
        (img,) = call["messages"][-1]["images"]
        assert wav_seconds(img) <= 28
    assert sum(wav_seconds(c["messages"][-1]["images"][0]) for c in fake_llm.calls) == pytest.approx(35.5)
    prompt = fake_llm.user_text(0)
    assert "verbatim" in prompt and "Australian English" in prompt and "half eight\" -> half 8" in prompt
    assert "Names you may hear (spell them like this): Jake, Mrs B." in prompt


def test_transcribe_silent_or_tiny_audio_skips_model(fake_llm, tmp_path):
    p = write_wav(tmp_path / "blip.wav", tone(0.1))
    text, meta = voice.transcribe(p)
    assert text == "" and not fake_llm.calls and "shorter than" in meta["warnings"][0]


# ----------------------------------------------------------------------------- memos -> diary

def test_memo_date_from_filename_or_mtime(tmp_path):
    assert voice.memo_date("Recording_20261006_131000.ogg") == date(2026, 10, 6)
    assert voice.memo_date("/x/2026-10-05 20.47 jake.m4a") == date(2026, 10, 5)
    assert voice.memo_date("20261009-2115.m4a") == date(2026, 10, 9)
    assert voice.memo_date("memo-20261341.m4a", use_mtime=False) is None  # month 13 is not a date
    f = tmp_path / "Voice 001.m4a"
    f.write_bytes(b"x")
    ts = datetime(2026, 10, 8, 10, 40).timestamp()
    os.utime(f, (ts, ts))
    assert voice.memo_date(f) == date(2026, 10, 8)
    assert voice.memo_date(f, use_mtime=False) is None


def test_memos_to_diary_formatting(monkeypatch, tmp_path):
    heard = {"20261005-2047.m4a": "Jake, Monday, 3 till half 8.\n Footy, 12 km.",
             "20261006-1310.m4a": "",
             "Voice 002.m4a": "Mrs B, 7 till half past 10."}
    seen = []

    def fake_transcribe(path, model, *, vocab=()):
        seen.append((os.path.basename(path), model, tuple(vocab)))
        return heard[os.path.basename(path)], {"path": str(path), "duration_s": 3.0, "warnings": []}

    monkeypatch.setattr(voice, "transcribe", fake_transcribe)
    paths = []
    for name in heard:
        f = tmp_path / name
        f.write_bytes(b"x")
        paths.append(str(f))
    ts = datetime(2026, 10, 8, 10, 40).timestamp()
    os.utime(paths[2], (ts, ts))

    diary, metas = voice.memos_to_diary(paths, "gemma4:e4b", vocab=["Jake"])
    assert diary.splitlines() == [
        "[memo recorded Mon 2026-10-05] Jake, Monday, 3 till half 8. Footy, 12 km.",
        "[memo recorded Thu 2026-10-08] Mrs B, 7 till half past 10.",
    ]
    assert [m["recorded"] for m in metas] == ["2026-10-05", "2026-10-06", "2026-10-08"]
    assert metas[1]["transcript"] == "" and seen[0] == ("20261005-2047.m4a", "gemma4:e4b", ("Jake",))

    diary, _ = voice.memos_to_diary(paths[2:], "gemma4:e4b", use_mtime=False)
    assert diary == "Mrs B, 7 till half past 10."


def test_memo_line_resolves_yesterday_in_code():
    sun = date(2026, 10, 11)
    line = voice.memo_line("Priya, yesterday, 10 till 2:30.", sun)
    assert line == ('[Sat 2026-10-10 (said "yesterday" in a memo recorded 2026-10-11)] '
                    'Priya, yesterday, 10 till 2:30.')
    # if the model copies the whole heading as day_written, extract's code still lands on Saturday
    from arvo.extract import dates_from_day_written, week_window
    assert dates_from_day_written(line.split("]")[0], week_window("2026-10-11")) == [date(2026, 10, 10)]
    assert voice.memo_line("Tom, Last Night 6 till 11.", date(2026, 10, 6)).startswith(
        '[Mon 2026-10-05 (said "last night" in a memo recorded 2026-10-06)] ')
    assert voice.memo_line("Jake 4 till 9 tonight.", sun) == "[memo recorded Sun 2026-10-11] Jake 4 till 9 tonight."
    assert voice.memo_line("  Jake  4 till 9 ", None) == "Jake 4 till 9"


# ----------------------------------------------------------------------------- pipeline + cli

def _router(payload):
    props = payload["format"]["properties"]
    if "transcript" in props:
        return {"transcript": "Jakey, three till half 8, footy, 12 k's. Had to lock the pantry again."}
    if "shifts" in props:
        user = payload["messages"][-1]["content"]
        line = "[memo recorded Tue 2026-11-03] Jakey, three till half 8, footy, 12 km. Had to lock the pantry again."
        assert line in user
        return {"shifts": [{"day_written": "Tue", "date": "2026-11-03", "name_written": "Jakey",
                            "participant_id": "jake", "times_written": "three till half 8",
                            "start": "15:00", "end": "20:30", "km": 12,
                            "note": "footy, 12 km. Had to lock the pantry again."}]}
    return {"flags": [{"evidence_quote": "Had to lock the pantry again.", "explanation": "Food access restricted.",
                       "rp_type": "environmental", "harm_mentioned": False, "authorised_in_bsp": False}]}


def test_pipeline_run_with_audio(fake_llm, roster, monkeypatch, tmp_path):
    from arvo import pipeline
    monkeypatch.setitem(sys.modules, "arvo.calendar_au", None)
    monkeypatch.setattr(pipeline, "_price", lambda shifts, roster: ([], []))
    fake_llm.handler = _router
    memo = write_wav(tmp_path / "20261103-2045.wav", tone(3))
    res = pipeline.run("", roster, "2026-11-08", audio_paths=[str(memo)])
    assert [(s.participant_id, s.date, s.start, s.end, s.km) for s in res.shifts] == [
        ("jake", "2026-11-03", "15:00", "20:30", 12.0)]
    assert res.flags[0].rp_type == "environmental"
    assert res.warnings[0].startswith("voice memo 20261103-2045.wav (3 s, recorded 2026-11-03): heard \"Jakey")
    assert res.timings["memos"] == 1 and "transcribe_s" in res.timings
    names = fake_llm.user_text(0).split("spell them like this): ")[1].split(".\n")[0].split(", ")
    assert names[:4] == ["Jake", "Jakey", "Jake Morrison", "Priya"] and "Mrs B" in names  # 1-char aliases dropped
    json.dumps(res.to_dict())


def test_cli_process_voice_memos(monkeypatch, tmp_path, capsys):
    from arvo import cli, pipeline
    got = {}

    def fake_run(diary_text, roster, week_ending, model, image_path=None, audio_paths=None):
        got.update(diary_text=diary_text, image_path=image_path, audio_paths=audio_paths)
        from arvo.models import RunResult
        return RunResult([], [], [], [], model, {})

    monkeypatch.setattr(pipeline, "run", fake_run)
    a = write_wav(tmp_path / "a.wav", tone(1))
    b = tmp_path / "b.m4a"
    b.write_bytes(b"x")
    assert cli.main(["process", str(a), str(b), "--week-ending", "2026-11-08"]) == 0
    assert got == {"diary_text": "", "image_path": None, "audio_paths": [str(a), str(b)]}

    txt = tmp_path / "week.txt"
    txt.write_text("Tues Jake 3-8")
    assert cli.main(["process", str(txt), str(a), "--week-ending", "2026-11-08"]) == 2
    assert "voice memos" in capsys.readouterr().err
