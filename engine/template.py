# engine/template.py
import html
from collections import defaultdict, Counter
from typing import Any, Dict, List, Optional, Set, Tuple

from .config import DELIMS, NUM_PREFIX
from .utils import norm_tr
from .config_rules import should_force_role_from_name  # ✅ NEW

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
    if "inch" in tl and __import__("re").search(r"\d+(\.\d+)?", tl):
        return True
    if '"' in tl and __import__("re").search(r"\d+(\.\d+)?", tl):
        return True
    if __import__("re").fullmatch(r"\d+(\.\d+)?\s*us", tl):
        return True
    return False

def classify_token(tok: str, color_set_lower: Set[str], length_set_lower: Set[str]) -> str:
    t = html.unescape((tok or "").strip())
    tl = t.lower()
    tl = tl.replace("″", '"').replace("”", '"').replace("“", '"')

    for c in color_set_lower:
        if c and c in tl:
            return "color"

    if __import__("re").fullmatch(r"\d+", tl):
        return "qty"

    if tl in length_set_lower:
        return "length"
    if looks_like_length_token(tl):
        return "length"

    m = __import__("re").match(r"^\s*(\d+)\s+(.*\S)\s*$", t)
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
        m = __import__("re").match(r"^\s*(\d+)\s+(.*\S)\s*$", s)
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

        # ✅ composite hint (color + length)
        if ("color" in pname_l) and ("length" in pname_l):
            delim = find_best_delim(samples_dec) or " / "
            props.append({
                "property_id": pid,
                "property_name": pname,
                "position": pos.get(pid),
                "delim": delim,
                "components": ["color", "length"],
                "sample_values": samples_dec[:60]
            })
            continue

        # ✅ name-based force role (length/qty/color)
        forced = should_force_role_from_name(pname or "")
        if forced in ("length", "qty", "color"):
            props.append({
                "property_id": pid,
                "property_name": pname,
                "position": pos.get(pid),
                "delim": None,
                "components": [forced],
                "sample_values": samples_dec[:60]
            })
            # collect qty samples for singular/plural inference
            if forced == "qty":
                for s in samples_dec:
                    if NUM_PREFIX.match(s.strip()):
                        qty_samples_all.append(s)
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
            "sample_values": samples_dec[:60]
        })

    sing, pl = infer_qty_units(qty_samples_all)
    return {
        "properties": sorted(props, key=lambda x: (x["position"] is None, x["position"] or 999)),
        "qty_unit_singular": sing,
        "qty_unit_plural": pl,
    }