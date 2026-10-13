"""Shared fixtures. `fake_llm` replaces the Ollama HTTP transport: no network, no model."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class FakeLLM:
    """Queue replies (dict -> JSON content, str -> raw content) or set `.handler(payload) -> dict|str`.
    Every request payload is recorded in `.calls`."""

    def __init__(self):
        self.calls: list[dict] = []
        self.replies: list = []
        self.handler = None

    def queue(self, *replies):
        self.replies.extend(replies)
        return self

    def __call__(self, payload: dict, timeout: float) -> dict:
        self.calls.append(payload)
        if self.handler is not None:
            reply = self.handler(payload)
        elif self.replies:
            reply = self.replies.pop(0)
        else:
            raise AssertionError("FakeLLM: unexpected extra call")
        content = reply if isinstance(reply, str) else json.dumps(reply)
        return {"model": payload["model"], "message": {"role": "assistant", "content": content},
                "done": True, "done_reason": "stop", "total_duration": 1_500_000_000,
                "load_duration": 100_000_000, "prompt_eval_count": 50, "eval_count": 20}

    def user_text(self, i: int = -1) -> str:
        return next(m["content"] for m in reversed(self.calls[i]["messages"]) if m["role"] == "user")


@pytest.fixture
def fake_llm(monkeypatch):
    import arvo.llm

    fake = FakeLLM()
    monkeypatch.setattr(arvo.llm, "_transport", fake)
    return fake


@pytest.fixture
def roster():
    return json.loads((ROOT / "data" / "roster.example.json").read_text())
