# engine/core_resolvers.py
import re
from typing import Any, Dict, List, Optional

from .db import (
    DB_ACTIONS,
    fetchall_dict,
    load_table,
    table_has_column,
    upsert_by_desc_schema,
)
from .utils import norm_tr, normalize_numeric


def resolve_type_code(profile, type_name: str, supplier_default: str = "asya") -> str:
    rows = fetchall_dict("SELECT code, `desc` FROM i_type")
    target = norm_tr(type_name)

    for r in rows:
        if norm_tr(r["desc"]) == target:
            DB_ACTIONS.append({"action": "EXISTS", "table": "i_type", "desc": type_name, "code": r["code"]})
            return r["code"]

    # not found -> insert
    existing = {r["code"] for r in fetchall_dict("SELECT code FROM i_type")}
    from .utils import first_free_code

    new_code = first_free_code(existing, profile.type_len)

    # schema-aware insert (use db module builder)
    values: Dict[str, Any] = {"code": new_code, "desc": type_name}

    meta = {}  # optional cols
    # (we cannot reliably know extra cols here without schema map, but upsert_by_desc_schema handles generic tables.
    # i_type may have extra columns: supplier, catalog_code, code_spare. We'll mimic old logic if present.)
    from .db import get_table_meta, build_insert_sql, execute

    meta = get_table_meta("i_type")
    if "supplier" in meta:
        values["supplier"] = supplier_default
    if "catalog_code" in meta:
        values["catalog_code"] = ""
    if "code_spare" in meta:
        values["code_spare"] = ""

    sql, params = build_insert_sql("i_type", values, fallback="-")
    DB_ACTIONS.append({"action": "WOULD_INSERT", "table": "i_type", "desc": type_name, "code": new_code})
    execute(sql, params)
    return new_code


def resolve_space_code(profile, space_raw: str) -> str:
    s = norm_tr(space_raw)
    if s in ("", "-", "0"):
        return upsert_by_desc_schema("i_space", "-", profile.space_len)

    if "bitisik" in s or "bitişik" in s:
        rows = fetchall_dict("SELECT code, `desc` FROM i_space")
        for r in rows:
            if "bitisik" in norm_tr(r["desc"]):
                DB_ACTIONS.append({"action": "EXISTS", "table": "i_space", "desc": r["desc"], "code": r["code"]})
                return r["code"]
        return upsert_by_desc_schema("i_space", "BITISIK", profile.space_len)

    m = re.search(r"(\d+)\s*cm", s)
    if m:
        n = m.group(1)
        rows = fetchall_dict("SELECT code, `desc` FROM i_space")
        for r in rows:
            d = norm_tr(r["desc"])
            if (n in d) and ("cm" in d):
                DB_ACTIONS.append({"action": "EXISTS", "table": "i_space", "desc": r["desc"], "code": r["code"]})
                return r["code"]
        return upsert_by_desc_schema("i_space", f"{n} cm bosluk", profile.space_len)

    return upsert_by_desc_schema("i_space", space_raw, profile.space_len)


def resolve_length_code(profile, length_raw: str, i_length_rows: List[Dict[str, Any]]) -> str:
    raw = str(length_raw or "").strip()
    raw_l = norm_tr(raw)

    if raw_l in ("", "-", "0"):
        return upsert_by_desc_schema("i_length", "-", profile.length_len)

    key = normalize_numeric(raw)
    wants_inches = ('"' in raw) or ("inch" in raw_l)

    def field_indicates_inches(s: str) -> bool:
        sl = norm_tr(s or "")
        return ("inch" in sl) or ('"' in (s or ""))

    has_desc2 = any(("desc2" in r) for r in i_length_rows)

    if has_desc2:
        cand_desc2 = []
        for r in i_length_rows:
            d2 = (r.get("desc2") or "").strip()
            if not d2 or d2 == "-":
                continue
            if wants_inches and (not field_indicates_inches(d2)):
                continue
            if normalize_numeric(d2) == key:
                cand_desc2.append(r)
        if cand_desc2:
            r = cand_desc2[0]
            DB_ACTIONS.append(
                {"action": "EXISTS", "table": "i_length", "code": r["code"], "desc": r.get("desc"), "desc2": r.get("desc2"), "match": "desc2"}
            )
            return r["code"]

    cand_desc = []
    for r in i_length_rows:
        d = (r.get("desc") or "").strip()
        if not d or d == "-":
            continue
        if wants_inches and (not field_indicates_inches(d)):
            continue
        if normalize_numeric(d) == key:
            cand_desc.append(r)
    if cand_desc:
        r = cand_desc[0]
        DB_ACTIONS.append(
            {"action": "EXISTS", "table": "i_length", "code": r["code"], "desc": r.get("desc"), "desc2": r.get("desc2"), "match": "desc"}
        )
        return r["code"]

    desc2_value = None
    if wants_inches:
        num = normalize_numeric(raw)
        desc2_value = f"{num} inches"
    return upsert_by_desc_schema("i_length", raw, profile.length_len, desc2_value=desc2_value)


def resolve_color_code(profile, workshop_color_label: str, i_color_rows: List[Dict[str, Any]]) -> str:
    raw = (workshop_color_label or "").strip()
    if not raw:
        raise ValueError("Empty workshop color label")

    target = norm_tr(raw)

    for r in i_color_rows:
        if norm_tr(r.get("desc") or "") == target:
            DB_ACTIONS.append({"action": "EXISTS", "table": "i_color", "desc": raw, "code": r["code"], "match": "desc"})
            return str(r["code"])

    if any("desc2" in r for r in i_color_rows):
        for r in i_color_rows:
            d2 = (r.get("desc2") or "").strip()
            if d2 and d2 != "-" and norm_tr(d2) == target:
                DB_ACTIONS.append({"action": "EXISTS", "table": "i_color", "desc2": raw, "code": r["code"], "match": "desc2"})
                return str(r["code"])

    # not found -> upsert
    return upsert_by_desc_schema("i_color", raw, profile.color_len)