"""Held-out voice set: gold is self-consistent and every memo's audio exists. No model calls, no Piper."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VOICE = ROOT / "eval" / "voice"


def _make_heldout():
    spec = importlib.util.spec_from_file_location("make_heldout", VOICE / "heldout" / "make_heldout.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_heldout_gold_consistent_and_audio_present():
    gold = json.loads((VOICE / "heldout" / "scripts.json").read_text(encoding="utf-8"))
    assert _make_heldout().check(gold) == []
    assert len(gold["memos"]) == 10
    dev_scripts = {m["script"] for m in json.loads((VOICE / "gold.json").read_text(encoding="utf-8"))["memos"]}
    for m in gold["memos"]:
        assert m["script"] not in dev_scripts
        assert (VOICE / m["file"]).is_file(), m["file"]
        assert m["duration_s"] is not None and m["duration_s"] < 25
