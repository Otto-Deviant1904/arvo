"""Local web server for Arvo: serves web/index.html and a small JSON API.

stdlib only (http.server). Binds to loopback only; nothing is reachable from the network.

    GET  /             web/index.html
    GET  /api/health   {ok, model, ollama_up, model_available}
    GET  /api/roster   the roster JSON (data/roster.example.json by default)
    POST /api/run      {diary_text, week_ending, model?, image_b64?, audio_b64_list?, audio_dates?}
                       -> RunResult.to_dict() + {"invoices_html": {participant_id: html}}
"""

from __future__ import annotations

import base64
import binascii
import importlib
import json
import os
import sys
import tempfile
import threading
import traceback
import urllib.request
from dataclasses import asdict, fields, is_dataclass
from datetime import date
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .models import InvoiceLine, Participant

ROOT = Path(__file__).resolve().parent.parent
WEB_INDEX = ROOT / "web" / "index.html"
DEFAULT_ROSTER = ROOT / "data" / "roster.example.json"
FALLBACK_MODEL = "gemma4:e4b"
FALLBACK_OLLAMA_URL = "http://localhost:11434"
MAX_BODY_BYTES = 25 * 1024 * 1024
MAX_MEMOS = 60
LOOPBACK_HOSTS = {"127.0.0.1", "localhost"}

# The page talks only to this server. The browser enforces it: no third-party
# requests, no fonts or scripts from a CDN, no form posts elsewhere.
PAGE_CSP = (
    "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
    "img-src 'self' blob: data:; media-src blob:; connect-src 'self'; font-src 'self'; "
    "base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
)

_IMAGE_SUFFIX = {
    b"\x89PNG": ".png",
    b"\xff\xd8\xff": ".jpg",
    b"GIF8": ".gif",
    b"RIFF": ".webp",
}


class BadRequest(Exception):
    def __init__(self, message: str, status: HTTPStatus = HTTPStatus.BAD_REQUEST):
        super().__init__(message)
        self.status = status


# ---------------------------------------------------------------- helpers

def default_model() -> str:
    try:
        from . import llm
        return getattr(llm, "DEFAULT_MODEL", FALLBACK_MODEL)
    except Exception:  # llm.py missing or mid-edit: the server still starts
        return FALLBACK_MODEL


def _ollama_url() -> str:
    try:
        from . import llm
        return getattr(llm, "OLLAMA_URL", FALLBACK_OLLAMA_URL)
    except Exception:
        return FALLBACK_OLLAMA_URL


def ollama_status(model: str, timeout: float = 1.0) -> tuple[bool, bool]:
    """(ollama_up, model_available). Talks to localhost Ollama only, ignoring proxy env vars."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(_ollama_url() + "/api/tags", timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return False, False
    names = set()
    for m in data.get("models", []) if isinstance(data, dict) else []:
        if isinstance(m, dict):
            names.update(str(m.get(k, "")) for k in ("name", "model"))
    return True, (model in names or f"{model}:latest" in names)


def load_roster(path: Path) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("roster must be a JSON object with 'worker' and 'participants'")
    return data


def _participants(roster: dict) -> list[Participant]:
    names = {f.name for f in fields(Participant)}
    out = []
    for p in roster.get("participants", []):
        if isinstance(p, Participant):
            out.append(p)
        elif isinstance(p, dict):
            out.append(Participant(**{k: v for k, v in p.items() if k in names}))
    return out


def _as_line(line) -> InvoiceLine:
    if isinstance(line, InvoiceLine):
        return line
    if isinstance(line, dict):
        names = {f.name for f in fields(InvoiceLine)}
        return InvoiceLine(**{k: v for k, v in line.items() if k in names})
    raise TypeError(f"unexpected invoice line type {type(line).__name__}")


def _to_dict(result) -> dict:
    if hasattr(result, "to_dict"):
        return result.to_dict()
    if is_dataclass(result):
        return asdict(result)
    if isinstance(result, dict):
        return dict(result)
    raise TypeError(f"pipeline.run returned {type(result).__name__}, expected RunResult")


def _decode_image(image_b64: str) -> tuple[bytes, str]:
    if not isinstance(image_b64, str):
        raise BadRequest("image_b64 must be a base64 string")
    if image_b64.startswith("data:"):
        image_b64 = image_b64.partition(",")[2]
    try:
        raw = base64.b64decode(image_b64, validate=False)
    except (binascii.Error, ValueError):
        raise BadRequest("image_b64 is not valid base64")
    if not raw:
        raise BadRequest("image_b64 is empty")
    suffix = next((s for magic, s in _IMAGE_SUFFIX.items() if raw.startswith(magic)), None)
    if suffix is None:
        raise BadRequest("the photo must be a PNG, JPG, GIF or WebP image")
    return raw, suffix


def _strip_b64(value) -> bytes:
    if not isinstance(value, str):
        raise BadRequest("audio_b64_list must be a list of base64 strings")
    if value.startswith("data:"):
        value = value.partition(",")[2]
    try:
        return base64.b64decode(value, validate=False)
    except (binascii.Error, ValueError):
        raise BadRequest("a voice memo is not valid base64")


def _decode_memos(data: dict) -> list[tuple[bytes, str | None]]:
    """[(audio bytes, 'YYYY-MM-DD' or None)] in upload order."""
    memos = data.get("audio_b64_list") or []
    dates = data.get("audio_dates") or []
    if not isinstance(memos, list):
        raise BadRequest("audio_b64_list must be a list of base64 strings")
    if not isinstance(dates, list):
        raise BadRequest("audio_dates must be a list of dates (YYYY-MM-DD)")
    if len(memos) > MAX_MEMOS:
        raise BadRequest(f"too many voice memos (at most {MAX_MEMOS} per run)")
    if len(dates) > len(memos):
        raise BadRequest("more audio_dates than voice memos")
    out = []
    for i, b64 in enumerate(memos):
        raw = _strip_b64(b64)
        if not raw:
            raise BadRequest(f"voice memo {i + 1} is empty")
        d = dates[i] if i < len(dates) else None
        if d in (None, ""):
            d = None
        else:
            try:
                d = date.fromisoformat(d).isoformat() if isinstance(d, str) else None
            except ValueError:
                d = None
            if d is None:
                raise BadRequest(f"audio_dates[{i}] must be a date like 2026-10-06")
        out.append((raw, d))
    return out


def _voice_error_class():
    try:
        return getattr(importlib.import_module("arvo.voice"), "VoiceError", None)
    except Exception:
        return None


def render_invoices(result, roster: dict, week_ending: str) -> dict | None:
    """{participant_id: html} via arvo.invoice.render_invoice_html, or None if that is not available."""
    try:
        invoice = importlib.import_module("arvo.invoice")
    except ImportError:
        return None
    except Exception:  # module present but broken: keep the run, skip invoices
        traceback.print_exc()
        return None
    render = getattr(invoice, "render_invoice_html", None)
    if not callable(render):
        return None

    raw_lines = getattr(result, "lines", None)
    if raw_lines is None and isinstance(result, dict):
        raw_lines = result.get("lines", [])
    by_pid: dict[str, list[InvoiceLine]] = {}
    for line in raw_lines or []:
        ln = _as_line(line)
        by_pid.setdefault(ln.participant_id, []).append(ln)

    worker = roster.get("worker", {}) or {}
    stamp = week_ending.replace("-", "")
    today = date.today().isoformat()
    out: dict[str, str] = {}
    for p in _participants(roster):
        lines = by_pid.get(p.id)
        if not lines:
            continue
        try:
            html = render(p, worker, lines, f"ARVO-{stamp}-{p.id.upper()}", today)
        except Exception:
            traceback.print_exc()
            continue
        if isinstance(html, str):
            out[p.id] = html
    return out


# ---------------------------------------------------------------- server

class ArvoServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, model: str, roster_path: Path, quiet: bool = False):
        super().__init__(address, ArvoHandler)
        self.model = model
        self.roster_path = Path(roster_path)
        self.quiet = quiet
        self.run_lock = threading.Lock()  # one model run at a time: the GPU is small

    def allowed_hosts(self) -> set[str]:
        port = self.server_address[1]
        return {f"{h}:{port}" for h in LOOPBACK_HOSTS} | (LOOPBACK_HOSTS if port == 80 else set())


class ArvoHandler(BaseHTTPRequestHandler):
    server: ArvoServer
    server_version = "Arvo"
    sys_version = ""
    timeout = 60  # socket read timeout; the model run itself is not bounded by this

    # ---- plumbing

    def log_message(self, fmt, *args):  # never logs bodies, only the request line
        if not self.server.quiet:
            sys.stderr.write("arvo: " + (fmt % args) + "\n")

    def _send(self, status: int, body: bytes, content_type: str, extra: dict | None = None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, status: int, payload: dict):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8")

    def _error(self, status: int, message: str):
        self._json(status, {"ok": False, "error": message})

    def _host_ok(self) -> bool:
        # DNS-rebinding guard: a web page on another site must not reach this server by name.
        host = self.headers.get("Host")
        return host is None or host.lower() in self.server.allowed_hosts()

    # ---- GET

    def do_GET(self):
        if not self._host_ok():
            return self._error(HTTPStatus.FORBIDDEN, "unexpected Host header")
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html"):
            try:
                body = WEB_INDEX.read_bytes()
            except OSError:
                return self._error(HTTPStatus.NOT_FOUND, f"missing {WEB_INDEX}")
            return self._send(HTTPStatus.OK, body, "text/html; charset=utf-8",
                              {"Content-Security-Policy": PAGE_CSP})
        if path == "/api/health":
            up, available = ollama_status(self.server.model)
            return self._json(HTTPStatus.OK, {"ok": True, "model": self.server.model,
                                              "ollama_up": up, "model_available": available})
        if path == "/api/roster":
            try:
                return self._json(HTTPStatus.OK, load_roster(self.server.roster_path))
            except (OSError, ValueError) as e:
                return self._error(HTTPStatus.INTERNAL_SERVER_ERROR, f"could not read roster: {e}")
        if path == "/favicon.ico":
            return self._send(HTTPStatus.NO_CONTENT, b"", "image/x-icon")
        return self._error(HTTPStatus.NOT_FOUND, f"no such page: {path}")

    do_HEAD = do_GET

    # ---- POST

    def do_POST(self):
        if not self._host_ok():
            return self._error(HTTPStatus.FORBIDDEN, "unexpected Host header")
        path = self.path.split("?", 1)[0]
        if path != "/api/run":
            return self._error(HTTPStatus.NOT_FOUND, f"no such endpoint: {path}")
        try:
            payload = self._read_json()
            diary_text, week_ending, model, image, memos = self._validate(payload)
        except BadRequest as e:
            return self._error(e.status, str(e))

        if not self.server.run_lock.acquire(blocking=False):
            return self._error(HTTPStatus.CONFLICT, "a run is already in progress; wait for it to finish")
        try:
            out = self._run(diary_text, week_ending, model, image, memos)
        except Exception as e:
            voice_error = _voice_error_class() if memos else None
            if voice_error is not None and isinstance(e, voice_error):
                return self._error(HTTPStatus.BAD_REQUEST, str(e))  # unreadable audio: the user can fix it
            traceback.print_exc()
            return self._error(HTTPStatus.INTERNAL_SERVER_ERROR, f"{type(e).__name__}: {e}")
        finally:
            self.server.run_lock.release()
        return self._json(HTTPStatus.OK, out)

    def _read_json(self) -> dict:
        ctype = (self.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
        if ctype != "application/json":
            self.close_connection = True
            raise BadRequest("send JSON with Content-Type: application/json", HTTPStatus.UNSUPPORTED_MEDIA_TYPE)
        length = self.headers.get("Content-Length")
        if length is None:
            self.close_connection = True
            raise BadRequest("Content-Length is required", HTTPStatus.LENGTH_REQUIRED)
        try:
            n = int(length)
        except ValueError:
            self.close_connection = True
            raise BadRequest("bad Content-Length")
        if n < 0 or n > MAX_BODY_BYTES:
            self.close_connection = True  # do not read a body we refuse
            raise BadRequest(f"request is larger than {MAX_BODY_BYTES // (1024 * 1024)} MB; "
                             "try a smaller photo or fewer voice memos", HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
        raw = self.rfile.read(n)
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise BadRequest("body is not valid JSON")
        if not isinstance(data, dict):
            raise BadRequest("body must be a JSON object")
        return data

    def _validate(self, data: dict):
        diary_text = data.get("diary_text") or ""
        if not isinstance(diary_text, str):
            raise BadRequest("diary_text must be a string")
        week_ending = data.get("week_ending")
        if not isinstance(week_ending, str):
            raise BadRequest("week_ending is required (YYYY-MM-DD)")
        try:
            date.fromisoformat(week_ending)
        except ValueError:
            raise BadRequest("week_ending must be a date like 2026-10-11")
        model = data.get("model") or self.server.model
        if not isinstance(model, str):
            raise BadRequest("model must be a string")
        image = _decode_image(data["image_b64"]) if data.get("image_b64") else None
        memos = _decode_memos(data)
        if not diary_text.strip() and image is None and not memos:
            raise BadRequest("paste the diary text, add a photo or add a voice memo first")
        return diary_text, week_ending, model, image, memos

    def _run(self, diary_text: str, week_ending: str, model: str, image, memos=()) -> dict:
        pipeline = importlib.import_module("arvo.pipeline")  # lazy: server starts even if the pipeline is mid-build
        roster = load_roster(self.server.roster_path)
        tmp_paths: list[str] = []

        def write_temp(raw: bytes, prefix: str, suffix: str) -> str:
            fd, path = tempfile.mkstemp(prefix=prefix, suffix=suffix)
            tmp_paths.append(path)
            with os.fdopen(fd, "wb") as fh:
                fh.write(raw)
            return path

        try:
            kwargs = {"model": model, "image_path": None}
            if image is not None:
                kwargs["image_path"] = write_temp(image[0], "arvo-photo-", image[1])
            if memos:
                # The date goes in the filename: voice.memo_date() reads it from there (mtime is off).
                kwargs["audio_paths"] = [write_temp(raw, f"arvo-memo-{d or 'nodate'}-", ".audio") for raw, d in memos]
                kwargs["audio_use_mtime"] = False
            result = pipeline.run(diary_text, roster, week_ending, **kwargs)
        finally:
            for path in tmp_paths:
                try:
                    os.unlink(path)
                except OSError:
                    pass
        out = _to_dict(result)
        invoices = render_invoices(result, roster, week_ending)
        if invoices is not None:
            out["invoices_html"] = invoices
        return out


def make_server(host: str = "127.0.0.1", port: int = 8765, model: str | None = None,
                roster_path: str | Path | None = None, quiet: bool = False) -> ArvoServer:
    if host not in LOOPBACK_HOSTS:
        raise ValueError(f"Arvo only listens on this computer (127.0.0.1), not {host!r}")
    return ArvoServer(("127.0.0.1", port), model or default_model(),
                      Path(roster_path) if roster_path else DEFAULT_ROSTER, quiet=quiet)


def main(host: str = "127.0.0.1", port: int = 8765, model: str | None = None,
         roster_path: str | Path | None = None) -> None:
    httpd = make_server(host, port, model=model, roster_path=roster_path)
    url = f"http://127.0.0.1:{httpd.server_address[1]}/"
    print(f"Arvo is running at {url}  (model {httpd.model}; Ctrl+C to stop)", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
