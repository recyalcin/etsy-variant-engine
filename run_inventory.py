# run_inventory.py  (Python 3.9.x)
# pip install pymysql requests python-dotenv

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

# --- Windows console UTF-8 fix (prevents UnicodeEncodeError on Turkish chars) ---
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
        # which tables have desc2?
        table_desc2: Dict[str, bool],
        # code lengths
        type_len: int,
        length_len: int,
        color_len: int,
        qty_len: int,
        size_len: int,
        start_len: int,
        space_len: int,
        # sku order
        sku_order: List[str],
    ):
        self.name = name
        self.table_desc2 = table_desc2

        self.type_len = type_len
        self.length_len = length_len
        self.color_len = color_len
        self.qty_len = qty_len
        self.size_len = size_len
        self.start_len = start_len
        self.space_len = space_len

        self.sku_order = sku_order

    def has_desc2(self, table: str) -> bool:
        return bool(self.table_desc2.get(table, False))

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
    # SHINY (eski)
    "shiny": Profile(
        name="shiny",
        table_desc2={
            "i_color": True,
            "i_length": True,
            "i_qty": True,
            "i_type": True,
            "i_size": True,
            "i_start": True,
            "i_space": True,
        },
        type_len=2,
        length_len=2,
        color_len=1,
        qty_len=2,
        size_len=1,
        start_len=2,
        space_len=1,
        sku_order=["type", "color", "qty", "length", "start", "space", "size"],
    ),

    # SILVERISTIC
    "silveristic": Profile(
        name="silveristic",
        table_desc2={
            "i_color": False,   # code-desc
            "i_length": True,   # code-desc-desc2 (cm->inch or alias)
            "i_qty": False,     # code-desc  (desc must be workshop token exactly; no desc2)
            "i_type": False,    # code-desc-supplier-catalog_code
            "i_size": False,    # code-desc
            "i_start": False,   # code-desc
            "i_space": False,   # code-desc
        },
        type_len=4,
        length_len=4,
        color_len=1,
        qty_len=3,
        size_len=4,
        start_len=3,
        space_len=2,
        # SKU: i_type - i_length - i_color - i_qty - i_size - i_start - i_space
        sku_order=["type", "length", "color", "qty", "size", "start", "space"],
    ),
}


# ------------------- utils -------------------

def dprint(*args):
    if DEBUG:
        print(*args, flush=True)

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

def safe_print(s: str):
    try:
        print(s, flush=True)
    except UnicodeEncodeError:
        print(s.encode("utf-8", "replace").decode("utf-8"), flush=True)


# ------------------- Etsy Token Manager -------------------

ETSY_TOKEN_CACHE = {"access_token": None, "expires_at": 0.0}

def refresh_access_token() -> str:
    api_key = require_env("ETSY_API_KEY")
    refresh_tok = require_env("ETSY_REFRESH_TOKEN")

    # Etsy expects client_id without the ":secret" part
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
    # if key already contains ":" then use as-is, else join key:secret
    x_api_key = f"{key}:{secret}" if (secret and ":" not in key) else key

    return {
        "Authorization": f"Bearer {get_access_token()}",
        "x-api-key": x_api_key,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

def etsy_request(method: str, url: str, **kwargs) -> requests.Response:
    # keep timeout stable on retry
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


# ------------------- generic table reads -------------------

def load_table(profile: Profile, table: str) -> List[Dict[str, Any]]:
    if profile.has_desc2(table):
        return fetchall_dict("SELECT code, `desc`, desc2 FROM %s" % table)
    return fetchall_dict("SELECT code, `desc` FROM %s" % table)


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

    for c in color_set_lower:
        if c and c in tl:
            return "color"

    if tl in length_set_lower:
        return "length"
    if looks_like_length_token(tl):
        return "length"

    m = NUM_PREFIX.match(t)
    if m:
        num_str = m.group(1)
        tail = (m.group(2) or "").strip().lower()
        if "." in num_str:
            return "unknown"
        n = int(num_str)
        if n <= 50 and tail not in ("us", "uk", "eu", "cm", "mm"):
            return "qty"

    return "unknown"

def infer_qty_units(samples: List[str]) -> Tuple[Optional[str], Optional[str]]:
    sing = None
    pl = None
    for s in samples:
        s = html.unescape(s or "")
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

def analyze_template(inv: Dict[str, Any], color_set_lower: Set[str], length_set_lower: Set[str]) -> Dict[str, Any]:
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

        # "Color / Length" special: pick delim from samples
        if ("color" in pname_l) and ("length" in pname_l):
            delim = find_best_delim(samples_dec) or " / "
            props.append({
                "property_id": pid,
                "property_name": pname,
                "position": pos.get(pid),
                "delim": delim,
                "components": ["color", "length"],
                "sample_values": samples_dec[:60],
            })
            continue

        delim = find_best_delim(samples_dec)
        if delim and samples_dec:
            rep = next((s for s in samples_dec if delim in s), samples_dec[0])
            parts = [x.strip() for x in rep.split(delim) if x.strip()]
            comps = [classify_token(part, color_set_lower, length_set_lower) for part in parts]
        else:
            comps = [classify_token(samples_dec[0], color_set_lower, length_set_lower)] if samples_dec else ["unknown"]

        for s in samples_dec:
            if NUM_PREFIX.match(s.strip()):
                qty_samples_all.append(s)

        props.append({
            "property_id": pid,
            "property_name": pname,
            "position": pos.get(pid),
            "delim": delim,
            "components": comps,
            "sample_values": samples_dec[:60],
        })

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

    return s

def build_property_value(prop: Dict[str, Any], ctx: Dict[str, str]) -> str:
    comps = prop.get("components") or []
    d = prop.get("delim")

    def val(role: str) -> str:
        if role == "color":
            return ctx.get("color_label", "")
        if role == "length":
            return ctx.get("length_label", "")
        if role == "qty":
            return ctx.get("qty_label", "")
        if role == "unknown" and ctx.get("length_label"):
            return ctx.get("length_label", "")
        return ctx.get("color_label") or ctx.get("length_label") or ctx.get("qty_label") or ""

    if d and len(comps) >= 2:
        return d.join(val(r) for r in comps)
    return val(comps[0] if comps else "unknown")


# ------------------- DB resolvers -------------------

def upsert_by_desc(profile: Profile, table: str, desc_value: str, code_len: int, desc2_value: Optional[str] = None) -> str:
    rows = load_table(profile, table)
    target = norm_tr(desc_value)

    for r in rows:
        if norm_tr(r["desc"]) == target:
            DB_ACTIONS.append({"action": "EXISTS", "table": table, "desc": desc_value, "code": r["code"], "desc2": r.get("desc2")})
            if desc2_value and profile.has_desc2(table):
                if (not r.get("desc2")) or r.get("desc2") == "-":
                    DB_ACTIONS.append({"action": "WOULD_UPDATE", "table": table, "code": r["code"], "set_desc2": desc2_value})
                    execute("UPDATE %s SET desc2=%%s WHERE code=%%s" % table, (desc2_value, r["code"]))
            return r["code"]

    existing = {r["code"] for r in fetchall_dict("SELECT code FROM %s" % table)}
    new_code = first_free_code(existing, code_len)

    if profile.has_desc2(table):
        DB_ACTIONS.append({"action": "WOULD_INSERT", "table": table, "desc": desc_value, "code": new_code, "desc2": (desc2_value or "-")})
        execute("INSERT INTO %s (code, `desc`, desc2) VALUES (%%s,%%s,%%s)" % table, (new_code, desc_value, desc2_value or "-"))
    else:
        DB_ACTIONS.append({"action": "WOULD_INSERT", "table": table, "desc": desc_value, "code": new_code})
        execute("INSERT INTO %s (code, `desc`) VALUES (%%s,%%s)" % table, (new_code, desc_value))

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
    DB_ACTIONS.append({"action": "WOULD_INSERT", "table": "i_type", "desc": type_name, "code": new_code})

    if profile.name == "silveristic":
        execute(
            "INSERT INTO i_type (code, `desc`, supplier, catalog_code) VALUES (%s,%s,%s,%s)",
            (new_code, type_name, supplier_default, "")
        )
    else:
        execute(
            "INSERT INTO i_type (code, `desc`) VALUES (%s,%s)",
            (new_code, type_name)
        )

    return new_code

def resolve_space_code(profile: Profile, space_raw: str) -> str:
    s = norm_tr(space_raw)
    if s in ("", "-", "0"):
        return upsert_by_desc(profile, "i_space", "-", profile.space_len)

    if "bitisik" in s or "bitişik" in s:
        rows = fetchall_dict("SELECT code, `desc` FROM i_space")
        for r in rows:
            if "bitisik" in norm_tr(r["desc"]):
                DB_ACTIONS.append({"action": "EXISTS", "table": "i_space", "desc": r["desc"], "code": r["code"]})
                return r["code"]
        return upsert_by_desc(profile, "i_space", "BITISIK", profile.space_len)

    m = re.search(r"(\d+)\s*cm", s)
    if m:
        n = m.group(1)
        rows = fetchall_dict("SELECT code, `desc` FROM i_space")
        for r in rows:
            d = norm_tr(r["desc"])
            if (n in d) and ("cm" in d):
                DB_ACTIONS.append({"action": "EXISTS", "table": "i_space", "desc": r["desc"], "code": r["code"]})
                return r["code"]
        return upsert_by_desc(profile, "i_space", "%s cm bosluk" % n, profile.space_len)

    return upsert_by_desc(profile, "i_space", space_raw, profile.space_len)

def resolve_length_code(profile: Profile, length_raw: str, i_length_rows: List[Dict[str, Any]]) -> str:
    raw = str(length_raw or "").strip()
    raw_l = norm_tr(raw)
    key = normalize_numeric(raw)

    wants_inches = ('"' in raw) or ("inch" in raw_l)

    def field_indicates_inches(s: str) -> bool:
        sl = norm_tr(s or "")
        # "inch" ya da çift tırnak varsa inches kabul et
        return ("inch" in sl) or ('"' in (s or ""))

    # 1) match desc2 (if exists)
    cand_desc2 = []
    for r in i_length_rows:
        d2 = (r.get("desc2") or "").strip()
        if not d2 or d2 == "-":
            continue

        # Eğer input inches istiyorsa, DB alanı da inches belirtmeli.
        if wants_inches and (not field_indicates_inches(d2)):
            continue

        if normalize_numeric(d2) == key:
            cand_desc2.append(r)

    if cand_desc2:
        # wants_inches ise zaten inches belirtenler kaldı; ilkini seç
        r = cand_desc2[0]
        DB_ACTIONS.append({"action": "EXISTS", "table": "i_length", "code": r["code"], "desc": r.get("desc"), "desc2": r.get("desc2"), "match": "desc2"})
        return r["code"]

    # 2) match desc
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

    # 3) insert
    # Eğer input inches ise desc2'yi "11.5 inches" formatında yaz
    if wants_inches:
        num = normalize_numeric(raw)  # "11.5"
        desc2 = f"{num} inches"
        return upsert_by_desc(profile, "i_length", raw, profile.length_len, desc2_value=desc2)

    # inches değilse eski davranış
    return upsert_by_desc(profile, "i_length", raw, profile.length_len, desc2_value=raw)


# ------------------- readiness_state_id -------------------

def infer_readiness_state_id(inv: Dict[str, Any]) -> Optional[int]:
    """
    Reuse readiness_state_id from current listing inventory (most reliable).
    """
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

def calc_price(payload: Dict[str, Any], color_code: str, qty_n: Optional[int], color_label: Optional[str] = None) -> float:
    """
    Supports:
    - app.py output: color_prices (by code OR by label)
    - new style: pricing.mode = fixed/by_color/by_qty
    - pricing dict without mode (treated as by_color)
    - legacy: prices (qty dict) or price (fixed)
    """
    # 0) app.py style: color_prices
    cp = payload.get("color_prices")
    if isinstance(cp, dict) and cp:
        if color_code in cp:
            return float(cp[color_code])
        if color_label and (color_label in cp):
            return float(cp[color_label])

    # 1) New style pricing block
    pricing = payload.get("pricing")
    if isinstance(pricing, dict) and pricing:
        # if no "mode", treat as direct by_color dict
        if "mode" not in pricing:
            if color_code in pricing:
                return float(pricing[color_code])
            if color_label and (color_label in pricing):
                return float(pricing[color_label])
            raise ValueError("pricing provided but missing key for color: %s / %s" % (color_code, color_label))

        mode = pricing.get("mode", "fixed")

        if mode == "fixed":
            return float(pricing["fixed"])

        if mode == "by_color":
            byc = pricing.get("by_color") or {}
            if color_code in byc:
                return float(byc[color_code])
            if color_label and (color_label in byc):
                return float(byc[color_label])
            raise ValueError("pricing.mode=by_color but missing key for color: %s / %s" % (color_code, color_label))

        if mode == "by_qty":
            if qty_n is None:
                raise ValueError("pricing.mode=by_qty but qty missing")
            return float(pricing["by_qty"][str(qty_n)])

        raise ValueError("Unknown pricing mode: %s" % mode)

    # 2) Legacy support → prices dict
    prices = payload.get("prices")
    if isinstance(prices, dict) and prices:
        if qty_n is not None:
            if str(qty_n) in prices:
                return float(prices[str(qty_n)])
            for k, v in prices.items():
                if str(qty_n) in str(k):
                    return float(v)
        first = list(prices.values())[0]
        return float(first)

    # 3) Legacy fixed
    if "price" in payload:
        return float(payload["price"])

    raise ValueError("Missing pricing in input.json (expected pricing/color_prices/prices/price)")


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
        out[seg] = sku[idx:idx+n]
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

    # pick readiness_state_id (most reliable: reuse existing)
    rs_id = payload.get("readiness_state_id")
    if rs_id is None:
        rs_id = infer_readiness_state_id(inv)
    if rs_id is None:
        raise ValueError("readiness_state_id not found in payload or listing inventory. Add it to input or ensure listing has existing offerings.")
    rs_id = int(rs_id)

    safe_print("[STEP] loading db tables ...")
    i_color_rows = load_table(profile, "i_color")
    i_length_rows = load_table(profile, "i_length")

    # sets for template analysis
    color_set_lower: Set[str] = set()
    if profile.name == "silveristic":
        for r in i_color_rows:
            color_set_lower.add(norm_tr(r.get("desc") or ""))
    else:
        # shiny: use desc2 (etsy label)
        for r in i_color_rows:
            if r.get("desc2") and r.get("desc2") != "-":
                color_set_lower.add(norm_tr(r.get("desc2") or ""))

    length_set_lower: Set[str] = set()
    for r in i_length_rows:
        d2 = (r.get("desc2") or "").strip()
        d = (r.get("desc") or "").strip()
        if d2 and d2 != "-":
            length_set_lower.add(norm_tr(d2))
        elif d and d != "-":
            length_set_lower.add(norm_tr(d))

    safe_print("[STEP] analyzing template ...")
    tpl = analyze_template(inv, color_set_lower, length_set_lower)
    props: List[Dict[str, Any]] = tpl["properties"]

    safe_print("[INFO] Template properties: %s" % ([
        (p["property_id"], p["property_name"], p["components"], p["delim"], p["sample_values"][:3])
        for p in props
    ],))

    # detect qty property
    qty_prop = next((p for p in props if "qty" in (p.get("components") or [])), None)
    qty_is_count = False
    if qty_prop:
        sv = qty_prop.get("sample_values") or []
        qty_is_count = any(NUM_PREFIX.match((html.unescape(x or "")).strip()) for x in sv)

    # resolve segments
    type_code = resolve_type_code(profile, payload.get("type", "-"))
    size_code = upsert_by_desc(profile, "i_size", payload.get("size", "-"), profile.size_len)
    space_code = resolve_space_code(profile, payload.get("space", "-"))
    start_code = upsert_by_desc(profile, "i_start", payload.get("start", "ortada"), profile.start_len)

    needs_color = any("color" in (p.get("components") or []) for p in props)
    needs_length = any("length" in (p.get("components") or []) for p in props)
    needs_qty = any("qty" in (p.get("components") or []) for p in props)

    colors_map = payload.get("colors") or {}
    lengths_in = payload.get("lengths", payload.get("lengths_inch", []))
    quantities_in = payload.get("quantities", [])
    qty_numbers = payload.get("qty_numbers", {})

    prop_len_ref = next((p for p in props if "length" in (p.get("components") or [])), None)

    # lengths mapping
    length_code_map: Dict[str, str] = {}
    length_label_map: Dict[str, str] = {}
    if needs_length:
        if not lengths_in:
            raise ValueError("Template needs length but input lengths empty")
        for rawL in lengths_in:
            rawL = str(rawL)
            L_label = normalize_length_for_property(rawL, prop_len_ref or {"sample_values": []})
            length_label_map[rawL] = L_label
            length_code_map[rawL] = resolve_length_code(profile, rawL, i_length_rows)

    # qty mapping (count-mode only here)
    qty_code_map: Dict[str, str] = {}
    qty_num_map: Dict[str, int] = {}
    if needs_qty:
        if not quantities_in:
            raise ValueError("Template needs qty but input.quantities is empty")
        if not qty_is_count:
            raise ValueError("Template qty seems ENUM (not count). This run supports count-mode for now.")
        for qraw in quantities_in:
            qty_code_map[qraw] = upsert_by_desc(profile, "i_qty", qraw, profile.qty_len)
            if qraw in qty_numbers:
                qty_num_map[qraw] = int(qty_numbers[qraw])
            else:
                m = re.search(r"(\d+)", qraw)
                if not m:
                    raise ValueError("qty_numbers missing and parse failed for: %s" % qraw)
                qty_num_map[qraw] = int(m.group(1))

    # iterate
    colors_iter = list(colors_map.keys()) if needs_color else ["X"]
    lengths_iter = [str(x) for x in lengths_in] if needs_length else [None]
    qty_iter = quantities_in if needs_qty else [None]

    products_out: List[Dict[str, Any]] = []

    for c_code, L_raw, qraw in product(colors_iter, lengths_iter, qty_iter):
        color_label = colors_map.get(c_code, "") if needs_color else ""

        length_label = ""
        len_code_part = ("0" * profile.length_len)
        if needs_length and L_raw is not None:
            length_label = length_label_map[L_raw]
            len_code_part = length_code_map[L_raw]

        qty_label = ""
        qty_code_part = ("0" * profile.qty_len)
        qty_n: Optional[int] = None
        if needs_qty and qraw is not None:
            qty_n = qty_num_map[qraw]
            qty_label = build_qty_label(qty_n, tpl)
            qty_code_part = qty_code_map[qraw]

        price = calc_price(payload, c_code, qty_n, color_label=color_label)

        ctx = {"color_label": color_label, "length_label": length_label, "qty_label": qty_label}

        pv_list = []
        for prop in props:
            pv_list.append({
                "property_id": prop["property_id"],
                "property_name": prop["property_name"],
                "values": [build_property_value(prop, ctx)]
            })

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

        products_out.append({
            "sku": sku,
            "property_values": pv_list,
            "offerings": [{
                "price": price,
                "quantity": payload.get("stock", 900),
                "is_enabled": True,
                "readiness_state_id": rs_id,
            }]
        })

    prop_ids = [p["property_id"] for p in props if p.get("property_id") is not None]

    if dry_run:
        sku_decode_first8 = [decode_sku(profile, p["sku"]) for p in products_out[:8]]
        summary = Counter(a.get("action") for a in DB_ACTIONS)
        plan = summarize_db_plan(DB_ACTIONS)

        out = json.dumps({
            "profile": profile.name,
            "listing_id": listing_id,
            "count": len(products_out),
            "readiness_state_id": rs_id,
            "sample_product": products_out[0] if products_out else None,
            "sku_decode_first8": sku_decode_first8,
            "db_plan_summary": dict(summary),
            "db_plan_by_table": plan
        }, ensure_ascii=False, indent=2)

        safe_print(out)
        return

    put_payload = {
        "products": products_out,
        "price_on_property": prop_ids,
        "quantity_on_property": [],
        "sku_on_property": prop_ids
    }

    safe_print("[INFO] PUT overwrite products: %s" % len(products_out))
    safe_print("[INFO] readiness_state_id: %s" % rs_id)
    safe_print("[INFO] price_on_property: %s" % prop_ids)
    safe_print("[INFO] sku_on_property: %s" % prop_ids)

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
