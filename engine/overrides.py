from typing import Any, Dict, Optional


def _as_str_dict(v: Any) -> Dict[str, Any]:
    return {str(k): v[k] for k in v} if isinstance(v, dict) else {}


def apply_display_override(
    role: str,
    base_value: str,
    prop_id: Optional[Any],
    display_overrides: Dict[str, Dict[str, str]],
    display_overrides_by_prop: Dict[str, Dict[str, Dict[str, str]]],
) -> str:
    s = (base_value or "").strip()
    if not s:
        return ""

    pid_str = str(prop_id).strip() if prop_id is not None else None
    pid_int = prop_id if isinstance(prop_id, int) else None

    print(
        "[OVERRIDE][CHECK]",
        {
            "pid_str": pid_str,
            "pid_int": pid_int,
            "role": role,
            "base_value": s,
            "prop_keys": list(display_overrides_by_prop.keys()) if isinstance(display_overrides_by_prop, dict) else [],
            "global_keys": list(display_overrides.keys()) if isinstance(display_overrides, dict) else [],
        },
        flush=True,
    )

    per_prop = None

    if isinstance(display_overrides_by_prop, dict):
        if pid_str and pid_str in display_overrides_by_prop:
            per_prop = display_overrides_by_prop[pid_str]
        elif pid_int is not None and pid_int in display_overrides_by_prop:
            per_prop = display_overrides_by_prop[pid_int]

    if isinstance(per_prop, dict):
        per_role = per_prop.get(role)
        print(
            "[OVERRIDE][PROP_HIT]",
            {
                "pid_str": pid_str,
                "role": role,
                "per_role": per_role,
            },
            flush=True,
        )

        if isinstance(per_role, dict):
            # exact match
            if s in per_role:
                out = str(per_role[s]).strip()
                print(
                    "[OVERRIDE][APPLIED][PROP][EXACT]",
                    {
                        "from": s,
                        "to": out,
                    },
                    flush=True,
                )
                return out

            # normalized fallback
            s_norm = s.strip().lower()
            for k, v in per_role.items():
                if str(k).strip().lower() == s_norm:
                    out = str(v).strip()
                    print(
                        "[OVERRIDE][APPLIED][PROP][NORMALIZED]",
                        {
                            "from": s,
                            "matched_key": k,
                            "to": out,
                        },
                        flush=True,
                    )
                    return out

    per_role = display_overrides.get(role) if isinstance(display_overrides, dict) else None
    if isinstance(per_role, dict):
        if s in per_role:
            out = str(per_role[s]).strip()
            print(
                "[OVERRIDE][APPLIED][GLOBAL][EXACT]",
                {
                    "from": s,
                    "to": out,
                },
                flush=True,
            )
            return out

        s_norm = s.strip().lower()
        for k, v in per_role.items():
            if str(k).strip().lower() == s_norm:
                out = str(v).strip()
                print(
                    "[OVERRIDE][APPLIED][GLOBAL][NORMALIZED]",
                    {
                        "from": s,
                        "matched_key": k,
                        "to": out,
                    },
                    flush=True,
                )
                return out

    print(
        "[OVERRIDE][MISS]",
        {
            "pid_str": pid_str,
            "role": role,
            "base_value": s,
        },
        flush=True,
    )
    return s


def build_property_value(
    prop: Dict[str, Any],
    ctx: Dict[str, str],
    display_overrides: Dict[str, Dict[str, str]],
    display_overrides_by_prop: Dict[str, Dict[str, Dict[str, str]]],
) -> str:
    pid = str(prop.get("property_id")).strip() if prop.get("property_id") is not None else None
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