from typing import Dict
from .config import Profile

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
        out[seg] = sku[idx : idx + n]
        idx += n

    out["pretty"] = " ".join(["%s=%s" % (k, out[k]) for k in profile.sku_order])
    return out