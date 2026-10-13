"""NDIS price limits from data/ndis_prices_2026_27.json. Every dollar figure comes from the JSON.

price_for(item, date)        -> (unit_price, source_note), period chosen by the support date
item_for(support_type, band) -> (item_number, item_name, warning_or_None)
activity_transport_item()     -> TravelItem (Activity Based Transport: km driven with the participant)
travel_km_item(support_type) -> TravelItem (provider travel non-labour item; not used for invoice lines)
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from functools import cache
from pathlib import Path

DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "ndis_prices_2026_27.json"

BANDS = ("weekday_daytime", "weekday_evening", "weekday_night", "saturday", "sunday", "public_holiday")
FAMILY = {"self_care": "assistance_with_self_care_standard",
          "community": "access_community_social_rec_standard"}
COMMUNITY_NIGHT_WARNING = ("no weekday-night item exists for community access; priced at weekday evening, "
                           "check with the plan manager")


class PriceError(ValueError):
    """Date outside the price data, unknown item, or unknown support type / band."""


@cache
def data() -> dict:
    return json.loads(DATA_PATH.read_text(encoding="utf-8"))


def _docs() -> dict[str, dict]:
    return {d["id"]: d for d in data()["meta"]["documents"]}


def short_doc(doc_id: str) -> str:
    """'PAPL_2025_26_V1_1' -> 'NDIS PAPL 2025-26 v1.1'; 'SCHED_2026_27_EFF_2026_09_24' -> 'NDIS Pricing Schedule 2026-27
    (effective 2026-09-24)'; anything else -> the document title or id."""
    p = doc_id.split("_")
    if p[0] == "PAPL" and len(p) == 5:
        return f"NDIS PAPL {p[1]}-{p[2]} {p[3].lower()}.{p[4]}"
    if p[0] == "SCHED" and len(p) == 7 and p[3] == "EFF":
        return f"NDIS Pricing Schedule {p[1]}-{p[2]} (effective {p[4]}-{p[5]}-{p[6]})"
    return _docs().get(doc_id, {}).get("title", doc_id)


def _all_items() -> dict[str, dict]:
    out = {}
    for fam in data()["items"].values():
        for it in fam if isinstance(fam, list) else []:
            out[it["item_number"]] = it
    return out


def earliest_date() -> str:
    return min(p["effective_from"] for p in data()["price_periods"])


def period_for(iso_date: str) -> dict:
    """The price_periods entry covering iso_date (raises PriceError outside them)."""
    d = date.fromisoformat(iso_date)
    for p in data()["price_periods"]:
        lo = date.fromisoformat(p["effective_from"])
        hi = date.fromisoformat(p["effective_to"]) if p.get("effective_to") else date.max
        if lo <= d <= hi:
            return p
    raise PriceError(f"no NDIS price data for {iso_date}: Arvo has prices from {earliest_date()} onwards only")


def is_previous_year(iso_date: str) -> bool:
    return period_for(iso_date)["governing_doc"].startswith("PAPL_2025_26")


def price_for(item_number: str, iso_date: str) -> tuple[float, str]:
    """(national unit price limit in AUD, source note) for a support delivered on iso_date."""
    period = period_for(iso_date)
    doc_id = period["governing_doc"]
    doc_title = short_doc(doc_id)
    if is_previous_year(iso_date):
        prev = data()["previous_year_prices_2025_26"]
        if item_number not in prev["national_aud"]:
            raise PriceError(f"item {item_number} has no 2025-26 price in {DATA_PATH.name}")
        price = prev["national_aud"][item_number]
        where = next((s.get("where") for s in prev.get("sources", []) if s.get("doc") == doc_id and s.get("where")), "")
        unit = _all_items().get(item_number, {}).get("unit", "unit")
        return float(price), f"{doc_title}{', ' + where if where else ''}: national ${price:.2f}/{unit}"
    item = _all_items().get(item_number)
    if item is None:
        raise PriceError(f"item {item_number} not found in {DATA_PATH.name}")
    price = item["price_limit_national_aud"]
    where = next((s.get("where") for s in item.get("sources", []) if s.get("doc") == doc_id), "")
    return float(price), f"{doc_title}{', ' + where if where else ''}: national ${price:.2f}/{item['unit']}"


def item_for(support_type: str, band: str) -> tuple[str, str, str | None]:
    """(item_number, item_name, warning). warning is set when the band has no item and a fallback is used
    (community access has no weekday-night item: the weekday-evening item is returned)."""
    if support_type not in FAMILY:
        raise PriceError(f"unknown support_type {support_type!r}; expected one of {sorted(FAMILY)}")
    if band not in BANDS:
        raise PriceError(f"unknown time band {band!r}; expected one of {list(BANDS)}")
    items = {it["time_band"]: it for it in data()["items"][FAMILY[support_type]]}
    warning = None
    if band not in items:
        missing = data()["items"].get(f"{FAMILY[support_type]}_{band}", {})
        if support_type == "community" and band == "weekday_night" and missing.get("item_number") is None:
            band, warning = "weekday_evening", COMMUNITY_NIGHT_WARNING
        else:
            raise PriceError(f"no {band} item for {support_type} in {DATA_PATH.name}")
    it = items[band]
    return it["item_number"], it["item_name"], warning


def band_of_item(item_number: str) -> str | None:
    it = _all_items().get(item_number)
    return it["time_band"] if it else None


@dataclass(frozen=True)
class TravelItem:
    item_number: str
    item_name: str
    per_km_limit: float
    rule: str               # how the km cost is claimed, from the JSON


def travel_km_item(support_type: str) -> TravelItem:
    """Provider travel non-labour item paired with the support type's item family, and the per-km limit."""
    if support_type not in FAMILY:
        raise PriceError(f"unknown support_type {support_type!r}; expected one of {sorted(FAMILY)}")
    core = data()["items"][FAMILY[support_type]][0]["item_number"].split("_")
    nl = data()["travel"]["provider_travel_non_labour"]
    for it in nl["items"]:
        seg = it["item_number"].split("_")
        if seg[0] == core[0] and seg[2] == core[2]:  # same support category + registration group
            per_km = float(nl["per_km_limit_aud"])
            src = next((s for s in nl["sources"] if s["doc"].startswith("PAPL")), {})
            src_title = short_doc(src.get("doc", ""))
            rule = (f"Provider travel non-labour cost: up to ${per_km:.2f}/km in the provider's or worker's own vehicle "
                    f"({src_title}, {src.get('where', '')}; carried forward: no 2026-27 document restates a per-km "
                    f"figure). Claimed on {it['item_number']} as a dollar amount (unit {it['unit']}, "
                    f"${it['price_limit_national_aud']:.2f} per unit), only where provider travel time can be claimed.")
            return TravelItem(it["item_number"], it["item_name"], per_km, rule)
    raise PriceError(f"no provider-travel non-labour item pairs with {support_type} in {DATA_PATH.name}")


def activity_transport_item() -> TravelItem:
    """Activity Based Transport (km driven WITH the participant), used for every support type's km line."""
    abt = data()["travel"]["activity_based_transport"]
    per_km = float(abt["per_km_unmodified_vehicle_aud"])
    rule = (f"Activity Based Transport: km driven with the participant, up to ${per_km:.2f}/km in an unmodified "
            f"vehicle (PAPL 2025-26 p28; 2026-27 catalogue). Claimed as a dollar amount against a "
            f"${abt['price_limit_national_aud']:.0f} notional unit.")
    return TravelItem(abt["item_number"], abt["item_name"], per_km, rule)
