import os
import re
import html
from typing import Any, List, Set

from .config import ALNUM

def dprint(*args, debug: bool = False):
    if debug:
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

def is_code_like(s: str, expected_len: int) -> bool:
    s = (s or "").strip()
    return (len(s) == expected_len) and all(ch in ALNUM for ch in s)

def ensure_list(v: Any) -> List[Any]:
    if v is None:
        return []
    if isinstance(v, list):
        return v
    if isinstance(v, (tuple, set)):
        return list(v)
    if isinstance(v, str):
        s = v.strip()
        return [s] if s else []
    return [v]

def parse_workshop_csv_list(s: Any) -> List[str]:
    if s is None:
        return []
    raw = str(s).strip()
    if not raw:
        return []
    raw = raw.replace(";", ",").replace("|", ",")
    parts = [p.strip() for p in raw.split(",")]
    out: List[str] = []
    for p in parts:
        p = re.sub(r"\s+", " ", p).strip()
        if not p:
            continue
        out.append(p)
    return out