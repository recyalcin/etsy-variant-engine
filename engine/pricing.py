# engine/pricing.py
from typing import Any, Dict

from .db import upsert_by_desc_schema
from .core_resolvers import resolve_color_code, resolve_length_code  # bunu aşağıda anlatacağım


def build_pricing_map(payload: Dict[str, Any], profile, i_color_rows, i_length_rows, dry_run: bool) -> Dict[str, float]:
    pricing_by = payload.get("pricing_by")
    if not pricing_by:
        if dry_run:
            return {}
        raise ValueError("pricing_by is required")

    # 1) Explicit pricing_map always wins
    if isinstance(payload.get("pricing_map"), dict):
        return {str(k): float(v) for k, v in payload["pricing_map"].items()}

    # 2) Backward/Frontend compatibility:
    # UI sometimes sends "prices" instead of "pricing_labels"
    pricing_labels = payload.get("pricing_labels")
    if not isinstance(pricing_labels, dict):
        prices = payload.get("prices")
        if isinstance(prices, dict):
            pricing_labels = prices  # alias

    if not isinstance(pricing_labels, dict):
        if pricing_by == "fixed":
            return {}
        if dry_run:
            return {}
        raise ValueError("pricing_labels or pricing_map required")

    pricing_map: Dict[str, float] = {}
    for label, price in pricing_labels.items():
        if pricing_by == "color":
            code = resolve_color_code(profile, label, i_color_rows)
        elif pricing_by == "length":
            code = resolve_length_code(profile, label, i_length_rows)
        elif pricing_by == "qty":
            code = upsert_by_desc_schema("i_qty", label, profile.qty_len)
        elif pricing_by == "fixed":
            continue
        else:
            if dry_run:
                continue
            raise ValueError(f"Unknown pricing_by: {pricing_by}")

        pricing_map[str(code)] = float(price)

    return pricing_map


def calc_price(payload: Dict[str, Any], pricing_map: Dict[str, float], color_code: str, length_code: str, qty_code: str, dry_run: bool) -> float:
    pricing_by = payload.get("pricing_by")

    if pricing_by == "fixed":
        if "fixed_price" in payload:
            return float(payload["fixed_price"])
        if dry_run:
            return 0.0
        raise ValueError("fixed_price missing")

    if pricing_by == "color":
        key = color_code
    elif pricing_by == "length":
        key = length_code
    elif pricing_by == "qty":
        key = qty_code
    else:
        if dry_run:
            return 0.0
        raise ValueError(f"Unknown pricing_by: {pricing_by}")

    if key in pricing_map:
        return float(pricing_map[key])

    if dry_run:
        return 0.0

    raise ValueError(f"Missing price for {pricing_by} code: {key}")