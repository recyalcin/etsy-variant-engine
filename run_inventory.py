# run_inventory.py  (Python 3.9.x)
# pip install pymysql requests python-dotenv
#
# Supports:
# - color -> DB code in SKU
# - scale-property PUT meta copy (scale_id/value_ids/ott_value_qualifier if present)
# - component_overrides by property_id
# - display_value_overrides_by_property by property_id OR semantic role (qty/color/length)
# - inline overrides in input values: "RAW::ETSY" or "RAW=>ETSY"
# - force SKU qty segment even if Etsy template doesn't expose qty as a property
# - payload logging for Postman

import os
import sys
import re
import json
import time
import html
import argparse
import requests
import pymysql

from itertools import product
from collections import defaultdict, Counter
from dotenv import load_dotenv
from typing import List, Dict, Optional, Any, Set, Tuple

load_dotenv()

# --- Windows console UTF-8 fix ---
try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ETSY_API = "https://api.etsy.com"
ALNUM = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
DELIMS = [" / ", " - ", " | ", "/", "-"]
NUM_PREFIX = re.compile(r"^\s*(\d+)\s+(.*\S)\s*$")

DEBUG = False
WRITE_ENABLED = False
DB_ACTIONS: List[Dict[str, Any]] = []


# ------------------- PROFILE CONFIG -------------------


class Profile:
    def __init__(
        self,
        name: str,
        type_len: int,
        length_len: int,
        color_len: int,
        qty_len: int,
        size_len: int,
        start_len: int,
        space_len: int,
        sku_order: List[str],
    ):
        self.name = name
        self.type_len = type_len
        self.length_len = length_len
        self.color_len = color_len
        self.qty_len = qty_len
        self.size_len = size_len
        self.start_len = start_len
        self.space_len = space_len
        self.sku_order = sku_order

    def sku_lengths(self) -> Dict[str, int]:
        return {
            "type": self.type_len,
            "length": self.length_len,
            "color": self.color_len,
            "qty": self.qty_len,
            "size": self.size_len,
            "start": self.start_len,
            "space": self.space_len,
        }


PROFILES: Dict[str, Profile] = {
    "shiny": Profile(
        name="shiny",
        type_len=2,
        length_len=2,
        color_len=1,
        qty_len=2,
        size_len=1,
        start_len=2,
        space_len=1,
        sku_order=["type", "color", "qty", "length", "start", "space", "size"],
    ),
    "silveristic": Profile(
        name="silveristic",
        type_len=4,
        length_len=4,
        color_len=1,
        qty_len=3,
        size_len=4,
        start_len=3,
        space_len=2,
        sku_order=["type", "length", "color", "qty", "size", "start", "space"],
    ),
    "belkymood": Profile(
        name="belkymood",
        type_len=2,
        length_len=2,
        color_len=1,
        qty_len=2,
        size_len=1,
        start_len=2,
        space_len=1,
        sku_order=["type", "color", "qty", "length", "start", "space", "size"],
    ),
}


# ------------------- utils -------------------


def dprint(*args):
    if DEBUG:
        print(*args, flush=True)


def safe_print(s: str):
    try:
        print(s, flush=True)
    except UnicodeEncodeError:
        print(s.encode("utf-8", "replace").decode("utf-8"), flush=True)


def require_env(name: str) -> str:
    v = os.environ.get(name)
    if not v:
        raise RuntimeError("Missing env var: %s" % name)
    return v


def norm_tr(s: str) -> str:
    s = (s or "").strip().lower()
    tr_map = str.maketrans({"ı": "i", "İ": "i", "ş": "s", "ğ": "g", "ü": "u", "ö": "o", "ç": "c"})
    s = s.translate(tr_map)
    s = re.sub(r"\s+", " ", s)
    return s


def split_override_label(raw: str) -> Tuple[str, Optional[str]]:
    """
    Supports:
      "Workshop :: Etsy"
      "Workshop => Etsy"
    """
    s = (raw or "").strip()
    if not s:
        return "", None

    for sep in ("::", "=>"):
        if sep in s:
            a, b = s.split(sep, 1)
            a = a.strip()
            b = b.strip()
            if a and b:
                return a, b
            return s, None
    return s, None


def first_free_code(existing: Set[str], length: int) -> str:
    if length <= 0:
        raise RuntimeError("Invalid code length")

    if length == 1:
        for a in ALNUM:
            if a not in existing:
                return a
    elif length == 2:
        for a in ALNUM:
            for b in ALNUM:
                c = a + b
                if c not in existing:
                    return c
    elif length == 3:
        for a in ALNUM:
            for b in ALNUM:
                for c1 in ALNUM:
                    c = a + b + c1
                    if c not in existing:
                        return c
    elif length == 4:
        for a in ALNUM:
            for b in ALNUM:
                for c1 in ALNUM:
                    for d in ALNUM:
                        c = a + b + c1 + d
                        if c not in existing:
                            return c
    raise RuntimeError("No free code available")


def normalize_numeric(s: str) -> str:
    x = norm_tr(html.unescape(s or ""))
    x = x.replace("″", '"').replace("”", '"').replace("“", '"')
    x = x.replace('"', "")
    x = x.replace("inches", "").replace("inch", "")
    x = x.replace("cm", "")
    x = x.replace("us", "")
    x = x.strip()
    return x


def _is_plain_number(x: str) -> bool:
    return bool(re.fullmatch(r"\d+(\.\d+)?", (x or "").strip()))


def is_code_like(s: str, expected_len: int) -> bool:
    s = (s or "").strip()
    return (len(s) == expected_len) and all(ch in ALNUM for ch in s)


def strip_option_word(s: str) -> str:
    if not s:
        return s
    s = re.sub(r"\boption\b", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def parse_simple_config_string_map(obj: Any) -> Dict[str, str]:
    out: Dict[str, str] = {}
    if not isinstance(obj, dict):
        return out
    for k, v in obj.items():
        kk = str(k).strip()
        vv = str(v).strip() if v is not None else ""
        if kk:
            out[kk] = vv
    return out


def dump_payload_for_log(payload: Dict[str, Any], max_chars: int = 200000) -> str:
    s = json.dumps(payload, ensure_ascii=False, indent=2)
    if len(s) > max_chars:
        return s[:max_chars] + "\n... [TRUNCATED]"
    return s


# ------------------- Etsy Token Manager -------------------

ETSY_TOKEN_CACHE = {"access_token": None, "expires_at": 0.0}


def refresh_access_token() -> str:
    api_key = require_env("ETSY_API_KEY")
    refresh_tok = require_env("ETSY_REFRESH_TOKEN")

    client_id = api_key.split(":", 1)[0] if ":" in api_key else api_key

    url = "https://api.etsy.com/v3/public/oauth/token"
    data = {
        "grant_type": "refresh_token",
        "client_id": client_id,
        "refresh_token": refresh_tok,
    }

    dprint("[AUTH] Refreshing Etsy access token ...")
    r = requests.post(url, data=data, timeout=30)
    if r.status_code != 200:
        raise RuntimeError("Token refresh failed: %s" % r.text)

    token_data = r.json()
    access_token = token_data["access_token"]
    expires_in = int(token_data.get("expires_in", 3600))

    ETSY_TOKEN_CACHE["access_token"] = access_token
    ETSY_TOKEN_CACHE["expires_at"] = time.time() + expires_in - 60
    return access_token


def get_access_token() -> str:
    now = time.time()
    if (ETSY_TOKEN_CACHE["access_token"] is None) or (now >= ETSY_TOKEN_CACHE["expires_at"]):
        return refresh_access_token()
    return ETSY_TOKEN_CACHE["access_token"]


def etsy_headers():
    key = require_env("ETSY_API_KEY")
    secret = os.environ.get("ETSY_API_SECRET", "")
    x_api_key = f"{key}:{secret}" if (secret and ":" not in key) else key

    return {
        "Authorization": f"Bearer {get_access_token()}",
        "x-api-key": x_api_key,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def etsy_request(method: str, url: str, **kwargs) -> requests.Response:
    timeout = kwargs.pop("timeout", 60)
    r = requests.request(method, url, headers=etsy_headers(), timeout=timeout, **kwargs)
    if r.status_code == 401:
        refresh_access_token()
        r = requests.request(method, url, headers=etsy_headers(), timeout=timeout, **kwargs)
    return r


def get_inventory(listing_id: int) -> Dict[str, Any]:
    url = "%s/v3/application/listings/%s/inventory" % (ETSY_API, listing_id)
    r = etsy_request("GET", url, timeout=45)
    r.raise_for_status()
    return r.json()


def put_inventory_overwrite(listing_id: int, payload: Dict[str, Any]) -> Dict[str, Any]:
    url = "%s/v3/application/listings/%s/inventory" % (ETSY_API, listing_id)
    r = etsy_request("PUT", url, json=payload, timeout=140)
    if not r.ok:
        safe_print("[ETSY][PUT][ERROR] status: %s" % r.status_code)
        safe_print("[ETSY][PUT][ERROR] body: %s" % r.text[:4000])
        r.raise_for_status()
    return r.json()


# ------------------- MySQL (pymysql) -------------------


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
    if not WRITE_ENABLED:
        DB_ACTIONS.append({"action": "DB_WRITE_SKIPPED", "sql": sql, "params": params})
        return
    conn = mysql_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
    finally:
        conn.close()


# ------------------- Schema-driven table meta -------------------

TABLE_META_CACHE: Dict[str, Dict[str, Dict[str, Any]]] = {}


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


# ------------------- Template analysis helpers -------------------


def find_best_delim(samples: List[str]) -> Optional[str]:
    counts = Counter()
    for s in samples:
        for d in DELIMS:
            if d in s:
                counts[d] += 1
    if not counts:
        return None
    d, c = counts.most_common(1)[0]
    return d if c >= 2 else None


def looks_like_length_token(t: str) -> bool:
    tl = norm_tr(html.unescape(t))
    tl = tl.replace("″", '"').replace("”", '"').replace("“", '"')
    if "inch" in tl and re.search(r"\d+(\.\d+)?", tl):
        return True
    if '"' in tl and re.search(r"\d+(\.\d+)?", tl):
        return True
    if re.fullmatch(r"\d+(\.\d+)?", tl):
        return True
    if re.fullmatch(r"\d+(\.\d+)?\s*us", tl):
        return True
    return False


def classify_token(tok: str, color_set_lower: Set[str], length_set_lower: Set[str]) -> str:
    t = html.unescape((tok or "").strip())
    tl = t.lower()
    tl = tl.replace("″", '"').replace("”", '"').replace("“", '"')
    tl_clean = strip_option_word(tl)

    for c in color_set_lower:
        if c and c in tl_clean:
            return "color"

    if tl_clean in length_set_lower:
        return "length"
    if looks_like_length_token(tl_clean):
        return "length"

    m = NUM_PREFIX.match(strip_option_word(t))
    if m:
        num_str = m.group(1)
        tail = strip_option_word(m.group(2) or "").strip().lower()
        if "." in num_str:
            return "unknown"
        n = int(num_str)
        if n <= 50 and tail not in ("us", "uk", "eu", "cm", "mm"):
            return "qty"

    return "unknown"


def normalize_components(comps: List[str]) -> List[str]:
    comps = [c for c in comps if c]

    out = []
    for c in comps:
        if not out or out[-1] != c:
            out.append(c)
    comps = out

    s = set(comps)

    if s.issubset({"qty", "length"}) and "qty" in s and "length" in s:
        out = []
        seen = set()
        for c in comps:
            if c in ("qty", "length") and c not in seen:
                out.append(c)
                seen.add(c)
            if len(out) == 2:
                break
        return out

    if s.issubset({"color", "length"}) and "color" in s and "length" in s:
        out = []
        seen = set()
        for c in comps:
            if c in ("color", "length") and c not in seen:
                out.append(c)
                seen.add(c)
            if len(out) == 2:
                break
        return out

    return comps


def infer_qty_units(samples: List[str]) -> Tuple[Optional[str], Optional[str]]:
    sing = None
    pl = None
    for s in samples:
        s = strip_option_word(html.unescape(s or ""))
        m = NUM_PREFIX.match(s)
        if not m:
            continue
        n = int(m.group(1))
        tail = m.group(2).strip()
        if n == 1 and sing is None:
            sing = tail
        elif n >= 2 and pl is None:
            pl = tail
    return sing, pl


def apply_component_override(
    pid: int,
    inferred: List[str],
    payload: Dict[str, Any],
) -> List[str]:
    comp_ovr = payload.get("component_overrides") or {}
    if not isinstance(comp_ovr, dict):
        return inferred

    key = str(pid)
    if key not in comp_ovr:
        return inferred

    arr = comp_ovr.get(key)
    if not isinstance(arr, list) or not arr:
        return inferred

    out = [str(x).strip().lower() for x in arr if str(x).strip()]
    return out or inferred


def analyze_template(inv: Dict[str, Any], color_set_lower: Set[str], length_set_lower: Set[str], payload: Dict[str, Any]) -> Dict[str, Any]:
    products = inv.get("products") or []
    prop_name: Dict[int, str] = {}
    prop_samples: Dict[int, Set[str]] = defaultdict(set)

    for p in products:
        for pv in (p.get("property_values") or []):
            pid = pv.get("property_id")
            pname = pv.get("property_name")
            if pid is None:
                continue
            pid = int(pid)
            prop_name[pid] = pname
            for v in (pv.get("values") or []):
                prop_samples[pid].add(str(v))

    order: List[int] = []
    if products and products[0].get("property_values"):
        for pv in products[0]["property_values"]:
            pid = pv.get("property_id")
            if pid is None:
                continue
            pid = int(pid)
            if pid in prop_name and pid not in order:
                order.append(pid)
    pos = {pid: i + 1 for i, pid in enumerate(order)}

    props: List[Dict[str, Any]] = []
    qty_samples_all: List[str] = []

    for pid, pname in prop_name.items():
        samples = sorted(prop_samples.get(pid, set()))
        samples_dec = [html.unescape(s) for s in samples]
        pname_l = norm_tr(pname or "")

        if ("color" in pname_l) and ("length" in pname_l):
            delim = find_best_delim(samples_dec) or " / "
            comps = ["color", "length"]
        else:
            delim = find_best_delim(samples_dec)
            if delim and samples_dec:
                rep = next((s for s in samples_dec if delim in s), samples_dec[0])
                parts = [x.strip() for x in rep.split(delim) if x.strip()]
                comps = [classify_token(part, color_set_lower, length_set_lower) for part in parts]
            else:
                comps = [classify_token(samples_dec[0], color_set_lower, length_set_lower)] if samples_dec else ["unknown"]

        comps = normalize_components(comps)
        comps = apply_component_override(pid, comps, payload)

        for s in samples_dec:
            if NUM_PREFIX.match(strip_option_word(s).strip()):
                qty_samples_all.append(strip_option_word(s))

        props.append(
            {
                "property_id": pid,
                "property_name": pname,
                "position": pos.get(pid),
                "delim": delim,
                "components": comps,
                "sample_values": samples_dec[:60],
            }
        )

    sing, pl = infer_qty_units(qty_samples_all)
    return {
        "properties": sorted(props, key=lambda x: (x["position"] is None, x["position"] or 999)),
        "qty_unit_singular": sing,
        "qty_unit_plural": pl,
    }


def build_qty_label(n: int, tpl: Dict[str, Any]) -> str:
    sing = tpl.get("qty_unit_singular") or "Option"
    pl = tpl.get("qty_unit_plural") or (sing + "s")
    return "%d %s" % (n, (sing if n == 1 else pl))


def normalize_length_for_property(raw_input: str, prop: Dict[str, Any]) -> str:
    s = html.unescape((raw_input or "").strip())
    s = s.replace("″", '"').replace("”", '"').replace("“", '"')
    samples = [norm_tr(x) for x in (prop.get("sample_values") or [])]

    if any((" us" in x) for x in samples):
        num = s.replace('"', "").strip()
        if num.lower().endswith("us"):
            num = num[:-2].strip()
        return "%s US" % num

    if any(("inch" in x) for x in samples):
        num = s.replace('"', "").replace("inches", "").replace("inch", "").strip()
        return "%s inches" % num

    if any('"' in x for x in samples):
        num = s.replace('"', "").strip()
        return '%s"' % num

    if samples:
        sample_nums = [normalize_numeric(x) for x in (prop.get("sample_values") or [])]
        sample_nums = [x for x in sample_nums if x]
        if sample_nums and all(_is_plain_number(x) for x in sample_nums):
            num = normalize_numeric(s)
            if _is_plain_number(num):
                return num

    return s


def resolve_display_override(
    payload: Dict[str, Any],
    *,
    role: str,
    property_id: Optional[int],
    raw_value: str,
) -> Optional[str]:
    root = payload.get("display_value_overrides_by_property") or {}
    if not isinstance(root, dict):
        return None

    raw = str(raw_value).strip()
    pid_key = str(property_id) if property_id is not None else None

    if pid_key and isinstance(root.get(pid_key), dict):
        per_prop = root.get(pid_key)

        # preferred shape: {"514": {"qty": {"on taraf":"Front Side Only"}}}
        if isinstance(per_prop.get(role), dict):
            mp = parse_simple_config_string_map(per_prop.get(role))
            if raw in mp and mp[raw]:
                return mp[raw]
            raw_norm = raw.strip().lower()
            for k, v in mp.items():
                if str(k).strip().lower() == raw_norm and v:
                    return str(v).strip()

        # backward-compatible shape: {"514": {"on taraf":"Front Side Only"}}
        mp_flat = parse_simple_config_string_map(per_prop)
        if raw in mp_flat and mp_flat[raw]:
            return mp_flat[raw]
        raw_norm = raw.strip().lower()
        for k, v in mp_flat.items():
            if str(k).strip().lower() == raw_norm and v:
                return str(v).strip()

    if role and isinstance(root.get(role), dict):
        mp = parse_simple_config_string_map(root.get(role))
        if raw in mp and mp[raw]:
            return mp[raw]
        raw_norm = raw.strip().lower()
        for k, v in mp.items():
            if str(k).strip().lower() == raw_norm and v:
                return str(v).strip()

    return None


def build_property_value(
    prop: Dict[str, Any],
    ctx: Dict[str, str],
    display_overrides: Dict[str, Dict[str, str]],
    display_overrides_by_prop: Dict[str, Dict[str, Dict[str, str]]],
) -> str:
    pid = str(prop.get("property_id")) if prop.get("property_id") is not None else None
    comps = prop.get("components") or []
    d = prop.get("delim")

    def apply_override(role: str, base_value: str) -> str:
        s = (base_value or "").strip()
        if not s:
            return ""

        if pid and isinstance(display_overrides_by_prop, dict):
            per_prop = display_overrides_by_prop.get(pid)
            if isinstance(per_prop, dict):
                per_role = per_prop.get(role)
                if isinstance(per_role, dict):
                    if s in per_role:
                        return str(per_role[s]).strip()
                    s_norm = s.strip().lower()
                    for k, v in per_role.items():
                        if str(k).strip().lower() == s_norm:
                            return str(v).strip()

        if isinstance(display_overrides, dict):
            per_role = display_overrides.get(role)
            if isinstance(per_role, dict):
                if s in per_role:
                    return str(per_role[s]).strip()
                s_norm = s.strip().lower()
                for k, v in per_role.items():
                    if str(k).strip().lower() == s_norm:
                        return str(v).strip()

        return s

    def val(role: str) -> str:
        if role == "color":
            return apply_override("color", strip_option_word(ctx.get("color_label", "")))
        if role == "length":
            return apply_override("length", strip_option_word(ctx.get("length_label", "")))
        if role == "qty":
            return apply_override("qty", strip_option_word(ctx.get("qty_label", "")))
        if role == "unknown" and ctx.get("length_label"):
            return apply_override("length", strip_option_word(ctx.get("length_label", "")))
        return strip_option_word(ctx.get("color_label") or ctx.get("length_label") or ctx.get("qty_label") or "")

    if d and len(comps) >= 2:
        parts = [val(r) for r in comps]
        parts = [p for p in parts if p]
        joined = d.join(parts) if parts else ""
        joined = re.sub(r"\s+", " ", joined).strip()
        return joined

    return val(comps[0] if comps else "unknown")


# ------------------- Etsy scale/meta map -------------------


def build_property_meta_map(inv: Dict[str, Any]) -> Dict[Tuple[int, str], Dict[str, Any]]:
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
            for extra in ("ott_value_qualifier",):
                if pv.get(extra) is not None:
                    meta[extra] = pv.get(extra)

            if not meta:
                continue

            for v in vals:
                out[(pid, norm_tr(strip_option_word(str(v))))] = meta
    return out


# ------------------- Schema-driven DB resolvers -------------------


def upsert_by_desc_schema(table: str, desc_value: str, code_len: int, desc2_value: Optional[str] = None) -> str:
    rows = load_table(table)
    target = norm_tr(desc_value)
    has_desc2 = table_has_column(table, "desc2")

    for r in rows:
        if norm_tr(r["desc"]) == target:
            DB_ACTIONS.append(
                {"action": "EXISTS", "table": table, "desc": desc_value, "code": r["code"], "desc2": r.get("desc2")}
            )
            if has_desc2 and desc2_value:
                old = (r.get("desc2") or "").strip()
                if (not old) or old == "-":
                    DB_ACTIONS.append({"action": "WOULD_UPDATE", "table": table, "code": r["code"], "set_desc2": desc2_value})
                    execute("UPDATE %s SET desc2=%%s WHERE code=%%s" % table, (desc2_value, r["code"]))
            return r["code"]

    existing = {r["code"] for r in fetchall_dict("SELECT code FROM %s" % table)}
    new_code = first_free_code(existing, code_len)

    values: Dict[str, Any] = {"code": new_code, "desc": desc_value}
    if has_desc2 and (desc2_value is not None):
        values["desc2"] = desc2_value

    sql, params = build_insert_sql(table, values, fallback="-")
    DB_ACTIONS.append({"action": "WOULD_INSERT", "table": table, "desc": desc_value, "code": new_code, "desc2": values.get("desc2", None)})
    execute(sql, params)
    return new_code


def resolve_type_code(profile: Profile, type_name: str, supplier_default: str = "asya") -> str:
    rows = fetchall_dict("SELECT code, `desc` FROM i_type")
    target = norm_tr(type_name)

    for r in rows:
        if norm_tr(r["desc"]) == target:
            DB_ACTIONS.append({"action": "EXISTS", "table": "i_type", "desc": type_name, "code": r["code"]})
            return r["code"]

    existing = {r["code"] for r in fetchall_dict("SELECT code FROM i_type")}
    new_code = first_free_code(existing, profile.type_len)

    meta = get_table_meta("i_type")
    values: Dict[str, Any] = {"code": new_code, "desc": type_name}

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


def resolve_space_code(profile: Profile, space_raw: str) -> str:
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
        return upsert_by_desc_schema("i_space", "%s cm bosluk" % n, profile.space_len)

    return upsert_by_desc_schema("i_space", space_raw, profile.space_len)


def resolve_length_code(profile: Profile, length_raw: str, i_length_rows: List[Dict[str, Any]]) -> str:
    raw = str(length_raw or "").strip()
    raw_l = norm_tr(raw)
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
            DB_ACTIONS.append({"action": "EXISTS", "table": "i_length", "code": r["code"], "desc": r.get("desc"), "desc2": r.get("desc2"), "match": "desc2"})
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
        DB_ACTIONS.append({"action": "EXISTS", "table": "i_length", "code": r["code"], "desc": r.get("desc"), "desc2": r.get("desc2"), "match": "desc"})
        return r["code"]

    desc2_value = None
    if wants_inches:
        num = normalize_numeric(raw)
        desc2_value = f"{num} inches"
    return upsert_by_desc_schema("i_length", raw, profile.length_len, desc2_value=desc2_value)


def resolve_color_code(profile: Profile, workshop_color_label: str, i_color_rows: List[Dict[str, Any]]) -> str:
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

    return upsert_by_desc_schema("i_color", raw, profile.color_len)


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


# ------------------- pricing -------------------

def calc_price(
    payload: Dict[str, Any],
    color_code: str,
    qty_n: Optional[int],
    color_label: Optional[str] = None,
    qty_label: Optional[str] = None,
) -> float:
    pricing_by_raw = payload.get("pricing_by")
    pricing = payload.get("pricing")

    if not pricing_by_raw:
        raise ValueError("Missing required field: pricing_by")

    pricing_by = str(pricing_by_raw).strip().lower()

    if pricing is None:
        raise ValueError("Missing required field: pricing")

    if pricing_by == "fixed":
        if isinstance(pricing, dict):
            raise ValueError("pricing_by=fixed requires scalar pricing value")
        try:
            return float(pricing)
        except (TypeError, ValueError):
            raise ValueError(f"Invalid fixed pricing value: {pricing!r}")

    if pricing_by == "color":
        if not isinstance(pricing, dict) or not pricing:
            raise ValueError("pricing_by=color requires pricing to be a non-empty object")

        if color_label and color_label in pricing:
            return float(pricing[color_label])

        if color_code in pricing:
            return float(pricing[color_code])

        wanted = []
        if color_code:
            wanted.append(str(color_code).strip().lower())
        if color_label:
            wanted.append(str(color_label).strip().lower())

        for k, v in pricing.items():
            key_norm = str(k).strip().lower()
            if key_norm in wanted:
                return float(v)

        raise ValueError(
            f"pricing_by=color but no matching price found for color_code={color_code!r}, color_label={color_label!r}"
        )

    if pricing_by == "qty":
        if not isinstance(pricing, dict) or not pricing:
            raise ValueError("pricing_by=qty requires pricing to be a non-empty object")

        # 1) exact qty label match
        if qty_label and qty_label in pricing:
            return float(pricing[qty_label])

        # 2) case-insensitive qty label match
        if qty_label:
            qty_label_norm = str(qty_label).strip().lower()
            for k, v in pricing.items():
                if str(k).strip().lower() == qty_label_norm:
                    return float(v)

        # 3) fallback numeric qty match
        if qty_n is not None:
            qty_key = str(qty_n)

            if qty_key in pricing:
                return float(pricing[qty_key])

            for k, v in pricing.items():
                if str(k).strip() == qty_key:
                    return float(v)

        raise ValueError(
            f"pricing_by=qty but no matching price found for qty_label={qty_label!r}, qty={qty_n!r}"
        )

    raise ValueError(f"Unknown pricing_by value: {pricing_by!r}")

# ------------------- reporting helpers -------------------


def summarize_db_plan(actions: List[Dict[str, Any]]) -> Dict[str, Any]:
    by_table: Dict[str, Dict[str, List[Dict[str, Any]]]] = defaultdict(lambda: {"exists": [], "missing": [], "updates": []})
    for a in actions:
        t = a.get("table")
        if not t:
            continue
        act = a.get("action")
        if act == "EXISTS":
            by_table[t]["exists"].append(a)
        elif act == "WOULD_INSERT":
            by_table[t]["missing"].append(a)
        elif act == "WOULD_UPDATE":
            by_table[t]["updates"].append(a)

    def compact(item: Dict[str, Any]) -> Dict[str, Any]:
        keys = ["table", "code", "desc", "desc2", "set_desc2", "match"]
        return {k: item.get(k) for k in keys if item.get(k) is not None}

    out: Dict[str, Any] = {}
    for t, d in by_table.items():
        out[t] = {
            "exists": [compact(x) for x in d["exists"]],
            "missing": [compact(x) for x in d["missing"]],
            "updates": [compact(x) for x in d["updates"]],
        }
    return out


# ------------------- SKU decode -------------------


def decode_sku(profile: Profile, sku: str) -> Dict[str, str]:
    sku = (sku or "").strip()
    seglen = profile.sku_lengths()
    total = sum(seglen[k] for k in profile.sku_order)
    if len(sku) < total:
        return {"sku": sku, "error": "too_short", "expected_len": str(total)}

    out: Dict[str, str] = {"sku": sku}
    idx = 0
    for seg in profile.sku_order:
        n = seglen[seg]
        out[seg] = sku[idx:idx + n]
        idx += n

    out["pretty"] = " ".join(["%s=%s" % (k, out[k]) for k in profile.sku_order])
    return out


# ------------------- core -------------------


def build_and_push(profile: Profile, payload: Dict[str, Any], dry_run: bool) -> None:
    DB_ACTIONS.clear()

    listing_id = int(payload["listing_id"])
    safe_print("[INFO] profile: %s | db: %s" % (profile.name, os.environ.get("MYSQL_DB")))
    safe_print("[INFO] Etsy inventory GET: %s" % listing_id)

    inv = get_inventory(listing_id)
    safe_print("[STEP] inventory fetched. products: %s" % len(inv.get("products") or []))

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

    color_field = "desc" if profile.name == "silveristic" else choose_label_field(i_color_rows)
    length_field = choose_label_field(i_length_rows)

    color_set_lower: Set[str] = set(norm_tr(r.get(color_field) or "") for r in i_color_rows)
    length_set_lower: Set[str] = set(norm_tr(r.get(length_field) or "") for r in i_length_rows)

    safe_print("[STEP] analyzing template ...")
    tpl = analyze_template(inv, color_set_lower, length_set_lower, payload)
    props: List[Dict[str, Any]] = tpl["properties"]

    safe_print("[INFO] Template properties: %s" % ([
        (p["property_id"], p["property_name"], p["components"], p["delim"], p["sample_values"][:3])
        for p in props
    ],))

    qty_prop = next((p for p in props if "qty" in (p.get("components") or [])), None)
    qty_is_count = False
    if qty_prop:
        sv = qty_prop.get("sample_values") or []
        qty_is_count = any(NUM_PREFIX.match(strip_option_word(html.unescape(x or "")).strip()) for x in sv)

    type_code = resolve_type_code(profile, payload.get("type", "-"))
    size_code = upsert_by_desc_schema("i_size", payload.get("size", "-"), profile.size_len)
    space_code = upsert_by_desc_schema("i_space", payload.get("space", "-"), profile.space_len) if norm_tr(payload.get("space", "-")) in ("", "-", "0") else resolve_space_code(profile, payload.get("space", "-"))
    start_code = upsert_by_desc_schema("i_start", payload.get("start", "ortada"), profile.start_len)

    needs_color = any("color" in (p.get("components") or []) for p in props)
    needs_length = any("length" in (p.get("components") or []) for p in props)
    needs_qty = any("qty" in (p.get("components") or []) for p in props)

    display_overrides = payload.get("display_value_overrides") or {}
    display_overrides_by_prop = payload.get("display_value_overrides_by_property") or {}

    display_overrides = {str(k): v for k, v in display_overrides.items()} if isinstance(display_overrides, dict) else {}
    for k in list(display_overrides.keys()):
        display_overrides[k] = parse_simple_config_string_map(display_overrides[k])

    display_overrides_by_prop = {str(k): v for k, v in display_overrides_by_prop.items()} if isinstance(display_overrides_by_prop, dict) else {}
    for pid in list(display_overrides_by_prop.keys()):
        per = display_overrides_by_prop[pid]
        if isinstance(per, dict):
            per2: Dict[str, Dict[str, str]] = {}
            for role, mp in per.items():
                per2[str(role)] = parse_simple_config_string_map(mp)
            display_overrides_by_prop[pid] = per2

    # ------------------- COLOR INPUT -------------------
    colors_in = payload.get("colors") or []
    workshop_color_labels: List[str] = []
    color_inline_override_map: Dict[str, str] = {}

    if isinstance(colors_in, list):
        for x in colors_in:
            raw, ov = split_override_label(str(x))
            if raw:
                workshop_color_labels.append(raw)
                if ov:
                    color_inline_override_map[raw] = ov
    elif isinstance(colors_in, dict):
        keys = [str(k).strip() for k in colors_in.keys()]
        vals = [str(v).strip() for v in colors_in.values() if v is not None]
        if keys and all(is_code_like(k, profile.color_len) for k in keys) and any(v and not is_code_like(v, profile.color_len) for v in vals):
            for v in colors_in.values():
                raw, ov = split_override_label(str(v))
                if raw:
                    workshop_color_labels.append(raw)
                    if ov:
                        color_inline_override_map[raw] = ov
        else:
            for k in keys:
                raw, ov = split_override_label(k)
                if raw:
                    workshop_color_labels.append(raw)
                    if ov:
                        color_inline_override_map[raw] = ov

    # ------------------- LENGTH INPUT -------------------
    lengths_in = payload.get("lengths", payload.get("lengths_inch", []))
    prop_len_ref = next((p for p in props if "length" in (p.get("components") or [])), None)

    length_code_map: Dict[str, str] = {}
    length_label_map: Dict[str, str] = {}
    if needs_length:
        if not lengths_in:
            raise ValueError("Template needs length but input lengths empty")
        for rawL0 in lengths_in:
            rawL0 = str(rawL0)
            L_workshop, L_inline_override = split_override_label(rawL0)

            length_code_map[rawL0] = resolve_length_code(profile, L_workshop, i_length_rows)

            if L_inline_override:
                length_label = L_inline_override
            else:
                length_label = normalize_length_for_property(L_workshop, prop_len_ref or {"sample_values": []})

            if prop_len_ref:
                ovr = resolve_display_override(payload, role="length", property_id=int(prop_len_ref["property_id"]), raw_value=L_workshop)
                if ovr:
                    length_label = ovr

            length_label_map[rawL0] = length_label

    # ------------------- QTY INPUT -------------------
    quantities_in = payload.get("quantities", [])
    qty_numbers = payload.get("qty_numbers", {})

    qty_code_map: Dict[str, str] = {}
    qty_num_map: Dict[str, Optional[int]] = {}
    qty_label_map: Dict[str, str] = {}

    if needs_qty:
        if not quantities_in:
            raise ValueError("Template needs qty but input.quantities is empty")

        for qraw0 in quantities_in:
            qraw0 = str(qraw0)
            q_workshop, q_inline_override = split_override_label(qraw0)

            qty_code_map[qraw0] = upsert_by_desc_schema("i_qty", q_workshop, profile.qty_len)

            if qraw0 in qty_numbers:
                qty_num_map[qraw0] = int(qty_numbers[qraw0])
            else:
                m = re.search(r"(\d+)", q_workshop)
                qty_num_map[qraw0] = int(m.group(1)) if m else None

            q_label = ""
            if q_inline_override:
                q_label = q_inline_override
            else:
                qovr = None
                if qty_prop:
                    qovr = resolve_display_override(payload, role="qty", property_id=int(qty_prop["property_id"]), raw_value=q_workshop)
                else:
                    qovr = resolve_display_override(payload, role="qty", property_id=None, raw_value=q_workshop)

                if qovr:
                    q_label = qovr
                else:
                    if qty_num_map[qraw0] is not None and qty_is_count:
                        q_label = build_qty_label(int(qty_num_map[qraw0]), tpl)
                    else:
                        q_label = q_workshop

            qty_label_map[qraw0] = q_label

    # ------------------- FORCE SKU QTY -------------------
    sku_qty_raw = payload.get("sku_qty") or payload.get("sku_quantity") or payload.get("quantity") or payload.get("qty")
    if not sku_qty_raw:
        qlist = payload.get("quantities", [])
        if isinstance(qlist, list) and len(qlist) == 1:
            sku_qty_raw = qlist[0]

    forced_qty_code_part = ("0" * profile.qty_len)
    forced_qty_n: Optional[int] = None

    if sku_qty_raw:
        sku_qty_raw = str(sku_qty_raw).strip()
        sku_qty_workshop, _sku_inline_ovr = split_override_label(sku_qty_raw)
        forced_qty_code_part = upsert_by_desc_schema("i_qty", sku_qty_workshop, profile.qty_len)
        m = re.search(r"(\d+)", sku_qty_workshop)
        if m:
            forced_qty_n = int(m.group(1))

    colors_iter = workshop_color_labels if needs_color else ["X"]
    lengths_iter = [str(x) for x in lengths_in] if needs_length else [None]
    qty_iter = quantities_in if needs_qty else [None]

    products_out: List[Dict[str, Any]] = []

    for workshop_color_label, L_raw0, qraw0 in product(colors_iter, lengths_iter, qty_iter):
        # COLOR
        if needs_color:
            c_workshop = str(workshop_color_label)
            c_code = resolve_color_code(profile, c_workshop, i_color_rows)

            c_label = color_inline_override_map.get(c_workshop)
            if not c_label:
                first_color_prop = next((p for p in props if "color" in (p.get("components") or [])), None)
                if first_color_prop:
                    c_label = resolve_display_override(payload, role="color", property_id=int(first_color_prop["property_id"]), raw_value=c_workshop)
            color_label_for_ctx = c_label or c_workshop
        else:
            c_code = "X"
            color_label_for_ctx = ""

        # LENGTH
        length_label = ""
        len_code_part = ("0" * profile.length_len)
        if needs_length and L_raw0 is not None:
            length_label = length_label_map[str(L_raw0)]
            len_code_part = length_code_map[str(L_raw0)]

        # QTY
        qty_label = ""
        qty_code_part = ("0" * profile.qty_len)
        qty_n: Optional[int] = None

        if needs_qty and qraw0 is not None:
            qty_label = qty_label_map[str(qraw0)]
            qty_code_part = qty_code_map[str(qraw0)]
            qty_n = qty_num_map.get(str(qraw0))
        else:
            if sku_qty_raw:
                qty_code_part = forced_qty_code_part
                qty_n = forced_qty_n

        price = calc_price(
            payload,
            c_code,
            qty_n,
            color_label=color_label_for_ctx,
            qty_label=qty_label,
        )

        ctx = {
            "color_label": color_label_for_ctx,
            "length_label": length_label,
            "qty_label": qty_label,
        }

        pv_list = []
        for prop in props:
            pid = int(prop["property_id"])
            vstr = build_property_value(
                prop,
                ctx,
                display_overrides,
                display_overrides_by_prop,
            )
            vnorm = norm_tr(strip_option_word(vstr))

            pv_obj: Dict[str, Any] = {
                "property_id": pid,
                "property_name": prop["property_name"],
                "values": [vstr],
            }

            meta = pv_meta_map.get((pid, vnorm))
            if meta:
                pv_obj.update(meta)

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
                "offerings": [
                    {
                        "price": price,
                        "quantity": payload.get("stock", 900),
                        "is_enabled": True,
                        "readiness_state_id": rs_id,
                    }
                ],
            }
        )

    prop_ids = [p["property_id"] for p in props if p.get("property_id") is not None]

    put_payload = {
        "products": products_out,
        "price_on_property": prop_ids,
        "quantity_on_property": [],
        "sku_on_property": prop_ids,
    }

    if dry_run:
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
                "applied_display_value_overrides": display_overrides,
                "applied_display_value_overrides_by_property": display_overrides_by_prop,
            },
            ensure_ascii=False,
            indent=2,
        )
        safe_print(out)
        return

    safe_print("[INFO] PUT overwrite products: %s" % len(products_out))
    safe_print("[INFO] readiness_state_id: %s" % rs_id)
    safe_print("[INFO] price_on_property: %s" % prop_ids)
    safe_print("[INFO] sku_on_property: %s" % prop_ids)

    safe_print("----- PUT_PAYLOAD_JSON_BEGIN -----")
    safe_print(dump_payload_for_log(put_payload))
    safe_print("----- PUT_PAYLOAD_JSON_END -----")

    resp = put_inventory_overwrite(listing_id, put_payload)
    safe_print("OK listing_id: %s products: %s" % (resp.get("listing_id"), len(products_out)))


def main():
    global DEBUG, WRITE_ENABLED

    safe_print("[BOOT] Running: %s" % os.path.abspath(__file__))
    safe_print("[BOOT] Python: %s" % sys.version)

    ap = argparse.ArgumentParser()
    ap.add_argument("input_json", help="Path to input json")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--debug", action="store_true")
    ap.add_argument("--profile", default=os.environ.get("DB_PROFILE", "shiny"))
    args = ap.parse_args()

    DEBUG = bool(args.debug)
    WRITE_ENABLED = not bool(args.dry_run)

    prof_name = (args.profile or "shiny").strip().lower()
    prof_name = prof_name.lstrip("-")

    if prof_name not in PROFILES:
        raise RuntimeError("Unknown profile: %s (available: %s)" % (prof_name, ", ".join(PROFILES.keys())))
    profile = PROFILES[prof_name]

    safe_print("[BOOT] dry_run: %s | WRITE_ENABLED: %s" % (args.dry_run, WRITE_ENABLED))
    safe_print("[BOOT] profile: %s" % profile.name)

    with open(args.input_json, "r", encoding="utf-8") as f:
        payload = json.load(f)

    build_and_push(profile, payload, dry_run=args.dry_run)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        safe_print("[ERROR] %r" % e)
        raise