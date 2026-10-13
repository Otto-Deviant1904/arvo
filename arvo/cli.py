"""`python -m arvo process|serve|eval`."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from datetime import date, timedelta
from pathlib import Path

from . import llm

REPO = Path(__file__).resolve().parent.parent
DEFAULT_ROSTER = REPO / "data" / "roster.example.json"
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".heic"}


def _last_sunday(today: date | None = None) -> str:
    today = today or date.today()
    return (today - timedelta(days=(today.weekday() + 1) % 7)).isoformat()


def _table(headers: list[str], rows: list[list], widths: dict[int, int] | None = None) -> str:
    widths = widths or {}
    cells = [[str(c) for c in r] for r in rows]
    for r in cells:
        for i, w in widths.items():
            if len(r[i]) > w:
                r[i] = r[i][: w - 1] + "…"
    cols = [max(len(h), *(len(r[i]) for r in cells)) if cells else len(h) for i, h in enumerate(headers)]
    fmt = lambda r: "  ".join(c.ljust(cols[i]) for i, c in enumerate(r)).rstrip()  # noqa: E731
    return "\n".join([fmt(headers), fmt(["-" * c for c in cols]), *(fmt(r) for r in cells)])


def render(result) -> str:
    """Human-readable report for a RunResult."""
    out = []
    out.append(f"SHIFTS ({len(result.shifts)})")
    out.append(_table(
        ["date", "day", "who", "start", "end", "km", "note"],
        [[s.date, date.fromisoformat(s.date).strftime("%a"), s.participant_id or "?", s.start, s.end,
          f"{s.km:g}" if s.km else "", s.note] for s in result.shifts],
        widths={6: 70}))
    shift_warns = [(s, w) for s in result.shifts for w in s.warnings]
    if shift_warns:
        out.append("")
        out.extend(f"  ! {s.date} {s.participant_id or '?'}: {w}" for s, w in shift_warns)

    out.append("")
    out.append(f"INVOICE LINES ({len(result.lines)})")
    if result.lines:
        out.append(_table(
            ["who", "date", "item", "start", "end", "qty", "unit", "price", "total", "rule"],
            [[ln.participant_id, ln.date, ln.item_number, ln.start, ln.end, f"{ln.quantity:.2f}", ln.unit,
              f"{ln.unit_price:.2f}", f"{ln.total:.2f}", ln.rule] for ln in result.lines],
            widths={9: 50}))
        totals: dict[str, float] = {}
        for ln in result.lines:
            totals[ln.participant_id] = round(totals.get(ln.participant_id, 0) + ln.total + 1e-9, 2)
        out.append("  totals: " + ", ".join(f"{k} ${v:,.2f}" for k, v in totals.items()))
    else:
        out.append("  (none)")

    out.append("")
    red = [f for f in result.flags if not f.authorised_in_bsp]
    auth = [f for f in result.flags if f.authorised_in_bsp]
    out.append(f"RESTRICTIVE PRACTICE FLAGS ({len(red)} red, {len(auth)} authorised in BSP)")
    if not result.flags:
        out.append("  (none)")
    for f in [*red, *auth]:
        tag = "RED" if not f.authorised_in_bsp else "AUTHORISED, record it"
        out.append(f"  [{tag}] {f.date} {f.participant_id or '?'}: {f.rp_type}"
                   + (" + HARM" if f.harm_mentioned else ""))
        out.append(f"      evidence: \"{f.evidence_quote}\"")
        if f.explanation:
            out.append(f"      why: {f.explanation}")
        if f.report_by:
            out.append(f"      report by: {f.report_by}")
        elif not f.authorised_in_bsp:
            out.append("      report by: (5 business days; deadline needs arvo.calendar_au)")
    if red:
        out.append("  Red flags: unregistered providers must not use restrictive practices. "
                   "Talk to your provider or the NDIS Commission.")

    if result.warnings:
        out.append("")
        out.append("WARNINGS")
        out.extend(f"  - {w}" for w in result.warnings)
    t = result.timings
    out.append("")
    out.append(f"model {result.model}: extract {t.get('extract_s', 0):.1f}s, pricing {t.get('pricing_s', 0):.2f}s, "
               f"rp {t.get('rp_s', 0):.1f}s ({t.get('rp_calls', 0)} calls), total {t.get('total_s', 0):.1f}s")
    return "\n".join(out)


def cmd_process(args) -> int:
    from .pipeline import run
    from .voice import AUDIO_EXTS, VoiceError

    paths = [Path(p) for p in (args.diary if isinstance(args.diary, list) else [args.diary])]
    for path in paths:
        if not path.is_file():
            print(f"error: no such file {path}", file=sys.stderr)
            return 2
    audio = [str(p) for p in paths if p.suffix.lower() in AUDIO_EXTS]
    if (audio and len(audio) != len(paths)) or (not audio and len(paths) > 1):
        print("error: give one diary (.txt or photo), or one or more voice memos", file=sys.stderr)
        return 2
    path = paths[0]
    is_image = not audio and path.suffix.lower() in IMAGE_EXTS
    diary_text = "" if (is_image or audio) else path.read_text(encoding="utf-8")
    try:
        result = run(diary_text, args.roster, args.week_ending, model=args.model,
                     image_path=str(path) if is_image else None, audio_paths=audio or None)
    except (llm.LLMError, VoiceError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(render(result))
    if args.json:
        Path(args.json).write_text(json.dumps(result.to_dict(), indent=2), encoding="utf-8")
        print(f"\nwrote {args.json}")
    return 0


def _run_with_argv(fn, prog: str, rest: list[str]):
    old = sys.argv
    sys.argv = [prog, *rest]
    try:
        return fn()
    finally:
        sys.argv = old


def cmd_serve(args) -> int:
    try:
        from arvo.server import main as server_main
    except ImportError as e:
        print(f"error: arvo.server is not available ({e})", file=sys.stderr)
        return 1
    kwargs = {k: v for k, v in (("port", args.port), ("model", args.model), ("roster_path", args.roster))
              if v is not None}
    return server_main(**kwargs) or 0


def cmd_eval(args) -> int:
    script = REPO / "eval" / "run_eval.py"
    if not script.is_file():
        print(f"error: {script} not found", file=sys.stderr)
        return 1
    spec = importlib.util.spec_from_file_location("arvo_run_eval", script)
    mod = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(REPO))
    spec.loader.exec_module(mod)
    if not hasattr(mod, "main"):
        print(f"error: {script} has no main()", file=sys.stderr)
        return 1
    return _run_with_argv(mod.main, str(script), args.rest) or 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="arvo", description="NDIS shift diary -> invoice lines + restrictive-practice flags (local Gemma).")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("process", help="read one diary (text, photo or voice memos) and print shifts, lines, flags")
    p.add_argument("diary", nargs="+", help="diary .txt, or a photo (.png/.jpg) of a handwritten diary, "
                                            "or one or more voice memos (.m4a/.wav/.ogg/...), one per shift")
    p.add_argument("--week-ending", default=_last_sunday(), help="YYYY-MM-DD, last day of the week (default: last Sunday)")
    p.add_argument("--roster", default=str(DEFAULT_ROSTER), help="roster JSON (default: data/roster.example.json)")
    p.add_argument("--model", default=llm.DEFAULT_MODEL, help=f"Ollama model (default {llm.DEFAULT_MODEL})")
    p.add_argument("--json", metavar="OUT", help="also write the full RunResult JSON here")
    p.set_defaults(fn=cmd_process)

    s = sub.add_parser("serve", help="start the local web UI (arvo.server)")
    s.add_argument("--port", type=int, default=None, help="port on 127.0.0.1 (server default 8765)")
    s.add_argument("--model", default=None, help="Ollama model (server default)")
    s.add_argument("--roster", default=None, help="roster JSON (server default)")
    s.set_defaults(fn=cmd_serve)

    e = sub.add_parser("eval", help="run eval/run_eval.py")
    e.add_argument("rest", nargs=argparse.REMAINDER)
    e.set_defaults(fn=cmd_eval)
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.fn(args) or 0)
