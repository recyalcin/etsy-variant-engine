from typing import Any, Dict, Optional
import html

from .utils import norm_tr

def _as_str_dict(v: Any) -> Dict[str, Any]:
    return {str(k): v[k] for k in v} if isinstance(v, dict) else {}

def apply_display_override(role: str, base_value: str, prop_id: Optional[int],
                           display_overrides: Dict[str, Dict[str, str]],
                           display_overrides_by_prop: Dict[str, Dict[str, Dict[str, str]]]) -> str:
    s = (base_value or "").strip()
    if not s:
        return ""

    pid = str(prop_id) if prop_id is not None else None
    if pid and pid in display_overrides_by_prop:
        per_prop = display_overrides_by_prop[pid]
        per_role = per_prop.get(role)
        if isinstance(per_role, dict) and s in per_role:
            return str(per_role[s]).strip()

    per_role = display_overrides.get(role)
    if isinstance(per_role, dict) and s in per_role:
        return str(per_role[s]).strip()

    return s

def build_property_value(prop: Dict[str, Any], ctx: Dict[str, str],
                         display_overrides: Dict[str, Dict[str, str]],
                         display_overrides_by_prop: Dict[str, Dict[str, Dict[str, str]]]) -> str:
    pid = int(prop.get("property_id")) if prop.get("property_id") is not None else None
    comps = prop.get("components") or []
    d = prop.get("delim")

    def val(role: str) -> str:
        if role == "color":
            base = ctx.get("color_label", "")
            return apply_display_override("color", base, pid, display_overrides, display_overrides_by_prop)
        if role == "length":
            base = ctx.get("length_label", "")
            return apply_display_override("length", base, pid, display_overrides, display_overrides_by_prop)
        if role == "qty":
            base = ctx.get("qty_label", "")
            return apply_display_override("qty", base, pid, display_overrides, display_overrides_by_prop)
        if role == "unknown" and ctx.get("length_label"):
            base = ctx.get("length_label", "")
            return apply_display_override("length", base, pid, display_overrides, display_overrides_by_prop)
        return ctx.get("color_label") or ctx.get("length_label") or ctx.get("qty_label") or ""

    if d and len(comps) >= 2:
        parts = [val(r) for r in comps]
        parts = [p for p in parts if p]
        return d.join(parts) if parts else ""
    return val(comps[0] if comps else "unknown")