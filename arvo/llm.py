"""Ollama chat client, stdlib only.

`chat()` sends one structured-output request to the local Ollama server and
returns the parsed JSON object plus timing/token metadata. The HTTP call goes
through the module-level `_transport` so tests can swap in a fake (no network).
"""

from __future__ import annotations

import base64
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

DEFAULT_MODEL = "gemma4:e4b"
OLLAMA_URL = os.environ.get("ARVO_OLLAMA_URL", "http://localhost:11434").rstrip("/")

Transport = Callable[[dict, float], dict]


class LLMError(RuntimeError):
    """Ollama unreachable, HTTP error, or the model gave unparseable JSON twice."""


def http_transport(payload: dict, timeout: float) -> dict:
    """POST payload to Ollama /api/chat and return the decoded JSON response."""
    url = OLLAMA_URL + "/api/chat"
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:500]
        raise LLMError(f"Ollama HTTP {e.code} for model {payload.get('model')!r}: {body}") from e
    except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
        raise LLMError(f"cannot reach Ollama at {url}: {e} (is `ollama serve` running?)") from e


# Swappable transport. Tests: monkeypatch.setattr(arvo.llm, "_transport", fake).
_transport: Transport = http_transport


def encode_image(img: Any) -> str:
    """bytes / file path / already-base64 string -> base64 string for messages[].images."""
    if isinstance(img, (bytes, bytearray)):
        return base64.b64encode(bytes(img)).decode("ascii")
    if isinstance(img, Path):
        return base64.b64encode(img.read_bytes()).decode("ascii")
    s = str(img)
    if len(s) < 4096 and Path(s).is_file():
        return base64.b64encode(Path(s).read_bytes()).decode("ascii")
    return s


def parse_json_object(content: str) -> dict:
    """Parse the model's reply into a dict. Tolerates a ```json fence. Raises ValueError."""
    text = (content or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text[:4].lower() == "json":
            text = text[4:]
        text = text.strip()
    obj = json.loads(text)  # json.JSONDecodeError is a ValueError
    if not isinstance(obj, dict):
        raise ValueError(f"expected a JSON object, got {type(obj).__name__}")
    return obj


RETRY_NUDGE = (
    "Your previous reply was not valid JSON. Reply again with only the JSON object "
    "that matches the schema, nothing else."
)


def chat(
    messages: list[dict],
    schema: dict,
    model: str = DEFAULT_MODEL,
    images: list | None = None,
    timeout: float = 300,
    *,
    options: dict | None = None,
    transport: Transport | None = None,
) -> tuple[dict, dict]:
    """One structured chat call. Returns (parsed_obj, meta).

    meta = {model, total_s, load_s, prompt_tokens, eval_tokens, attempts, done_reason}.
    Retries once (with a short JSON nudge) if the reply does not parse.
    """
    msgs = [dict(m) for m in messages]
    if images:
        enc = [encode_image(i) for i in images]
        idx = max((i for i, m in enumerate(msgs) if m.get("role") == "user"), default=len(msgs) - 1)
        msgs[idx]["images"] = list(msgs[idx].get("images") or []) + enc

    payload = {
        "model": model,
        "messages": msgs,
        "stream": False,
        "think": False,
        "format": schema,
        "options": {"temperature": 0, **(options or {})},
    }
    send = transport or _transport

    meta = {"model": model, "total_s": 0.0, "load_s": 0.0, "prompt_tokens": 0,
            "eval_tokens": 0, "attempts": 0, "done_reason": ""}
    t0 = time.perf_counter()
    content = ""
    last_err: Exception | None = None
    for attempt in (1, 2):
        req = payload if attempt == 1 else {
            **payload, "messages": msgs + [{"role": "user", "content": RETRY_NUDGE}]}
        resp = send(req, timeout)
        meta["attempts"] = attempt
        meta["load_s"] += (resp.get("load_duration") or 0) / 1e9
        meta["prompt_tokens"] += int(resp.get("prompt_eval_count") or 0)
        meta["eval_tokens"] += int(resp.get("eval_count") or 0)
        meta["done_reason"] = resp.get("done_reason", "")
        content = (resp.get("message") or {}).get("content", "")
        try:
            obj = parse_json_object(content)
        except ValueError as e:
            last_err = e
            continue
        meta["total_s"] = round(time.perf_counter() - t0, 3)
        meta["load_s"] = round(meta["load_s"], 3)
        return obj, meta
    raise LLMError(
        f"{model} returned invalid JSON twice ({last_err}); "
        f"done_reason={meta['done_reason']!r}; reply starts {content[:200]!r}")
