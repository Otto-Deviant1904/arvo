"""Regenerate docs/demo/run.json from docs/demo/diary.txt with a real local Gemma run.

    uv run python scripts/make_demo.py [--model gemma4:e4b]
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from arvo import pipeline, server  # noqa: E402

DEMO = ROOT / "docs" / "demo"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="gemma4:e4b")
    ap.add_argument("--week-ending", default="2026-11-08")
    args = ap.parse_args()
    roster = json.loads((ROOT / "data" / "roster.example.json").read_text())
    diary = (DEMO / "diary.txt").read_text()
    result = pipeline.run(diary, roster, args.week_ending, model=args.model)
    out = server._to_dict(result)
    invoices = server.render_invoices(result, roster, args.week_ending)
    if invoices:
        out["invoices_html"] = invoices
    out["week_ending"] = args.week_ending
    out["saved_note"] = "A real run of gemma4:e4b on a laptop (RTX 4050), saved so this page works without the app."
    (DEMO / "run.json").write_text(json.dumps(out, indent=1))
    (DEMO / "roster.json").write_text(json.dumps(roster, indent=1))
    print(f"wrote {DEMO / 'run.json'}: {len(out['shifts'])} shifts, {len(out['lines'])} lines, {len(out['flags'])} flags")


if __name__ == "__main__":
    main()
