# engine/config_rules.py
import re
from typing import Any, Dict, List, Optional

# Basit keyword hint listeleri: property_name ve sample üzerinden role bias
ROLE_HINTS: Dict[str, List[str]] = {
    "qty": [
        "qty", "quantity", "number", "count", "single", "pair", "piece", "pieces",
        "option", "options", "paws", "paw", "names", "nameplates",
        "tek", "çift", "pati",
    ],
    "length": [
        "length", "bracelet length", "necklace length", "chain length", "size",
        "inch", "inches", "cm", "mm", "us", "uk", "eu",
    ],
    "color": [
        "color", "finish", "metal", "renk", "kaplama",
    ],
}

# Değer normalize: scale length gibi numeric scale için "14 inches" -> "14"
_NUM_RE = re.compile(r"(\d+(?:\.\d+)?)")

def normalize_numeric_value(s: str) -> str:
    s = (s or "").strip()
    if not s:
        return s
    m = _NUM_RE.search(s.replace("″", '"').replace("”", '"').replace("“", '"'))
    return m.group(1) if m else s

def contains_any(hay: str, needles: List[str]) -> bool:
    h = (hay or "").lower()
    return any(n.lower() in h for n in needles if n)

def sample_contains_any(samples: List[str], needles: List[str]) -> bool:
    for s in samples or []:
        if contains_any(s, needles):
            return True
    return False

def sample_matches_any(samples: List[str], regex_list: List[str]) -> bool:
    for s in samples or []:
        for rx in regex_list or []:
            try:
                if re.search(rx, s, flags=re.IGNORECASE):
                    return True
            except Exception:
                continue
    return False

# Otomatik override kuralları
# - match: property_name / sample / delim ile eşleşir
# - role_map: role bazında mapping (qty/color/length)
# - normalize: "numeric" ise input ne olursa olsun sayıya indirger (scale için)
AUTO_VALUE_RULES: List[Dict[str, Any]] = [
    {
        "id": "single_pair_tr",
        "match": {
            "property_name_any": ["single", "pair", "pieces", "single / pair"],
            "sample_any": ["Single", "Pair", "Pieces"],
        },
        "role_map": {
            "qty": {
                "Tek": "Single (1 Piece)",
                "Çift": "Pair (2 Pieces)",
                "Single": "Single (1 Piece)",
                "Pair": "Pair (2 Pieces)",
                "1": "Single (1 Piece)",
                "2": "Pair (2 Pieces)",
            }
        },
    },
    {
        "id": "pati_to_paw",
        "match": {
            "property_name_any": ["paw", "paws", "pati"],
            "delim_any": [" - "],
        },
        "role_map": {
            "qty": {
                "1 Pati": "1 Paw",
                "2 Pati": "2 Paws",
                "3 Pati": "3 Paws",
                "4 Pati": "4 Paws",
                "5 Pati": "5 Paws",
                "6 Pati": "6 Paws",
                "7 Pati": "7 Paws",
            }
        },
    },
    {
        "id": "scale_length_numeric",
        "match": {
            "property_name_any": ["length", "bracelet length", "necklace length"],
            "sample_regex_any": [r"\b\d+(\.\d+)?\b", r'inch', r'"'],
        },
        # mapping değil: normalize
        "normalize": "numeric",
        "role": "length",
    },
]

def build_auto_display_overrides_for_property(prop: Dict[str, Any]) -> Dict[str, Dict[str, str]]:
    """
    Return: { role: {input_value: output_value, ...}, ... }
    """
    pname = (prop.get("property_name") or "")
    samples = prop.get("sample_values") or []
    delim = prop.get("delim") or ""

    out: Dict[str, Dict[str, str]] = {}

    for rule in AUTO_VALUE_RULES:
        m = rule.get("match") or {}

        ok = True
        if m.get("property_name_any"):
            ok = ok and contains_any(pname, m["property_name_any"])
        if m.get("sample_any"):
            ok = ok and sample_contains_any(samples, m["sample_any"])
        if m.get("sample_regex_any"):
            ok = ok and sample_matches_any(samples, m["sample_regex_any"])
        if m.get("delim_any"):
            ok = ok and any(d == delim for d in m["delim_any"])

        if not ok:
            continue

        # normalize rule (scale length numeric)
        if rule.get("normalize") == "numeric" and rule.get("role") == "length":
            # Bu kural map üretmez; normalize işlemi core içinde "length value" üretirken uygulanır.
            # Yine de "length" role'u işaretlemek için boş dict koyabiliriz.
            out.setdefault("length", {})
            continue

        role_map = rule.get("role_map") or {}
        for role, mp in role_map.items():
            mp = mp or {}
            if role not in out:
                out[role] = {}
            # merge (rule order)
            for k, v in mp.items():
                out[role].setdefault(str(k), str(v))

    return out

def should_force_role_from_name(property_name: str) -> Optional[str]:
    """
    property_name’e göre tek role baskınsa döndür.
    """
    pn = (property_name or "").lower()
    # length > qty > color öncelik
    if contains_any(pn, ["length", "bracelet length", "necklace length", "chain length", "ring size"]):
        return "length"
    if contains_any(pn, ["single", "pair", "pieces", "number of", "qty", "quantity", "count"]):
        return "qty"
    if contains_any(pn, ["color", "finish", "metal"]):
        return "color"
    return None