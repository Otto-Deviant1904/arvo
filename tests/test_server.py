"""Server + page tests. No network, no Ollama: arvo.pipeline and arvo.invoice are faked."""

from __future__ import annotations

import base64
import http.client
import json
import re
import sys
import threading
import types
from dataclasses import fields
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from arvo import server as srv  # noqa: E402
from arvo.models import InvoiceLine, RPFlag, RunResult, Shift  # noqa: E402

PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)


def fake_result(model: str) -> RunResult:
    note = "Bunnings. I locked the pantry so he'd stop snacking. Fine after."
    return RunResult(
        shifts=[Shift("jake", "2026-10-06", "15:00", "20:30", 12, note, "Tues - Jake 3 till 8:30ish",
                      ["approximate end time '8:30ish'"])],
        lines=[InvoiceLine("jake", "2026-10-06", "04_103_0125_6_1", "Community - Weekday Evening",
                           "15:00", "20:30", 5.5, "H", 10.0, 55.0, "Weekday evening: ends after 20:00")],
        flags=[RPFlag("jake", "2026-10-06", "environmental", "I locked the pantry so he'd stop snacking.",
                      False, False, "2026-10-13", "Locking food away is an environmental restraint.")],
        warnings=["Fri: no times"],
        model=model,
        timings={"extract_s": 1.0, "rp_s": 0.5, "total_s": 1.5},
    )


class FakePipeline:
    def __init__(self):
        self.calls: list[dict] = []
        self.gate: threading.Event | None = None
        self.started = threading.Event()

    def run(self, diary_text, roster_path_or_dict, week_ending, model="gemma4:e4b", image_path=None,
            audio_paths=None, audio_use_mtime=True):
        call = {"diary_text": diary_text, "roster": roster_path_or_dict, "week_ending": week_ending,
                "model": model, "image_path": image_path, "image_bytes": None,
                "audio_paths": audio_paths, "audio_use_mtime": audio_use_mtime, "audio_bytes": None}
        if image_path:
            call["image_bytes"] = Path(image_path).read_bytes()  # must exist while run() is active
        if audio_paths:
            call["audio_bytes"] = [Path(a).read_bytes() for a in audio_paths]
        self.calls.append(call)
        if diary_text == "bad audio":
            from arvo.voice import VoiceError
            raise VoiceError("ffmpeg could not read memo.audio: Invalid data found")
        self.started.set()
        if self.gate is not None:
            self.gate.wait(5)
        if diary_text == "boom":
            raise RuntimeError("ollama is not running")
        return fake_result(model)


@pytest.fixture
def fake_pipeline(monkeypatch):
    fake = FakePipeline()
    mod = types.ModuleType("arvo.pipeline")
    mod.run = fake.run
    monkeypatch.setitem(sys.modules, "arvo.pipeline", mod)
    return fake


@pytest.fixture
def fake_invoice(monkeypatch):
    seen = []

    def render_invoice_html(participant, worker, lines, invoice_no, invoice_date):
        seen.append((participant, worker, lines, invoice_no, invoice_date))
        return f"<html><head></head><body>{participant.name} {invoice_no}</body></html>"

    mod = types.ModuleType("arvo.invoice")
    mod.render_invoice_html = render_invoice_html
    monkeypatch.setitem(sys.modules, "arvo.invoice", mod)
    return seen


@pytest.fixture
def live(monkeypatch):
    monkeypatch.setattr(srv, "ollama_status", lambda model, timeout=1.0: (True, True))
    httpd = srv.make_server("127.0.0.1", 0, model="gemma4:e4b", quiet=True)
    t = threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    t.start()
    yield httpd
    httpd.shutdown()
    httpd.server_close()


def request(httpd, method, path, body=None, headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", httpd.server_address[1], timeout=10)
    hdrs = {"Content-Type": "application/json"} if body is not None else {}
    hdrs.update(headers or {})
    data = json.dumps(body).encode() if isinstance(body, dict) else body
    conn.request(method, path, body=data, headers=hdrs)
    resp = conn.getresponse()
    raw = resp.read()
    conn.close()
    return resp, raw


def get_json(httpd, path):
    resp, raw = request(httpd, "GET", path)
    return resp.status, json.loads(raw)


def post_run(httpd, payload):
    resp, raw = request(httpd, "POST", "/api/run", payload)
    return resp.status, json.loads(raw)


# ------------------------------------------------------------------ API

def test_health(live):
    status, data = get_json(live, "/api/health")
    assert status == 200
    assert data == {"ok": True, "model": "gemma4:e4b", "ollama_up": True, "model_available": True}


def test_index_served_with_csp(live):
    resp, raw = request(live, "GET", "/")
    assert resp.status == 200
    assert resp.getheader("Content-Type").startswith("text/html")
    assert "connect-src 'self'" in resp.getheader("Content-Security-Policy")
    assert b"Nothing you type here leaves this computer." in raw


def test_roster(live):
    status, data = get_json(live, "/api/roster")
    assert status == 200
    assert {p["id"] for p in data["participants"]} >= {"jake", "priya"}


def test_run_round_trip_with_invoices(live, fake_pipeline, fake_invoice):
    status, data = post_run(live, {"diary_text": "Tues - Jake 3 till 8:30ish", "week_ending": "2026-10-11"})
    assert status == 200, data
    for key in ("shifts", "lines", "flags", "warnings", "model", "timings"):
        assert key in data
    assert data["flags"][0]["evidence_quote"] == "I locked the pantry so he'd stop snacking."
    assert data["lines"][0]["total"] == 55.0
    assert set(data["invoices_html"]) == {"jake"}
    assert "Jake Morrison ARVO-20261011-JAKE" in data["invoices_html"]["jake"]

    call = fake_pipeline.calls[0]
    assert call["diary_text"] == "Tues - Jake 3 till 8:30ish"
    assert call["week_ending"] == "2026-10-11"
    assert call["model"] == "gemma4:e4b"
    assert call["image_path"] is None
    assert call["roster"]["worker"]["name"]  # roster dict passed through

    participant, worker, lines, invoice_no, _ = fake_invoice[0]
    assert participant.id == "jake" and isinstance(lines[0], InvoiceLine)
    assert worker["abn"] and invoice_no == "ARVO-20261011-JAKE"


def test_run_without_invoice_module(live, fake_pipeline, monkeypatch):
    monkeypatch.setitem(sys.modules, "arvo.invoice", None)  # import raises ImportError
    status, data = post_run(live, {"diary_text": "x", "week_ending": "2026-10-11", "model": "gemma4:e2b"})
    assert status == 200
    assert "invoices_html" not in data
    assert data["model"] == "gemma4:e2b"


def test_run_with_image_uses_temp_file(live, fake_pipeline, fake_invoice):
    b64 = "data:image/png;base64," + base64.b64encode(PNG_1PX).decode()
    status, data = post_run(live, {"diary_text": "", "week_ending": "2026-10-11", "image_b64": b64})
    assert status == 200, data
    call = fake_pipeline.calls[0]
    assert call["image_bytes"] == PNG_1PX
    assert call["image_path"].endswith(".png")
    assert not Path(call["image_path"]).exists()  # cleaned up after the run


def test_run_rejects_non_image(live, fake_pipeline):
    status, data = post_run(live, {"diary_text": "", "week_ending": "2026-10-11",
                                   "image_b64": base64.b64encode(b"not an image").decode()})
    assert status == 400 and data["ok"] is False
    assert fake_pipeline.calls == []


@pytest.mark.parametrize("payload, needle", [
    ({"diary_text": "x"}, "week_ending"),
    ({"diary_text": "x", "week_ending": "11/10/2026"}, "week_ending"),
    ({"diary_text": "   ", "week_ending": "2026-10-11"}, "diary"),
])
def test_run_validation(live, fake_pipeline, payload, needle):
    status, data = post_run(live, payload)
    assert status == 400
    assert needle in data["error"]
    assert fake_pipeline.calls == []


def test_bad_json_and_content_type(live, fake_pipeline):
    resp, raw = request(live, "POST", "/api/run", b"{not json", {"Content-Type": "application/json"})
    assert resp.status == 400 and json.loads(raw)["ok"] is False
    resp, raw = request(live, "POST", "/api/run", b'{"diary_text":"x","week_ending":"2026-10-11"}',
                        {"Content-Type": "text/plain"})
    assert resp.status == 415  # forces a CORS preflight, which this server never grants


# ------------------------------------------------------------------ voice memos

def b64(raw: bytes, prefix: str = "") -> str:
    return prefix + base64.b64encode(raw).decode()


def test_run_with_voice_memos(live, fake_pipeline):
    memos = [b"memo-one", b"memo-two", b"memo-three"]
    status, data = post_run(live, {
        "diary_text": "", "week_ending": "2026-10-11",
        "audio_b64_list": [b64(memos[0], "data:audio/webm;codecs=opus;base64,"), b64(memos[1]), b64(memos[2])],
        "audio_dates": ["2026-10-06", None],  # shorter than the list: the third memo has no date
    })
    assert status == 200, data
    call = fake_pipeline.calls[0]
    assert call["diary_text"] == ""  # an empty diary is fine when memos are present
    assert call["audio_use_mtime"] is False
    assert call["audio_bytes"] == memos  # upload order kept, data: prefix stripped
    names = [Path(a).name for a in call["audio_paths"]]
    assert names[0].startswith("arvo-memo-2026-10-06-") and names[0].endswith(".audio")
    assert names[1].startswith("arvo-memo-nodate-") and names[2].startswith("arvo-memo-nodate-")
    assert not any(Path(a).exists() for a in call["audio_paths"])  # cleaned up after the run


def test_run_without_memos_does_not_pass_audio(live, fake_pipeline):
    status, _ = post_run(live, {"diary_text": "x", "week_ending": "2026-10-11"})
    assert status == 200
    assert fake_pipeline.calls[0]["audio_paths"] is None


@pytest.mark.parametrize("extra, needle", [
    ({"audio_b64_list": "abc"}, "audio_b64_list"),
    ({"audio_b64_list": [b64(b"a")], "audio_dates": ["06/10/2026"]}, "audio_dates[0]"),
    ({"audio_b64_list": [b64(b"a")], "audio_dates": "2026-10-06"}, "audio_dates"),
    ({"audio_b64_list": [b64(b"a")], "audio_dates": ["2026-10-06", "2026-10-07"]}, "more audio_dates"),
    ({"audio_b64_list": [""]}, "empty"),
    ({"audio_b64_list": [123]}, "base64"),
])
def test_voice_memo_validation(live, fake_pipeline, extra, needle):
    status, data = post_run(live, {"diary_text": "", "week_ending": "2026-10-11", **extra})
    assert status == 400, data
    assert needle in data["error"]
    assert fake_pipeline.calls == []


def test_voice_error_is_400(live, fake_pipeline):
    status, data = post_run(live, {"diary_text": "bad audio", "week_ending": "2026-10-11",
                                   "audio_b64_list": [b64(b"x")], "audio_dates": ["2026-10-06"]})
    assert status == 400
    assert data == {"ok": False, "error": "ffmpeg could not read memo.audio: Invalid data found"}
    assert not Path(fake_pipeline.calls[0]["audio_paths"][0]).exists()


def test_page_csp_allows_blob_audio(live):
    resp, _ = request(live, "GET", "/")
    assert "media-src blob:" in resp.getheader("Content-Security-Policy")


def test_pipeline_error_is_json(live, fake_pipeline):
    status, data = post_run(live, {"diary_text": "boom", "week_ending": "2026-10-11"})
    assert status == 500
    assert data == {"ok": False, "error": "RuntimeError: ollama is not running"}


def test_body_size_limit(live, fake_pipeline):
    conn = http.client.HTTPConnection("127.0.0.1", live.server_address[1], timeout=10)
    conn.putrequest("POST", "/api/run")
    conn.putheader("Content-Type", "application/json")
    conn.putheader("Content-Length", str(srv.MAX_BODY_BYTES + 1))
    conn.endheaders()  # body never sent: the server must refuse on the header alone
    resp = conn.getresponse()
    data = json.loads(resp.read())
    conn.close()
    assert resp.status == 413
    assert srv.MAX_BODY_BYTES == 25 * 1024 * 1024
    assert "25 MB" in data["error"]
    assert fake_pipeline.calls == []


def test_one_run_at_a_time(live, fake_pipeline):
    fake_pipeline.gate = threading.Event()
    first: dict = {}

    def slow_run():
        first["status"], first["data"] = post_run(live, {"diary_text": "a", "week_ending": "2026-10-11"})

    t = threading.Thread(target=slow_run)
    t.start()
    assert fake_pipeline.started.wait(5)
    status, data = post_run(live, {"diary_text": "b", "week_ending": "2026-10-11"})
    fake_pipeline.gate.set()
    t.join(5)
    assert status == 409 and "in progress" in data["error"]
    assert first["status"] == 200


def test_dns_rebinding_host_rejected(live):
    resp, raw = request(live, "GET", "/api/roster", headers={"Host": "evil.example:8765"})
    assert resp.status == 403
    assert b"Mel" not in raw


def test_refuses_non_loopback_bind():
    with pytest.raises(ValueError):
        srv.make_server("0.0.0.0", 0)


def test_unknown_path_404(live):
    status, data = get_json(live, "/etc/passwd")
    assert status == 404 and data["ok"] is False


# ------------------------------------------------------------------ page

HTML = (ROOT / "web" / "index.html").read_text(encoding="utf-8")


def test_page_never_writes_markup_from_strings():
    script = "\n".join(re.findall(r"<script>(.*?)</script>", HTML, flags=re.S))
    assert script
    for pattern in (r"\.innerHTML\s*\+?=", r"\.outerHTML\s*=(?!=)", r"insertAdjacentHTML",
                    r"document\.write", r"\beval\(", r"new Function\("):
        assert not re.search(pattern, script), pattern


def test_page_has_required_copy():
    for text in ("Running on your laptop: ", "Demo mode: showing a saved run", "Record a memo", "MediaRecorder",
                 "What Gemma heard", "audio_b64_list", "audio_dates",
                 "Arvo flags, it does not decide. Registered providers must notify the NDIS Commission",
                 "Nothing you type here leaves this computer.", "python -m arvo serve", "demo/run.json"):
        assert text in HTML, text
    # no third-party scripts; the only external URL is the hosted-demo font stylesheet
    assert not re.search(r"<script[^>]+src=", HTML)
    assert set(re.findall(r"https://[a-z0-9.-]+", HTML)) <= {"https://fonts.googleapis.com"}


def test_docs_copy_is_identical():
    assert (ROOT / "docs" / "index.html").read_text(encoding="utf-8") == HTML


def test_demo_run_matches_runresult_shape():
    data = json.loads((ROOT / "docs" / "demo" / "run.json").read_text(encoding="utf-8"))
    for f in fields(RunResult):
        assert f.name in data, f.name
    for key, cls in (("shifts", Shift), ("lines", InvoiceLine), ("flags", RPFlag)):
        assert data[key], key
        for item in data[key]:
            assert set(item) == {f.name for f in fields(cls)}, key
    notes = {(s["participant_id"], s["date"]): s["note"] for s in data["shifts"]}
    for flag in data["flags"]:
        assert flag["evidence_quote"] in notes[(flag["participant_id"], flag["date"])]
