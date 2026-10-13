"""Invoice lines -> printable self-contained HTML invoice (one participant per invoice) and CSV."""

from __future__ import annotations

import csv
import io
from dataclasses import asdict, fields
from datetime import date
from decimal import Decimal
from html import escape

from . import prices
from .models import InvoiceLine

FOOTER = "Prepared with Arvo. Prices: NDIS Pricing Schedule 2026-27 (National, Victoria)"
CSV_FIELDS = [f.name for f in fields(InvoiceLine)]

_CSS = """
:root { --ink:#1d2329; --muted:#5d6873; --line:#d9dee3; --head:#f3f5f7; }
* { box-sizing:border-box; }
body { margin:0; background:#fff; color:var(--ink); font:14px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,Arial,sans-serif; }
.page { max-width:900px; margin:24px auto; padding:32px 36px; }
header { display:flex; justify-content:space-between; gap:24px; flex-wrap:wrap; border-bottom:2px solid var(--ink); padding-bottom:16px; }
h1 { margin:0 0 4px; font-size:26px; letter-spacing:.02em; }
.muted { color:var(--muted); }
.meta { text-align:right; }
.meta div, .party div { margin:2px 0; }
.parties { display:grid; grid-template-columns:1fr 1fr; gap:24px; margin:20px 0; }
.party h2 { font-size:12px; text-transform:uppercase; letter-spacing:.08em; color:var(--muted); margin:0 0 6px; }
.table-wrap { overflow-x:auto; }
table { width:100%; border-collapse:collapse; margin-top:8px; }
th, td { border-bottom:1px solid var(--line); padding:7px 6px; vertical-align:top; text-align:left; }
th { background:var(--head); font-size:12px; text-transform:uppercase; letter-spacing:.04em; }
td.num, th.num { text-align:right; white-space:nowrap; }
td.code { font-family:ui-monospace,Menlo,Consolas,monospace; font-size:12.5px; white-space:nowrap; }
.rule { color:var(--muted); font-size:12px; margin-top:2px; }
tfoot td { border-bottom:none; font-weight:700; font-size:16px; padding-top:12px; }
.notes { margin-top:24px; display:grid; gap:10px; }
.notes p { margin:0; }
footer { margin-top:28px; padding-top:10px; border-top:1px solid var(--line); color:var(--muted); font-size:12px; }
@media (max-width:640px) { .page { padding:16px; margin:0; } .parties { grid-template-columns:1fr; } .meta { text-align:left; }
  table { font-size:12.5px; } }
@media print {
  @page { size:A4; margin:14mm; }
  body { font-size:11.5px; }
  .page { margin:0; padding:0; max-width:none; }
  tr { break-inside:avoid; }
  th { -webkit-print-color-adjust:exact; print-color-adjust:exact; }
}
"""


def _get(obj, key: str, default=""):
    if obj is None:
        return default
    if isinstance(obj, dict):
        v = obj.get(key, default)
    else:
        v = getattr(obj, key, default)
    return default if v is None else v


def _as_line(line) -> InvoiceLine:
    if isinstance(line, InvoiceLine):
        return line
    return InvoiceLine(**{k: v for k, v in dict(line).items() if k in CSV_FIELDS})


def _money(x) -> str:
    return f"${Decimal(str(x)):,.2f}"


def _qty(x) -> str:
    return f"{Decimal(str(x)):.2f}"


def _day(iso: str) -> str:
    try:
        return date.fromisoformat(iso).strftime("%a %d %b %Y")
    except ValueError:
        return iso


def gst_statement() -> tuple[str, str]:
    """(verbatim GST sentence, where it comes from) from the price JSON."""
    gst = prices.data()["other_rules"]["gst"]
    src = gst.get("source", {})
    return gst["verbatim"], f"{prices.short_doc(src.get('doc', ''))}, {src.get('where', '')}".strip(", ")


def render_invoice_html(participant, worker: dict, lines: list, invoice_no: str, invoice_date: str) -> str:
    """One participant's invoice. `participant` may be a dict or models.Participant; lines InvoiceLine or dict."""
    e = lambda v: escape(str(v), quote=True)  # noqa: E731
    pid = _get(participant, "id")
    lines = [_as_line(ln) for ln in lines]
    others = sorted({ln.participant_id for ln in lines if pid and ln.participant_id and ln.participant_id != pid})
    if others:
        raise ValueError(f"an invoice is for one participant only: lines for {others} given for {pid!r}")
    lines.sort(key=lambda ln: (ln.date, ln.start or "99:99", ln.unit != "H"))

    total = sum((Decimal(str(ln.total)) for ln in lines), Decimal("0"))
    dates = sorted(ln.date for ln in lines)
    period = f"{_day(dates[0])} to {_day(dates[-1])}" if dates else "no supports"
    business = _get(worker, "business_name") or _get(worker, "name")
    title = "Tax invoice" if _get(worker, "gst_registered", False) is True else "Invoice"
    gst_text, gst_src = gst_statement()

    rows = []
    for ln in lines:
        times = f"{e(ln.start)}&ndash;{e(ln.end)}" if ln.start and ln.end else "&mdash;"
        claim = "Direct service" if ln.unit == "H" else "Activity based transport"
        rule = f'<div class="rule">{e(ln.rule)}</div>' if ln.rule else ""
        rows.append(
            f"<tr><td>{e(_day(ln.date))}</td><td class=\"code\">{e(ln.item_number)}</td>"
            f"<td>{e(ln.item_name)}{rule}</td><td>{e(claim)}</td><td class=\"num\">{times}</td>"
            f"<td class=\"num\">{e(_qty(ln.quantity))}</td><td>{e(ln.unit)}</td>"
            f"<td class=\"num\">{e(_money(ln.unit_price))}</td><td class=\"num\">{e(_money(ln.total))}</td></tr>")

    def row(label: str, value) -> str:
        return f"<div><span class=\"muted\">{e(label)}:</span> {e(value)}</div>" if value not in ("", None, []) else ""

    worker_html = "".join([
        f"<div><strong>{e(business)}</strong></div>",
        row("Worker", _get(worker, "name") if business != _get(worker, "name") else ""),
        row("ABN", _get(worker, "abn") or "NOT PROVIDED: add an ABN or attach the ATO Statement by a supplier"),
        row("Email", _get(worker, "email")), row("Phone", _get(worker, "phone")),
    ])
    participant_html = "".join([
        f"<div><strong>{e(_get(participant, 'name'))}</strong></div>",
        row("NDIS number", _get(participant, "ndis_number")),
        row("Address", _get(participant, "address")),
        row("Plan manager", _get(participant, "plan_manager")),
        row("Note", _get(participant, "note") or _get(participant, "notes")),
    ])

    return f"""<!doctype html>
<html lang="en-AU">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(title)} {e(invoice_no)} - {e(_get(participant, 'name'))}</title>
<style>{_CSS}</style>
</head>
<body>
<div class="page">
<header>
  <div><h1>{e(title)}</h1><div class="muted">NDIS supports for {e(_get(participant, 'name'))}</div></div>
  <div class="meta">
    <div><span class="muted">Invoice number:</span> <strong>{e(invoice_no)}</strong></div>
    <div><span class="muted">Invoice date:</span> {e(_day(invoice_date))}</div>
    <div><span class="muted">Support period:</span> {e(period)}</div>
  </div>
</header>
<section class="parties">
  <div class="party"><h2>From (provider)</h2>{worker_html}</div>
  <div class="party"><h2>For (participant)</h2>{participant_html}</div>
</section>
<div class="table-wrap"><table>
  <thead><tr><th>Date</th><th>Support item</th><th>Item name</th><th>Claim type</th><th class="num">Start&ndash;end</th>
  <th class="num">Qty</th><th>Unit</th><th class="num">Unit price</th><th class="num">Total</th></tr></thead>
  <tbody>
{chr(10).join(rows) if rows else '<tr><td colspan="9" class="muted">No supports on this invoice.</td></tr>'}
  </tbody>
  <tfoot><tr><td colspan="8" class="num">Total (AUD)</td><td class="num">{e(_money(total))}</td></tr></tfoot>
</table></div>
<section class="notes">
  <p><strong>GST:</strong> GST component $0.00. Most NDIS supports are GST-free. &ldquo;{e(gst_text)}&rdquo; ({e(gst_src)})</p>
  <p><strong>Payment:</strong> {e(_get(worker, 'bank') or 'bank details not provided')}. Please quote {e(invoice_no)}.</p>
</section>
<footer>{e(FOOTER)}</footer>
</div>
</body>
</html>
"""


def lines_to_csv(lines) -> str:
    """CSV with one row per line, columns as in models.InvoiceLine; money and quantities to 2 decimals."""
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=CSV_FIELDS, lineterminator="\n")
    w.writeheader()
    for ln in lines:
        d = asdict(_as_line(ln))
        for k in ("quantity", "unit_price", "total"):
            d[k] = f"{Decimal(str(d[k])):.2f}"
        w.writerow(d)
    return buf.getvalue()
