# engine/db.py
import os
import pymysql
from typing import Any, Dict, List, Optional, Set, Tuple

from .utils import require_env, first_free_code, norm_tr

# !!! IMPORTANT FIX:
# Do NOT import WRITE_ENABLED as a value (it won't update when config.WRITE_ENABLED changes).
# Always read it dynamically from the config module.
from . import config  # <-- instead of: from .config import WRITE_ENABLED

DB_ACTIONS: List[Dict[str, Any]] = []
TABLE_META_CACHE: Dict[str, Dict[str, Dict[str, Any]]] = {}

# ------------------------------
# DRY-RUN / SAME-RUN STATE CACHE
# ------------------------------
# When WRITE_ENABLED=False, DB doesn't change, so repeated upserts would keep picking the same "first free code".
# We keep an in-memory reservation + desc->code map for the current run to make dry-run deterministic and correct.
PENDING_CODES: Dict[str, Set[str]] = {}                 # table -> reserved codes in this run
PENDING_DESC_TO_CODE: Dict[str, Dict[str, str]] = {}    # table -> norm_desc -> code


def mysql_conn():
    return pymysql.connect(
        host=require_env("MYSQL_HOST"),
        port=int(os.environ.get("MYSQL_PORT", "3306")),
        user=require_env("MYSQL_USER"),
        password=require_env("MYSQL_PASS"),
        database=require_env("MYSQL_DB"),
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=True,
    )


def fetchall_dict(sql: str, params: Tuple[Any, ...] = ()) -> List[Dict[str, Any]]:
    conn = mysql_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return list(cur.fetchall())
    finally:
        conn.close()


def execute(sql: str, params: Tuple[Any, ...] = ()) -> None:
    # Read dynamically
    if not bool(getattr(config, "WRITE_ENABLED", False)):
        DB_ACTIONS.append({"action": "DB_WRITE_SKIPPED", "sql": sql, "params": params})
        return

    conn = mysql_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
    finally:
        conn.close()


def get_table_meta(table: str) -> Dict[str, Dict[str, Any]]:
    if table in TABLE_META_CACHE:
        return TABLE_META_CACHE[table]

    db = require_env("MYSQL_DB")
    rows = fetchall_dict(
        """
        SELECT COLUMN_NAME, IS_NULLABLE, COLUMN_DEFAULT
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s
        """,
        (db, table),
    )

    meta: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        meta[str(r["COLUMN_NAME"])] = {
            "is_nullable": (str(r["IS_NULLABLE"]).upper() == "YES"),
            "default": r["COLUMN_DEFAULT"],
        }

    TABLE_META_CACHE[table] = meta
    return meta


def table_has_column(table: str, col: str) -> bool:
    return col in get_table_meta(table)


def build_insert_sql(table: str, values: Dict[str, Any], fallback: str = "-") -> Tuple[str, Tuple[Any, ...]]:
    meta = get_table_meta(table)

    cols: List[str] = []
    params: List[Any] = []

    for k, v in values.items():
        if k not in meta:
            continue
        cols.append(k if k != "desc" else "`desc`")
        params.append(v)

    # fill NOT NULL columns that have no default and are not provided
    for col, info in meta.items():
        if col in values:
            continue
        if col.lower() in ("id",):
            continue
        if info["is_nullable"]:
            continue
        if info["default"] is not None:
            continue
        cols.append(col if col != "desc" else "`desc`")
        params.append(fallback)

    if not cols:
        raise RuntimeError("No insertable columns detected for table: %s" % table)

    placeholders = ", ".join(["%s"] * len(cols))
    sql = "INSERT INTO %s (%s) VALUES (%s)" % (table, ", ".join(cols), placeholders)
    return sql, tuple(params)


def load_table(table: str) -> List[Dict[str, Any]]:
    meta = get_table_meta(table)
    if "desc2" in meta:
        return fetchall_dict("SELECT code, `desc`, desc2 FROM %s" % table)
    return fetchall_dict("SELECT code, `desc` FROM %s" % table)


def choose_label_field(rows: List[Dict[str, Any]]) -> str:
    has_desc2 = any(("desc2" in r) for r in rows)
    if not has_desc2:
        return "desc"
    for r in rows:
        d2 = (r.get("desc2") or "").strip()
        if d2 and d2 != "-":
            return "desc2"
    return "desc"


def upsert_by_desc_schema(table: str, desc_value: str, code_len: int, desc2_value: Optional[str] = None) -> str:
    rows = load_table(table)
    target = norm_tr(desc_value)
    has_desc2 = table_has_column(table, "desc2")

    # ---- SAME-RUN CACHE: if we already planned/inserted this desc in this run, reuse code ----
    pend_map = PENDING_DESC_TO_CODE.setdefault(table, {})
    if target in pend_map:
        return pend_map[target]

    for r in rows:
        if norm_tr(r["desc"]) == target:
            DB_ACTIONS.append(
                {"action": "EXISTS", "table": table, "desc": desc_value, "code": r["code"], "desc2": r.get("desc2")}
            )

            # cache the found code too (prevents extra queries + stabilizes the run)
            pend_map[target] = str(r["code"])

            if has_desc2 and desc2_value:
                old = (r.get("desc2") or "").strip()
                if (not old) or old == "-":
                    DB_ACTIONS.append({"action": "WOULD_UPDATE", "table": table, "code": r["code"], "set_desc2": desc2_value})
                    execute("UPDATE %s SET desc2=%%s WHERE code=%%s" % table, (desc2_value, r["code"]))

            return str(r["code"])

    # Not found -> generate new code
    existing = {str(r["code"]) for r in fetchall_dict("SELECT code FROM %s" % table)}
    reserved = PENDING_CODES.setdefault(table, set())

    new_code = first_free_code(existing | reserved, code_len)

    values: Dict[str, Any] = {"code": new_code, "desc": desc_value}
    if has_desc2 and (desc2_value is not None):
        values["desc2"] = desc2_value

    sql, params = build_insert_sql(table, values, fallback="-")
    DB_ACTIONS.append(
        {"action": "WOULD_INSERT", "table": table, "desc": desc_value, "code": new_code, "desc2": values.get("desc2")}
    )

    # reserve in-memory BEFORE execute (critical for dry-run)
    reserved.add(new_code)
    pend_map[target] = new_code

    execute(sql, params)
    return new_code