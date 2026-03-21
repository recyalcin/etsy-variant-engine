# engine/core.py
import json
import html
import re
from itertools import product
from collections import Counter
from typing import Any, Dict, List, Optional, Set, Tuple

from .etsy_api import get_inventory, put_inventory_overwrite
from .db import DB_ACTIONS, load_table, choose_label_field, upsert_by_desc_schema
from .template import analyze_template
from .normalize import normalize_length_for_property, normalize_qty_for_property, build_qty_label
from .overrides import _as_str_dict, build_property_value
from .pricing import build_pricing_map, calc_price
from .sku import decode_sku
from .utils import (
    safe_print,
    ensure_list,
    parse_workshop_csv_list,
    is_code_like,
    norm_tr,
    normalize_numeric,  # IMPORTANT: for scale/meta matching (e.g. "14 inches" -> "14")
)

from .core_resolvers import (
    resolve_type_code,
    resolve_space_code,
    resolve_color_code,
    resolve_length_code,
)

# local const (same as main file)
NUM_PREFIX = re.compile(r"^\s*(\d+)\s+(.*\S)\s*$")

# ------------------- Etsy scale/meta map -------------------


def build_property_meta_map(inv: Dict[str, Any]) -> Dict[Tuple[int, str], Dict[str, Any]]:
    """
    Map: (property_id, normalized_value_string) -> meta {scale_id, value_ids, ott_value_qualifier? ...}

    IMPORTANT:
    Etsy scale properties often return values like "14" (scale_id=5),
    but our engine may generate "14 inches" or '14"'.
    So we index BOTH:
      - norm_tr(raw_value)
      - norm_tr(normalize_numeric(raw_value))  (e.g. "14 inches" -> "14")
    """
    out: Dict[Tuple[int, str], Dict[str, Any]] = {}
    for p in (inv.get("products") or []):
        for pv in (p.get("property_values") or []):
            pid = pv.get("property_id")
            if pid is None:
                continue
            pid = int(pid)

            vals = pv.get("values") or []
            if not vals:
                continue

            meta: Dict[str, Any] = {}
            if pv.get("scale_id") is not None:
                meta["scale_id"] = pv.get("scale_id")
            if pv.get("value_ids") is not None:
                meta["value_ids"] = pv.get("value_ids")

            # keep only if present (None is ignored)
            for extra in ("ott_value_qualifier",):
                if pv.get(extra) is not None:
                    meta[extra] = pv.get(extra)

            if not meta:
                continue

            for v in vals:
                v0 = str(v)
                k1 = norm_tr(v0)
                if k1:
                    out[(pid, k1)] = meta

                vn = normalize_numeric(v0)
                k2 = norm_tr(vn)
                if k2 and k2 != k1:
                    out[(pid, k2)] = meta

    return out


# ------------------- readiness_state_id -------------------


def infer_readiness_state_id(inv: Dict[str, Any]) -> Optional[int]:
    for p in (inv.get("products") or []):
        for off in (p.get("offerings") or []):
            rs = off.get("readiness_state_id")
            if rs is None:
                continue
            try:
                return int(rs)
            except Exception:
                continue
    return None


# ------------------- reporting helpers -------------------


def summarize_db_plan(actions):
    by_table = {}

    def uniq_exists(lst):
        seen = set()
        out = []
        for r in lst:
            key = (
                r.get("table"),
                r.get("code"),
                r.get("desc"),
                r.get("desc2"),
                r.get("match"),
            )
            if key in seen:
                continue
            seen.add(key)
            out.append(r)
        return out

    for a in actions:
        table = a.get("table")
        if not table:
            continue

        if table not in by_table:
            by_table[table] = {
                "exists": [],
                "missing": [],
                "updates": [],
            }

        act = a.get("action")

        if act == "EXISTS":
            by_table[table]["exists"].append(a)

        elif act == "WOULD_INSERT":
            by_table[table]["missing"].append(a)

        elif act == "WOULD_UPDATE":
            by_table[table]["updates"].append(a)

    # UNIQUE FILTER only for exists
    for table in by_table:
        by_table[table]["exists"] = uniq_exists(by_table[table]["exists"])

    return by_table


# ------------------- color display helpers -------------------


def _find_color_row(workshop_color_label: str, i_color_rows: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    target = norm_tr((workshop_color_label or "").strip())
    if not target:
        return None
    for r in i_color_rows:
        if norm_tr(r.get("desc") or "") == target:
            return r
    for r in i_color_rows:
        d2 = (r.get("desc2") or "").strip()
        if d2 and d2 != "-" and norm_tr(d2) == target:
            return r
    return None


def choose_color_display_label(
    workshop_label: str,
    color_row: Optional[Dict[str, Any]],
    color_prop: Optional[Dict[str, Any]],
) -> str:
    wl = (workshop_label or "").strip()
    if not wl:
        return ""

    if not color_row:
        return wl

    desc = (color_row.get("desc") or "").strip()
    desc2 = (color_row.get("desc2") or "").strip()

    samples = [html.unescape(str(x)).strip() for x in ((color_prop or {}).get("sample_values") or [])][:60]
    sample_set = {norm_tr(x) for x in samples if x}

    if desc2 and desc2 != "-" and norm_tr(desc2) in sample_set:
        return desc2
    if desc:
        return desc
    if desc2 and desc2 != "-":
        return desc2
    return wl


# ------------------- dry-run suggestions -------------------


def suggest_component_overrides(props: List[Dict[str, Any]]) -> Dict[str, List[str]]:
    out: Dict[str, List[str]] = {}
    for p in props:
        pid = p.get("property_id")
        pname = norm_tr(p.get("property_name") or "")
        comps = p.get("components") or []
        delim = p.get("delim") or ""
        samples = [html.unescape(str(x)).strip() for x in (p.get("sample_values") or [])][:25]

        if not pid or len(comps) < 2:
            continue
        if not delim:
            continue

        name_hint = any(k in pname for k in ["number", "numbers", "initial", "birthstone", "harf", "rakam", "numara", "no"])
        ints = 0
        total = 0
        for s in samples:
            if delim not in s:
                continue
            parts = [x.strip() for x in s.split(delim)]
            if len(parts) < 2:
                continue
            total += 1
            if re.fullmatch(r"\d+", parts[-1]):
                ints += 1

        if total >= 2 and ints >= max(2, total // 2):
            if "color" in comps and "length" in comps and (name_hint or ints >= 3):
                out[str(pid)] = ["color", "qty"]

    return out


def suggest_display_overrides_for_colors(
    workshop_labels: List[str],
    i_color_rows: List[Dict[str, Any]],
    color_prop: Optional[Dict[str, Any]],
) -> Dict[str, str]:
    out: Dict[str, str] = {}
    samples = [html.unescape(str(x)).strip() for x in ((color_prop or {}).get("sample_values") or [])][:80]
    sample_set = {norm_tr(x) for x in samples if x}

    for wl in workshop_labels:
        row = _find_color_row(wl, i_color_rows)
        if not row:
            continue
        desc = (row.get("desc") or "").strip()
        desc2 = (row.get("desc2") or "").strip()
        if desc2 and desc2 != "-" and norm_tr(desc2) in sample_set:
            if desc and norm_tr(wl) == norm_tr(desc) and norm_tr(desc2) != norm_tr(desc):
                out[desc] = desc2
    return out


# ------------------- core -------------------


def build_and_push(profile, payload: Dict[str, Any], dry_run: bool) -> None:
    DB_ACTIONS.clear()

    listing_id = int(payload["listing_id"])
    safe_print("[INFO] profile: %s | db: %s" % (profile.name, __import__("os").environ.get("MYSQL_DB")))
    safe_print("[INFO] Etsy inventory GET: %s" % listing_id)

    inv = get_inventory(listing_id)
    safe_print("[STEP] inventory fetched. products: %s" % len(inv.get("products") or []))

    # meta map (scale_id/value_ids/ott_value_qualifier)
    pv_meta_map = build_property_meta_map(inv)

    rs_id = payload.get("readiness_state_id")
    if rs_id is None:
        rs_id = infer_readiness_state_id(inv)
    if rs_id is None:
        raise ValueError("readiness_state_id not found in payload or listing inventory.")
    rs_id = int(rs_id)

    safe_print("[STEP] loading db tables ...")
    i_color_rows = load_table("i_color")
    i_length_rows = load_table("i_length")

    pricing_map = build_pricing_map(payload, profile, i_color_rows, i_length_rows, dry_run)
    i_length_rows = load_table("i_length")  # refresh after potential inserts

    color_field = "desc" if profile.name == "silveristic" else choose_label_field(i_color_rows)
    length_field = choose_label_field(i_length_rows)

    color_set_lower: Set[str] = set(norm_tr(r.get(color_field) or "") for r in i_color_rows)
    length_set_lower: Set[str] = set(norm_tr(r.get(length_field) or "") for r in i_length_rows)

    safe_print("[STEP] analyzing template ...")
    tpl = analyze_template(inv, color_set_lower, length_set_lower)
    props: List[Dict[str, Any]] = tpl["properties"]

    # APPLY COMPONENT/DELIM OVERRIDES (Overrides-first)
    comp_over = payload.get("component_overrides") or {}
    delim_over = payload.get("delim_overrides") or {}
    comp_over = {str(k): v for k, v in comp_over.items()} if isinstance(comp_over, dict) else {}
    delim_over = {str(k): v for k, v in delim_over.items()} if isinstance(delim_over, dict) else {}

    for p in props:
        pid = str(p.get("property_id"))
        if pid in comp_over:
            p["components"] = list(comp_over[pid])
        if pid in delim_over:
            p["delim"] = str(delim_over[pid])

    safe_print(
        "[INFO] Template properties: %s"
        % ([(p["property_id"], p["property_name"], p["components"], p["delim"], p["sample_values"][:3]) for p in props],)
    )

    suggested_component_overrides = suggest_component_overrides(props)

    # DISPLAY OVERRIDES (Overrides-first)
    display_overrides = payload.get("display_value_overrides") or {}
    display_overrides_by_prop = payload.get("display_value_overrides_by_property") or {}

    display_overrides = _as_str_dict(display_overrides)
    for k in list(display_overrides.keys()):
        display_overrides[k] = _as_str_dict(display_overrides[k])

    display_overrides_by_prop = _as_str_dict(display_overrides_by_prop)
    for pid in list(display_overrides_by_prop.keys()):
        per = display_overrides_by_prop[pid]
        per = _as_str_dict(per)
        for role in list(per.keys()):
            per[role] = _as_str_dict(per[role])
        display_overrides_by_prop[pid] = per

    # locate template props for roles
    color_prop = next((p for p in props if "color" in (p.get("components") or [])), None)
    qty_prop = next((p for p in props if "qty" in (p.get("components") or [])), None)
    len_prop = next((p for p in props if "length" in (p.get("components") or [])), None)

    qty_is_count = False
    if qty_prop:
        sv = qty_prop.get("sample_values") or []
        qty_is_count = any(NUM_PREFIX.match((html.unescape(x or "")).strip()) for x in sv)

    type_code = resolve_type_code(profile, payload.get("type", "-"))
    size_code = upsert_by_desc_schema("i_size", payload.get("size", "-"), profile.size_len)
    space_code = resolve_space_code(profile, payload.get("space", "-"))
    start_code = upsert_by_desc_schema("i_start", payload.get("start", "-"), profile.start_len)

    needs_color = any("color" in (p.get("components") or []) for p in props)
    needs_length = any("length" in (p.get("components") or []) for p in props)
    needs_qty = any("qty" in (p.get("components") or []) for p in props)

    # ------------------- COLOR INPUT -------------------
    colors_in = payload.get("colors") or []
    workshop_color_labels: List[str] = []

    if isinstance(colors_in, list):
        workshop_color_labels = [str(x).strip() for x in colors_in if str(x).strip()]
    elif isinstance(colors_in, dict):
        keys = [str(k).strip() for k in colors_in.keys()]
        vals = [str(v).strip() for v in colors_in.values() if v is not None]
        if keys and all(is_code_like(k, profile.color_len) for k in keys) and any(v and not is_code_like(v, profile.color_len) for v in vals):
            workshop_color_labels = [str(v).strip() for v in colors_in.values() if str(v).strip()]
        else:
            workshop_color_labels = keys
    elif isinstance(colors_in, str):
        s = colors_in.strip()
        workshop_color_labels = [s] if s else []
    else:
        workshop_color_labels = []

    # ------------------- WORKSHOP QTY INPUT (empty/single/multi) -------------------
    raw_quantities = [str(x).strip() for x in ensure_list(payload.get("quantities")) if str(x).strip() and str(x).strip() != "-"]

    if raw_quantities:
        if len(raw_quantities) == 1:
            effective_qty = raw_quantities[0]
            quantities_in: List[str] = []
        else:
            effective_qty = "-"
            quantities_in = raw_quantities
    else:
        raw_qty = payload.get("quantity") or payload.get("Quantity")
        if raw_qty is None:
            raw_qty = payload.get("qty") or payload.get("Qty") or payload.get("sku_qty") or payload.get("sku_quantity")

        qty_items = parse_workshop_csv_list(raw_qty) if raw_qty is not None else []

        if not qty_items:
            effective_qty = "-"
            quantities_in = []
        elif len(qty_items) == 1:
            effective_qty = qty_items[0] or "-"
            quantities_in = []
        else:
            effective_qty = "-"
            quantities_in = [q for q in qty_items if q and q != "-"]

    # ------------------- WORKSHOP LENGTH INPUT -------------------
    raw_len_single = payload.get("length") or payload.get("Length")
    len_label_in = (str(raw_len_single).strip() if raw_len_single is not None else "").strip()

    lengths_in_raw = payload.get("lengths", payload.get("lengths_inch", payload.get("Lengths", payload.get("Lengths_inch", []))))
    lengths_list_in = [str(x).strip() for x in ensure_list(lengths_in_raw) if str(x).strip() and str(x).strip() != "-"]

    if len_label_in:
        effective_len = len_label_in
        lengths_in_list = [effective_len]
    elif lengths_list_in:
        lengths_in_list = lengths_list_in
        effective_len = "-"
    else:
        effective_len = "-"
        lengths_in_list = []

    # ------------------- LENGTH MAPS + SKU logic -------------------
    length_code_map: Dict[str, str] = {}
    length_label_map: Dict[str, str] = {}

    if lengths_in_list:
        for rawL in lengths_in_list:
            rawL = str(rawL)
            L_label = normalize_length_for_property(rawL, len_prop or {"sample_values": []})
            length_label_map[rawL] = L_label
            length_code_map[rawL] = resolve_length_code(profile, rawL, i_length_rows)
        forced_len_code_part = ("0" * profile.length_len)
    else:
        forced_len_code_part = resolve_length_code(profile, effective_len, i_length_rows)

    # ✅ SKU length fallback:
    # Template'de length yoksa bile, inputtan tek bir length geldiyse SKU'ya yaz.
    sku_fixed_length_code: Optional[str] = None
    sku_fixed_length_label: Optional[str] = None
    _input_lengths = [str(x).strip() for x in lengths_in_list if str(x).strip() and str(x).strip() != "-"]
    if (not needs_length) and _input_lengths:
        if len(_input_lengths) == 1:
            sku_fixed_length_label = _input_lengths[0]
            sku_fixed_length_code = resolve_length_code(profile, sku_fixed_length_label, i_length_rows)
        else:
            raise ValueError(
                f"Listing template has no length variation, but input provides multiple lengths: {_input_lengths}. "
                "Either add length variation on Etsy or provide a single fixed length."
            )

    # ------------------- QTY MAPS + SKU forcing -------------------
    forced_qty_code_part = upsert_by_desc_schema("i_qty", effective_qty, profile.qty_len)
    forced_qty_n: Optional[int] = None
    m_forced = re.search(r"(\d+)", effective_qty)
    if m_forced:
        forced_qty_n = int(m_forced.group(1))

    if quantities_in:
        forced_qty_code_part = ("0" * profile.qty_len)
        forced_qty_n = None

    qty_code_map: Dict[str, str] = {}
    qty_num_map: Dict[str, Optional[int]] = {}
    if quantities_in:
        for qraw in quantities_in:
            qty_code_map[qraw] = upsert_by_desc_schema("i_qty", qraw, profile.qty_len)
            if isinstance(qty_numbers, dict) and qraw in qty_numbers:
                qty_num_map[qraw] = int(qty_numbers[qraw])
            else:
                m = re.search(r"(\d+)", str(qraw))
                qty_num_map[qraw] = int(m.group(1)) if m else None

    # ------------------- suggested display overrides (dry-run helper) -------------------
    suggested_display_value_overrides: Dict[str, Dict[str, str]] = {}
    if needs_color:
        sug_c = suggest_display_overrides_for_colors(workshop_color_labels, i_color_rows, color_prop)
        if sug_c:
            suggested_display_value_overrides["color"] = sug_c

    # mapping trace
    trace_color: List[Dict[str, Any]] = []
    trace_qty: List[Dict[str, Any]] = []
    trace_length: List[Dict[str, Any]] = []

    colors_iter = workshop_color_labels if needs_color else ["X"]
    lengths_iter = [str(x) for x in lengths_in_list] if (needs_length and lengths_in_list) else [None]
    qty_iter = quantities_in if (needs_qty and quantities_in) else [None]

    products_out: List[Dict[str, Any]] = []

    for workshop_color_label, L_raw, qraw in product(colors_iter, lengths_iter, qty_iter):
        # COLOR
        if needs_color:
            c_code = resolve_color_code(profile, workshop_color_label, i_color_rows)
            row = _find_color_row(workshop_color_label, i_color_rows)
            base_color_display = choose_color_display_label(workshop_color_label, row, color_prop)
            color_label_for_ctx = base_color_display
            trace_color.append({"workshop": workshop_color_label, "base_display": base_color_display, "db_code": c_code})
        else:
            c_code = "X"
            color_label_for_ctx = ""

        # LENGTH
        length_label = ""
        # default: template length yok ama input fixed length geldiyse SKU'ya yaz
        len_code_part = sku_fixed_length_code or (forced_len_code_part if not lengths_in_list else ("0" * profile.length_len))

        if needs_length:
            if L_raw is not None:
                length_label = length_label_map[L_raw]
                len_code_part = length_code_map[L_raw]
                trace_length.append({"input": L_raw, "base_display": length_label, "db_code": len_code_part})
            else:
                length_label = normalize_length_for_property(effective_len, len_prop or {"sample_values": []}) if effective_len else ""
        else:
            if sku_fixed_length_label:
                # sadece debug/ctx için
                length_label = normalize_length_for_property(sku_fixed_length_label, {"sample_values": []})

        # QTY
        qty_label = ""
        qty_code_part = forced_qty_code_part
        qty_n: Optional[int] = forced_qty_n

        if needs_qty and quantities_in and qraw is not None:
            qty_n = qty_num_map.get(qraw)
            qty_code_part = qty_code_map[qraw]

            if qty_is_count and (qty_n is not None):
                qty_label = build_qty_label(qty_n, tpl)
            else:
                qty_label = normalize_qty_for_property(str(qraw), qty_prop)

            trace_qty.append({"input": qraw, "base_display": qty_label, "db_code": qty_code_part, "qty_n": qty_n, "mode": "count" if qty_is_count else "enum"})
        else:
            qty_label = ""

        price = calc_price(payload, pricing_map, c_code, len_code_part, qty_code_part, dry_run)

        ctx = {"color_label": color_label_for_ctx, "length_label": length_label, "qty_label": qty_label}

        pv_list = []
        for prop in props:
            pid = int(prop["property_id"])
            vstr = build_property_value(prop, ctx, display_overrides, display_overrides_by_prop)

            pv_obj: Dict[str, Any] = {
                "property_id": pid,
                "property_name": prop["property_name"],
                "values": [vstr],
            }

            # scale/meta attach (with numeric fallback)
            meta = pv_meta_map.get((pid, norm_tr(vstr)))
            if not meta:
                meta = pv_meta_map.get((pid, norm_tr(normalize_numeric(vstr))))

            if meta:
                # Etsy bazı scale property'lerde ott_value_qualifier=0 kabul etmiyor.
                # Ayrıca None geliyorsa da göndermeyelim.
                meta2 = dict(meta)
                oq = meta2.get("ott_value_qualifier")
                if oq in (None, 0, "0"):
                    meta2.pop("ott_value_qualifier", None)
                pv_obj.update(meta2)

            pv_list.append(pv_obj)

        seg = {
            "type": type_code,
            "length": len_code_part,
            "color": c_code,
            "qty": qty_code_part,
            "size": size_code,
            "start": start_code,
            "space": space_code,
        }
        sku = "".join(seg[k] for k in profile.sku_order)

        products_out.append(
            {
                "sku": sku,
                "property_values": pv_list,
                "offerings": [{"price": price, "quantity": payload.get("stock", 900), "is_enabled": True, "readiness_state_id": rs_id}],
            }
        )

    prop_ids = [p["property_id"] for p in props if p.get("property_id") is not None]

    if dry_run:
        # UNIQUE FILTER for mapping_trace
        def _uniq_list(items, key_fn):
            seen = set()
            out = []
            for it in items:
                k = key_fn(it)
                if k in seen:
                    continue
                seen.add(k)
                out.append(it)
            return out

        trace_color_u = _uniq_list(trace_color, lambda x: (x.get("workshop"), x.get("base_display"), x.get("db_code")))
        trace_qty_u = _uniq_list(trace_qty, lambda x: (x.get("input"), x.get("base_display"), x.get("db_code"), x.get("qty_n"), x.get("mode")))
        trace_length_u = _uniq_list(trace_length, lambda x: (x.get("input"), x.get("base_display"), x.get("db_code")))

        sku_decode_first8 = [decode_sku(profile, p["sku"]) for p in products_out[:8]]
        summary = Counter(a.get("action") for a in DB_ACTIONS)
        plan = summarize_db_plan(DB_ACTIONS)

        out = json.dumps(
            {
                "profile": profile.name,
                "listing_id": listing_id,
                "count": len(products_out),
                "readiness_state_id": rs_id,
                "sample_product": products_out[0] if products_out else None,
                "sku_decode_first8": sku_decode_first8,
                "db_plan_summary": dict(summary),
                "db_plan_by_table": plan,
                "qty_is_count": qty_is_count,
                "suggested_component_overrides": suggested_component_overrides,
                "example_component_overrides": {},
                "applied_component_overrides": comp_over,
                "applied_delim_overrides": delim_over,
                "suggested_display_value_overrides": suggested_display_value_overrides,
                "example_display_value_overrides": {},
                "example_display_value_overrides_by_property": {},
                "applied_display_value_overrides": display_overrides,
                "applied_display_value_overrides_by_property": display_overrides_by_prop,
                "mapping_trace": {"color": trace_color_u[:50], "qty": trace_qty_u[:50], "length": trace_length_u[:50]},
                "sku_fixed_length_applied": bool(sku_fixed_length_code),
                "sku_fixed_length_label": sku_fixed_length_label,
                "sku_fixed_length_code": sku_fixed_length_code,
            },
            ensure_ascii=False,
            indent=2,
        )

        safe_print(out)
        return

    put_payload = {
        "products": products_out,
        "price_on_property": prop_ids,
        "quantity_on_property": [],
        "sku_on_property": prop_ids,
    }

    safe_print("[DEBUG] payload.quantities = %s" % json.dumps(payload.get("quantities"), ensure_ascii=False))
    safe_print("[DEBUG] payload.quantity = %s" % json.dumps(payload.get("quantity"), ensure_ascii=False))
    safe_print("[DEBUG] applied_component_overrides = %s" % json.dumps(comp_over, ensure_ascii=False))
    safe_print("[DEBUG] applied_display_value_overrides_by_property = %s" % json.dumps(display_overrides_by_prop, ensure_ascii=False))
    safe_print("[DEBUG] effective_qty = %s | quantities_in = %s" % (repr(effective_qty), repr(quantities_in)))

    safe_print("[INFO] PUT overwrite products: %s" % len(products_out))
    safe_print("[INFO] readiness_state_id: %s" % rs_id)
    safe_print("[INFO] price_on_property: %s" % prop_ids)
    safe_print("[INFO] sku_on_property: %s" % prop_ids)

    safe_print("----- PUT_PAYLOAD_JSON_BEGIN -----")
    safe_print(json.dumps(put_payload, ensure_ascii=False))
    safe_print("----- PUT_PAYLOAD_JSON_END -----")

    resp = put_inventory_overwrite(listing_id, put_payload)
    safe_print("OK listing_id: %s products: %s" % (resp.get("listing_id"), len(products_out)))