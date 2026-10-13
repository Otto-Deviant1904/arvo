"""Invoice HTML + CSV."""

import csv
import io

import pytest

from arvo.invoice import FOOTER, lines_to_csv, render_invoice_html
from arvo.models import InvoiceLine, Participant, Shift
from arvo.pricing import price_shifts


def _jake_lines(roster):
    lines, _ = price_shifts([Shift("jake", "2026-11-03", "10:00", "14:00", 12, ""),
                             Shift("jake", "2026-10-14", "15:00", "20:30", 0, "")], roster)
    return lines


def test_invoice_has_required_fields(roster):
    jake = next(p for p in roster["participants"] if p["id"] == "jake")
    html = render_invoice_html(jake, roster["worker"], _jake_lines(roster), "ARVO-20261108-JAKE", "2026-11-08")
    for needle in ["Mel Tran", "12 345 678 901", "Jake Morrison", "430000001", "Bayside Plan Partners (example)",
                   "ARVO-20261108-JAKE", "Sun 08 Nov 2026", "04_102_0125_6_1", "04_103_0125_6_1", "04_590_0125_6_1",
                   "10:00&ndash;14:00", "$163.46", "$653.84", "$11.88", "$445.89",
                   "BSB 000-000  Acc 00000000", FOOTER, "Goods and Services Tax (GST)", "@media print"]:
        assert needle in html, needle
    # grand total 653.84 + 11.88 + 445.89 = 1111.61
    assert "$1,111.61" in html
    # lines are sorted by date
    assert html.index("04_103_0125_6_1") < html.index("04_102_0125_6_1")


def test_invoice_escapes_text(roster):
    evil = {"id": "jake", "name": "Jake <b>M</b>", "ndis_number": "430000001",
            "plan_manager": "PM & Co", "note": "<script>alert('x')</script>"}
    line = InvoiceLine("jake", "2026-10-14", "04_104_0125_6_1", "Item <i>", "09:00", "13:00",
                       4.0, "H", 73.58, 294.32, rule="<script>bad()</script>")
    html = render_invoice_html(evil, roster["worker"], [line], "INV<1>", "2026-10-15")
    assert "<script" not in html.lower()
    assert "&lt;script&gt;alert(&#x27;x&#x27;)&lt;/script&gt;" in html
    assert "Jake &lt;b&gt;M&lt;/b&gt;" in html and "PM &amp; Co" in html and "INV&lt;1&gt;" in html


def test_invoice_accepts_participant_dataclass(roster):
    p = Participant(**next(p for p in roster["participants"] if p["id"] == "jake"))
    html = render_invoice_html(p, roster["worker"], _jake_lines(roster), "X1", "2026-11-08")
    assert "Jake Morrison" in html


def test_invoice_rejects_other_participants_lines(roster):
    jake = next(p for p in roster["participants"] if p["id"] == "jake")
    stray = InvoiceLine("priya", "2026-10-14", "01_011_0107_1_1", "x", "09:00", "10:00", 1.0, "H", 73.58, 73.58)
    with pytest.raises(ValueError, match="one participant"):
        render_invoice_html(jake, roster["worker"], [stray], "X", "2026-11-08")


def test_lines_to_csv(roster):
    out = lines_to_csv(_jake_lines(roster))
    rows = list(csv.DictReader(io.StringIO(out)))
    assert [r["item_number"] for r in rows] == ["04_102_0125_6_1", "04_590_0125_6_1", "04_103_0125_6_1"]
    assert rows[0]["quantity"] == "4.00" and rows[0]["unit_price"] == "163.46" and rows[0]["total"] == "653.84"
    assert rows[1]["unit"] == "km" and rows[1]["total"] == "11.88"
    assert list(rows[0]) == ["participant_id", "date", "item_number", "item_name", "start", "end",
                             "quantity", "unit", "unit_price", "total", "rule"]
