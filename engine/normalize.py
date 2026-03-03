# engine/normalize.py
import re
import html
from typing import Any, Dict, List, Optional, Tuple

from .utils import norm_tr
from .config import NUM_PREFIX

# ---------- length formatting (ring size aware) ----------

def _samples_look_like_ring_sizes(sample_values: List[str]) -> bool:
    if not sample_values:
        return False
    cnt = 0
    for v in sample_values[:30]:
        s = html.unescape(str(v)).strip()
        if re.fullmatch(r"\d+(\s+1/2)?", s) or re.fullmatch(r"\d+(\.\d+)?", s):
            cnt += 1
    return cnt >= 2


def _detect_half_style(sample_values: List[str]) -> str:
    sv = [html.unescape(str(x)).strip() for x in (sample_values or [])]
    if any(re.search(r"\b1/2\b", s) for s in sv):
        return "fraction"
    if any(re.search(r"\d+\.5\b", s) for s in sv):
        return "decimal"
    return "fraction"


def _parse_us_number(raw: str) -> Tuple[str, bool]:
    s0 = norm_tr(raw or "")
    had_us = (" us" in s0) or s0.endswith("us") or ("us" in s0.split())
    s = s0.replace(" us", " ").replace("us", " ").strip()
    s = re.sub(r"\s+", " ", s)
    return s, had_us


def _to_fraction_half(x: str) -> str:
    if re.fullmatch(r"\d+\.5", x):
        return x.replace(".5", " 1/2")
    if re.fullmatch(r"\d+\s+1/2", x):
        return x
    if re.fullmatch(r"\d+\.0", x):
        return x[:-2]
    if re.fullmatch(r"\d+", x):
        return x
    return x


def _to_decimal_half(x: str) -> str:
    if re.fullmatch(r"\d+\s+1/2", x):
        return x.replace(" 1/2", ".5")
    if re.fullmatch(r"\d+\.5", x):
        return x
    if re.fullmatch(r"\d+\.0", x):
        return x[:-2]
    if re.fullmatch(r"\d+", x):
        return x
    return x


def normalize_length_for_property(raw_input: str, prop: Dict[str, Any]) -> str:
    s = html.unescape((raw_input or "").strip())
    s = s.replace("″", '"').replace("”", '"').replace("“", '"')
    samples_raw = [html.unescape(str(x)) for x in (prop.get("sample_values") or [])]
    samples_norm = [norm_tr(x) for x in samples_raw]

    # ring-size style
    if _samples_look_like_ring_sizes(samples_raw):
        half_style = _detect_half_style(samples_raw)
        num, had_us = _parse_us_number(s)
        out = _to_fraction_half(num) if half_style == "fraction" else _to_decimal_half(num)
        return (out + " US") if had_us else out

    # explicit US style in template
    if any((" us" in x) for x in samples_norm):
        num = s.replace('"', "").strip()
        if num.lower().endswith("us"):
            num = num[:-2].strip()
        return "%s US" % num

    # inch style in template
    if any(("inch" in x) for x in samples_norm):
        num = s.replace('"', "").replace("inches", "").replace("inch", "").strip()
        return "%s inches" % num

    # quote style in template
    if any('"' in x for x in samples_raw):
        num = s.replace('"', "").strip()
        return '%s"' % num

    return s


# ---------- qty formatting (ENUM templates, incl "Birthstone") ----------

def _extract_qty_unit_from_samples(samples: List[str]) -> Tuple[Optional[str], Optional[str]]:
    """
    If samples look like:
      - "1 Birthstone", "2 Birthstones" => ("Birthstone","Birthstones")
      - "1 Pair", "2 Pairs" => ("Pair","Pairs")
    Returns (singular, plural) or (None,None).
    """
    sing = None
    pl = None
    for s in samples[:60]:
        s = html.unescape(str(s)).strip()
        m = re.fullmatch(r"(\d+)\s+(.+)", s)
        if not m:
            continue
        try:
            n = int(m.group(1))
        except Exception:
            continue
        tail = m.group(2).strip()
        if not tail:
            continue
        if n == 1 and sing is None:
            sing = tail
        if n >= 2 and pl is None:
            pl = tail
    return sing, pl


def normalize_qty_for_property(raw_qty: str, prop: Optional[Dict[str, Any]]) -> str:
    """
    ENUM qty display:
      - if samples are numbers => "1 Taki" -> "1"
      - if samples are "<n> <unit>" => "1 Taki" -> "1 <unit(s)>"
      - otherwise keep as-is (still overrideable)
    """
    s = html.unescape((raw_qty or "")).strip()
    if not s or s == "-":
        return ""

    samples = [html.unescape(str(x)).strip() for x in ((prop or {}).get("sample_values") or [])][:60]
    if not samples:
        m = re.search(r"(\d+)", s)
        return m.group(1) if m else s

    # numbers-only?
    num_only = 0
    total = 0
    for v in samples:
        if not v:
            continue
        total += 1
        if re.fullmatch(r"\d+", v):
            num_only += 1
    if total >= 2 and num_only >= max(2, total // 2):
        m = re.search(r"(\d+)", s)
        return m.group(1) if m else s

    # "<n> <unit>" style?
    sing, pl = _extract_qty_unit_from_samples(samples)
    m = re.search(r"(\d+)", s)
    if m and (sing or pl):
        n = int(m.group(1))
        unit = sing if (n == 1 and sing) else (pl or sing or "")
        unit = unit.strip()
        return f"{n} {unit}".strip() if unit else str(n)

    return s


# ---------- qty label builder for COUNT templates ----------

def build_qty_label(n: int, tpl: Dict[str, Any]) -> str:
    sing = tpl.get("qty_unit_singular") or "Option"
    pl = tpl.get("qty_unit_plural") or (sing + "s")
    return "%d %s" % (n, (sing if n == 1 else pl))