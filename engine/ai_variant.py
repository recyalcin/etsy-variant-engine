"""Optional AI-assisted Etsy variation analysis.

The AI layer only proposes existing override fields. It never calls Etsy and it
never receives database credentials, API keys, or application source code.
"""

import copy
import hashlib
import json
import os
import re
import time
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import quote

import requests


OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
OPENAI_MODELS_URL = "https://api.openai.com/v1/models"
ALLOWED_COMPONENTS = {"color", "length", "qty", "size"}
DEFAULT_MODEL = "gpt-4o-mini"
DEFAULT_AUTO_APPLY_CONFIDENCE = 0.90
DEFAULT_MIN_CONFIDENCE = 0.70


class AIAnalysisError(ValueError):
    pass


class AIUnavailableError(RuntimeError):
    pass


def normalize_text(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").strip().casefold())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.translate(str.maketrans({"ı": "i", "ş": "s", "ğ": "g", "ç": "c", "ö": "o", "ü": "u"}))
    text = re.sub(r"\s*[-–—]\s*", "-", text)
    return re.sub(r"\s+", " ", text).strip()


def _first_integer(value: Any) -> Optional[int]:
    match = re.search(r"\d+", str(value or ""))
    return int(match.group(0)) if match else None


def _property_values(prop: Dict[str, Any]) -> List[str]:
    values = prop.get("all_values") or prop.get("sample_values") or []
    return [str(value) for value in values if str(value).strip()]


def _property_identity(prop: Dict[str, Any]) -> str:
    identity = {
        "name": normalize_text(prop.get("property_name")),
        "values": sorted(normalize_text(value) for value in _property_values(prop)),
    }
    return json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _source_values(payload: Dict[str, Any], component: str) -> List[str]:
    if component == "color":
        raw = payload.get("colors") or []
    elif component == "length":
        raw = payload.get("lengths", payload.get("lengths_inch", [])) or []
    elif component == "qty":
        raw = payload.get("quantities") or []
    elif component == "size":
        raw = payload.get("sizes") or []
        if not raw:
            single = str(payload.get("size") or "").strip()
            raw = [single] if single and single != "-" else []
    else:
        raw = []

    if isinstance(raw, dict):
        raw = list(raw.values())
    if not isinstance(raw, list):
        raw = [raw]
    return [str(value).strip() for value in raw if str(value).strip() and str(value).strip() != "-"]


def _strong_components(property_name: Any) -> Optional[List[str]]:
    name = normalize_text(property_name)
    has_color = any(token in name for token in ("color", "colour", "renk", "finish", "metal"))
    has_length = any(token in name for token in ("chain length", "necklace length", "bracelet length", "length", "uzunluk"))
    # Workshop payloads use the length axis for ring-number choices, while
    # `size` is the fixed physical width/thickness (for example 4mm).
    if "ring size" in name:
        return ["length"]
    if has_color and has_length:
        return ["color", "length"]
    if has_length:
        return ["length"]
    if has_color:
        return ["color"]
    if any(
        token in name
        for token in (
            "number of birthstone",
            "number of birthflower",
            "number of initial",
            "number of charm",
            "number of name",
            "quantity",
            "count",
        )
    ):
        return ["qty"]
    if "size" in name and "length" not in name:
        return ["size"]
    return None


def _canonical_lookup(values: Iterable[str]) -> Dict[str, List[str]]:
    result: Dict[str, List[str]] = {}
    for value in values:
        result.setdefault(normalize_text(value), []).append(str(value))
    return result


def _canonical_value(value: Any, allowed: Iterable[str], label: str) -> str:
    lookup = _canonical_lookup(allowed)
    matches = lookup.get(normalize_text(value), [])
    if len(matches) != 1:
        raise AIAnalysisError("%s is not an unambiguous allowed value: %r" % (label, value))
    return matches[0]


def _canonical_mapping_pair(
    source_value: Any,
    target_value: Any,
    sources: Iterable[str],
    targets: Iterable[str],
    label: str,
) -> Tuple[str, str]:
    """Canonicalize source->target, safely correcting a fully reversed AI pair."""
    sources_list = list(sources)
    targets_list = list(targets)
    try:
        return (
            _canonical_value(source_value, sources_list, "%s source" % label),
            _canonical_value(target_value, targets_list, "%s target" % label),
        )
    except AIAnalysisError as original_error:
        try:
            return (
                _canonical_value(target_value, sources_list, "%s source" % label),
                _canonical_value(source_value, targets_list, "%s target" % label),
            )
        except AIAnalysisError:
            raise original_error


def deterministic_value_mapping(sources: List[str], targets: List[str]) -> Dict[str, str]:
    """Map complete lists by normalized equality or unique numeric meaning."""
    if not sources or not targets:
        return {}

    target_lookup = _canonical_lookup(targets)
    target_numbers: Dict[int, List[str]] = {}
    for target in targets:
        number = _first_integer(target)
        if number is not None:
            target_numbers.setdefault(number, []).append(target)

    mapping: Dict[str, str] = {}
    used_targets = set()
    for source in sources:
        exact = target_lookup.get(normalize_text(source), [])
        target = exact[0] if len(exact) == 1 else None
        if target is None:
            number = _first_integer(source)
            numeric = target_numbers.get(number, []) if number is not None else []
            target = numeric[0] if len(numeric) == 1 else None
        if target is None or normalize_text(target) in used_targets:
            return {}
        mapping[source] = target
        used_targets.add(normalize_text(target))

    return mapping if len(mapping) == len(sources) else {}


def build_deterministic_analysis(
    payload: Dict[str, Any],
    props: List[Dict[str, Any]],
) -> Dict[str, Any]:
    component_overrides = []
    effective_components: Dict[int, List[str]] = {}

    for prop in props:
        property_id = int(prop["property_id"])
        current = [str(value).lower() for value in (prop.get("components") or [])]
        strong = _strong_components(prop.get("property_name"))
        if strong and current != strong:
            component_overrides.append({"property_id": property_id, "components": strong})
            effective_components[property_id] = strong
        else:
            effective_components[property_id] = current

    qty_props = [prop for prop in props if "qty" in effective_components.get(int(prop["property_id"]), [])]
    display_overrides = []
    qty_numbers = []
    pricing_label_map = []

    if len(qty_props) == 1:
        qty_prop = qty_props[0]
        sources = _source_values(payload, "qty")
        targets = _property_values(qty_prop)
        mapping = deterministic_value_mapping(sources, targets)
        if mapping:
            if any(normalize_text(source) != normalize_text(target) for source, target in mapping.items()):
                display_overrides.append(
                    {
                        "property_id": int(qty_prop["property_id"]),
                        "component": "qty",
                        "mappings": [
                            {"source": source, "target": target}
                            for source, target in mapping.items()
                        ],
                    }
                )
            pricing_label_map = [
                {"source": source, "target": target}
                for source, target in mapping.items()
            ]
            numbers = [_first_integer(source) for source in sources]
            if sources and all(number is not None for number in numbers):
                qty_numbers = [
                    {"source": source, "number": int(number)}
                    for source, number in zip(sources, numbers)
                ]

    override_required = bool(component_overrides or display_overrides or qty_numbers)
    return {
        "override_required": override_required,
        "confidence": 1.0,
        "reason": "Conservative property-name and unique numeric matching rules were applied." if override_required else "No deterministic override was needed.",
        "override": {
            "component_overrides": component_overrides,
            "delim_overrides": [],
            "qty_numbers": qty_numbers,
            "display_value_overrides": display_overrides,
        },
        "pricing_label_map": pricing_label_map,
    }


def _effective_components(props: List[Dict[str, Any]], payload: Dict[str, Any]) -> Dict[int, List[str]]:
    configured = payload.get("component_overrides") or {}
    result = {}
    for prop in props:
        property_id = int(prop["property_id"])
        override = configured.get(str(property_id), configured.get(property_id)) if isinstance(configured, dict) else None
        components = override if isinstance(override, list) and override else prop.get("components") or []
        result[property_id] = [str(component).strip().lower() for component in components]
    return result


def _existing_display_target(
    payload: Dict[str, Any],
    property_id: int,
    component: str,
    source: str,
) -> Optional[str]:
    roots = []
    per_property = payload.get("display_value_overrides_by_property") or {}
    if isinstance(per_property, dict):
        prop_root = per_property.get(str(property_id), per_property.get(property_id))
        if isinstance(prop_root, dict) and isinstance(prop_root.get(component), dict):
            roots.append(prop_root[component])
    global_root = payload.get("display_value_overrides") or {}
    if isinstance(global_root, dict) and isinstance(global_root.get(component), dict):
        roots.append(global_root[component])
    for mapping in roots:
        for raw, target in mapping.items():
            if normalize_text(raw) == normalize_text(source):
                return str(target)
    return None


def analysis_needed(payload: Dict[str, Any], props: List[Dict[str, Any]]) -> Tuple[bool, str]:
    components = _effective_components(props, payload)
    unresolved = [
        prop for prop in props
        if not components.get(int(prop["property_id"]))
        or "unknown" in components.get(int(prop["property_id"]), [])
    ]
    if unresolved:
        return True, "unresolved template properties: %s" % ", ".join(
            "%s %s" % (prop.get("property_id"), prop.get("property_name"))
            for prop in unresolved
        )

    quantities = _source_values(payload, "qty")
    if not quantities:
        return False, "deterministic analyzer sufficient"

    qty_props = [prop for prop in props if "qty" in components.get(int(prop["property_id"]), [])]
    if not qty_props:
        return False, "quantity input has no Etsy variation property; AI cannot create a property ID"
    if len(qty_props) != 1:
        return True, "quantity input does not map to exactly one Etsy property"

    qty_prop = qty_props[0]
    target_lookup = _canonical_lookup(_property_values(qty_prop))
    for source in quantities:
        target = _existing_display_target(payload, int(qty_prop["property_id"]), "qty", source) or source
        if len(target_lookup.get(normalize_text(target), [])) != 1:
            return True, "quantity display mapping is incomplete"
    return False, "deterministic analyzer sufficient"


def _schema() -> Dict[str, Any]:
    component_enum = sorted(ALLOWED_COMPONENTS)
    mapping_item = {
        "type": "object",
        "additionalProperties": False,
        "properties": {"source": {"type": "string"}, "target": {"type": "string"}},
        "required": ["source", "target"],
    }
    return {
        "type": "json_schema",
        "name": "etsy_variant_analysis",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "override_required": {"type": "boolean"},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                "reason": {"type": "string"},
                "override": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "component_overrides": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "additionalProperties": False,
                                "properties": {
                                    "property_id": {"type": "integer"},
                                    "components": {"type": "array", "items": {"type": "string", "enum": component_enum}},
                                },
                                "required": ["property_id", "components"],
                            },
                        },
                        "delim_overrides": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "additionalProperties": False,
                                "properties": {"property_id": {"type": "integer"}, "delimiter": {"type": "string"}},
                                "required": ["property_id", "delimiter"],
                            },
                        },
                        "qty_numbers": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "additionalProperties": False,
                                "properties": {"source": {"type": "string"}, "number": {"type": "integer"}},
                                "required": ["source", "number"],
                            },
                        },
                        "display_value_overrides": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "additionalProperties": False,
                                "properties": {
                                    "property_id": {"type": "integer"},
                                    "component": {"type": "string", "enum": component_enum},
                                    "mappings": {"type": "array", "items": mapping_item},
                                },
                                "required": ["property_id", "component", "mappings"],
                            },
                        },
                    },
                    "required": ["component_overrides", "delim_overrides", "qty_numbers", "display_value_overrides"],
                },
                "pricing_label_map": {"type": "array", "items": mapping_item},
            },
            "required": ["override_required", "confidence", "reason", "override", "pricing_label_map"],
        },
    }


def _prompt() -> str:
    return (
        "Analyze Etsy variation semantics and return only the required structured result. "
        "Allowed components are color, length, qty, and size. Never invent component names. "
        "Use component overrides only when detected components are wrong or unknown. "
        "Map every relevant workshop source value to an exact Etsy target value from the supplied property. "
        "In every mapping, source is the workshop input and target is the Etsy template value; never reverse them. "
        "Do not invent Etsy values and do not map by array position alone. Avoid duplicate targets. "
        "For qty, provide complete qty_numbers. Semantic options without literal numbers must use unique 1..N ordinals "
        "in workshop input order; never assign the same qty number to multiple source values. "
        "pricing_label_map must completely map qty pricing labels when display labels change. "
        "Do not emit unnecessary delimiter or component overrides."
    )


def build_request_context(profile: str, payload: Dict[str, Any], props: List[Dict[str, Any]]) -> Dict[str, Any]:
    input_payload = {
        key: copy.deepcopy(payload.get(key))
        for key in ("type", "size", "sizes", "colors", "lengths", "lengths_inch", "quantities", "space", "start", "pricing_by", "pricing")
        if key in payload
    }
    effective_components = _effective_components(props, payload)
    delimiters = payload.get("delim_overrides") or {}
    if not isinstance(delimiters, dict):
        delimiters = {}
    return {
        "profile": profile,
        "input": input_payload,
        "template_properties": [
            {
                "property_id": int(prop["property_id"]),
                "property_name": str(prop.get("property_name") or ""),
                "detected_components": effective_components.get(int(prop["property_id"]), []),
                "delimiter": delimiters.get(
                    str(prop["property_id"]),
                    delimiters.get(int(prop["property_id"]), prop.get("delim")),
                ),
                "values": _property_values(prop),
            }
            for prop in props
        ],
    }


def _response_text(data: Dict[str, Any]) -> str:
    direct = data.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct
    for item in data.get("output") or []:
        if item.get("type") != "message":
            continue
        for content in item.get("content") or []:
            if content.get("type") == "output_text" and isinstance(content.get("text"), str):
                return content["text"]
            if content.get("type") == "refusal":
                raise AIUnavailableError("OpenAI refused the variant analysis request")
    raise AIUnavailableError("OpenAI response did not contain structured output text")


def request_openai_analysis(
    api_key: str,
    model: str,
    context: Dict[str, Any],
    timeout_seconds: int = 45,
) -> Dict[str, Any]:
    if not api_key:
        raise AIUnavailableError("OpenAI API key is not configured")
    body = {
        "model": model,
        "instructions": _prompt(),
        "input": json.dumps(context, ensure_ascii=False),
        "text": {"format": _schema()},
        "max_output_tokens": 4000,
    }
    try:
        response = requests.post(
            OPENAI_RESPONSES_URL,
            headers={"Authorization": "Bearer %s" % api_key, "Content-Type": "application/json"},
            json=body,
            timeout=timeout_seconds,
        )
    except requests.RequestException as exc:
        raise AIUnavailableError("OpenAI request failed: %s" % exc.__class__.__name__)
    if not response.ok:
        detail = response.text[:500].replace(api_key, "[REDACTED]")
        raise AIUnavailableError("OpenAI HTTP %s: %s" % (response.status_code, detail))
    try:
        return json.loads(_response_text(response.json()))
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise AIUnavailableError("OpenAI returned invalid structured JSON: %s" % exc)


def test_openai_connection(api_key: str, model: str, timeout_seconds: int = 15) -> Dict[str, Any]:
    if not api_key:
        raise AIUnavailableError("OpenAI API key is not configured")
    safe_model = str(model or DEFAULT_MODEL).strip()
    try:
        response = requests.get(
            "%s/%s" % (OPENAI_MODELS_URL, quote(safe_model, safe="")),
            headers={"Authorization": "Bearer %s" % api_key},
            timeout=timeout_seconds,
        )
    except requests.RequestException as exc:
        raise AIUnavailableError("OpenAI connection failed: %s" % exc.__class__.__name__)
    if not response.ok:
        detail = response.text[:500].replace(api_key, "[REDACTED]")
        raise AIUnavailableError("OpenAI HTTP %s: %s" % (response.status_code, detail))
    try:
        data = response.json()
    except (TypeError, ValueError) as exc:
        raise AIUnavailableError("OpenAI returned an invalid model response: %s" % exc.__class__.__name__)
    return {"ok": True, "model": data.get("id", safe_model)}


def validate_ai_analysis(
    analysis: Dict[str, Any],
    payload: Dict[str, Any],
    props: List[Dict[str, Any]],
) -> Dict[str, Any]:
    if not isinstance(analysis, dict):
        raise AIAnalysisError("AI analysis must be an object")
    property_map = {int(prop["property_id"]): prop for prop in props}
    override = analysis.get("override")
    if not isinstance(override, dict):
        raise AIAnalysisError("AI override must be an object")
    if not isinstance(analysis.get("override_required"), bool):
        raise AIAnalysisError("AI override_required must be a boolean")
    confidence = float(analysis.get("confidence", -1))
    if confidence < 0 or confidence > 1:
        raise AIAnalysisError("AI confidence must be between 0 and 1")

    result = {
        "override_required": bool(analysis.get("override_required")),
        "confidence": confidence,
        "reason": str(analysis.get("reason") or ""),
        "override": {"component_overrides": [], "delim_overrides": [], "qty_numbers": [], "display_value_overrides": []},
        "pricing_label_map": [],
    }

    component_property_ids = set()
    for item in override.get("component_overrides") or []:
        property_id = int(item.get("property_id"))
        if property_id not in property_map:
            raise AIAnalysisError("Unknown Etsy property_id: %s" % property_id)
        if property_id in component_property_ids:
            raise AIAnalysisError("Duplicate component override for property %s" % property_id)
        component_property_ids.add(property_id)
        components = [str(component).strip().lower() for component in item.get("components") or []]
        if not components or any(component not in ALLOWED_COMPONENTS for component in components):
            raise AIAnalysisError("Unsupported component override for property %s" % property_id)
        if len(components) != len(set(components)):
            raise AIAnalysisError("Duplicate components for property %s" % property_id)
        result["override"]["component_overrides"].append({"property_id": property_id, "components": components})

    delimiter_property_ids = set()
    for item in override.get("delim_overrides") or []:
        property_id = int(item.get("property_id"))
        if property_id not in property_map:
            raise AIAnalysisError("Unknown delimiter property_id: %s" % property_id)
        if property_id in delimiter_property_ids:
            raise AIAnalysisError("Duplicate delimiter override for property %s" % property_id)
        delimiter_property_ids.add(property_id)
        delimiter = str(item.get("delimiter") or "")
        if not delimiter or len(delimiter) > 5:
            raise AIAnalysisError("Invalid delimiter for property %s" % property_id)
        result["override"]["delim_overrides"].append({"property_id": property_id, "delimiter": delimiter})

    component_by_property = _effective_components(props, payload)
    for item in result["override"]["component_overrides"]:
        component_by_property[item["property_id"]] = item["components"]

    quantities = _source_values(payload, "qty")
    quantity_lookup = _canonical_lookup(quantities)
    qty_number_sources = set()
    for item in override.get("qty_numbers") or []:
        source = _canonical_value(item.get("source"), quantities, "qty_numbers source")
        number = int(item.get("number"))
        if number <= 0:
            raise AIAnalysisError("qty_numbers values must be positive")
        literal = _first_integer(source)
        if literal is not None and literal != number:
            raise AIAnalysisError("qty number conflicts with source label: %r" % source)
        normalized_source = normalize_text(source)
        if normalized_source in qty_number_sources:
            raise AIAnalysisError("Duplicate qty_numbers source: %r" % source)
        qty_number_sources.add(normalized_source)
        result["override"]["qty_numbers"].append({"source": source, "number": number})

    display_mapping_keys = set()
    for item in override.get("display_value_overrides") or []:
        property_id = int(item.get("property_id"))
        prop = property_map.get(property_id)
        if prop is None:
            raise AIAnalysisError("Unknown display mapping property_id: %s" % property_id)
        component = str(item.get("component") or "").strip().lower()
        current_components = component_by_property.get(property_id, [])
        if component not in ALLOWED_COMPONENTS:
            raise AIAnalysisError(
                "Display mapping component %r is not valid for property %s" % (component, property_id)
            )
        if component not in current_components:
            # The model can correctly map every value for an unresolved Etsy
            # property yet omit the matching component_override. Completing
            # that omission is safe only while the property is still unknown;
            # a resolved but contradictory component remains an error.
            if not current_components or "unknown" in current_components:
                component_by_property[property_id] = [component]
                if property_id not in component_property_ids:
                    result["override"]["component_overrides"].append(
                        {"property_id": property_id, "components": [component]}
                    )
                    component_property_ids.add(property_id)
            else:
                raise AIAnalysisError(
                    "Display mapping component %r conflicts with property %s components %r"
                    % (component, property_id, current_components)
                )
        display_key = (property_id, component)
        if display_key in display_mapping_keys:
            raise AIAnalysisError("Duplicate display mapping for property %s component %s" % display_key)
        display_mapping_keys.add(display_key)
        sources = _source_values(payload, component)
        targets = _property_values(prop)
        mappings = []
        seen_sources = set()
        seen_targets = set()
        for mapping in item.get("mappings") or []:
            source, target = _canonical_mapping_pair(
                mapping.get("source"),
                mapping.get("target"),
                sources,
                targets,
                "display mapping",
            )
            source_norm = normalize_text(source)
            target_norm = normalize_text(target)
            if source_norm in seen_sources:
                raise AIAnalysisError("Duplicate display mapping source: %r" % source)
            if target_norm in seen_targets:
                raise AIAnalysisError("Duplicate display mapping target: %r" % target)
            seen_sources.add(source_norm)
            seen_targets.add(target_norm)
            mappings.append({"source": source, "target": target})
        if sources and seen_sources != set(_canonical_lookup(sources)):
            raise AIAnalysisError("Display mapping is incomplete for property %s" % property_id)
        result["override"]["display_value_overrides"].append(
            {"property_id": property_id, "component": component, "mappings": mappings}
        )

    introduces_qty = (
        any("qty" in item["components"] for item in result["override"]["component_overrides"])
        or any(item["component"] == "qty" for item in result["override"]["display_value_overrides"])
    )
    if quantities and (introduces_qty or result["override"]["qty_numbers"]):
        proposed_numbers = {
            normalize_text(item["source"]): int(item["number"])
            for item in result["override"]["qty_numbers"]
        }
        canonical_numbers: Dict[str, int] = {}
        used_numbers = set()

        # Literal numbers are semantic and must be preserved first.
        for source in quantities:
            literal = _first_integer(source)
            if literal is None:
                continue
            if literal in used_numbers:
                raise AIAnalysisError("Duplicate literal quantity meaning: %r" % literal)
            canonical_numbers[source] = literal
            used_numbers.add(literal)

        # Non-numeric semantic choices use stable, unique input-order ordinals.
        next_ordinal = 1
        for source in quantities:
            if source in canonical_numbers:
                continue
            proposed = proposed_numbers.get(normalize_text(source))
            if proposed is not None and proposed > 0 and proposed not in used_numbers:
                number = proposed
            else:
                while next_ordinal in used_numbers:
                    next_ordinal += 1
                number = next_ordinal
            canonical_numbers[source] = number
            used_numbers.add(number)

        result["override"]["qty_numbers"] = [
            {"source": source, "number": canonical_numbers[source]}
            for source in quantities
        ]
        qty_number_sources = {normalize_text(source) for source in quantities}

    pricing = payload.get("pricing")
    pricing_sources = list(pricing.keys()) if isinstance(pricing, dict) else []
    pricing_seen = set()
    if payload.get("pricing_by") == "qty":
        allowed_targets = [
            value
            for prop in props
            if "qty" in component_by_property.get(int(prop["property_id"]), [])
            for value in _property_values(prop)
        ]
    else:
        allowed_targets = [value for prop in props for value in _property_values(prop)]
    pricing_targets_seen = set()
    for item in analysis.get("pricing_label_map") or []:
        source, target = _canonical_mapping_pair(
            item.get("source"),
            item.get("target"),
            pricing_sources,
            allowed_targets,
            "pricing",
        )
        source_norm = normalize_text(source)
        target_norm = normalize_text(target)
        if source_norm in pricing_seen:
            raise AIAnalysisError("Duplicate pricing source: %r" % source)
        if target_norm in pricing_targets_seen:
            raise AIAnalysisError("Duplicate pricing target: %r" % target)
        pricing_seen.add(source_norm)
        pricing_targets_seen.add(target_norm)
        result["pricing_label_map"].append({"source": source, "target": target})

    has_qty_property = any("qty" in components for components in component_by_property.values())
    if payload.get("pricing_by") == "qty" and pricing_sources and has_qty_property:
        display_qty_map = {
            normalize_text(mapping["source"]): mapping["target"]
            for item in result["override"]["display_value_overrides"]
            if item["component"] == "qty"
            for mapping in item["mappings"]
        }
        explicit_pricing_map = {normalize_text(item["source"]): item["target"] for item in result["pricing_label_map"]}
        allowed_qty_targets = [
            value
            for prop in props
            if "qty" in component_by_property.get(int(prop["property_id"]), [])
            for value in _property_values(prop)
        ]
        allowed_qty_lookup = _canonical_lookup(allowed_qty_targets)
        for source in pricing_sources:
            source_norm = normalize_text(source)
            target = explicit_pricing_map.get(source_norm) or display_qty_map.get(source_norm)
            if target is None and len(allowed_qty_lookup.get(source_norm, [])) == 1:
                target = allowed_qty_lookup[source_norm][0]
            if target is None:
                raise AIAnalysisError("Pricing mapping is incomplete for %r" % source)
            if source_norm not in explicit_pricing_map:
                result["pricing_label_map"].append({"source": source, "target": target})

    introduces_nonnumeric_qty = (
        bool(quantities)
        and any(_first_integer(source) is None for source in quantities)
        and introduces_qty
    )
    if introduces_nonnumeric_qty and qty_number_sources != set(quantity_lookup):
        raise AIAnalysisError("qty_numbers must cover every non-numeric quantity option")

    has_override_content = any(result["override"][key] for key in result["override"])
    if result["override_required"] != bool(has_override_content):
        raise AIAnalysisError("override_required does not match override content")
    return result


def analysis_to_override(analysis: Dict[str, Any]) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    override = analysis.get("override") or {}
    component_overrides = {
        str(item["property_id"]): list(item["components"])
        for item in override.get("component_overrides") or []
    }
    if component_overrides:
        result["component_overrides"] = component_overrides
    delim_overrides = {
        str(item["property_id"]): item["delimiter"]
        for item in override.get("delim_overrides") or []
    }
    if delim_overrides:
        result["delim_overrides"] = delim_overrides
    qty_numbers = {
        item["source"]: int(item["number"])
        for item in override.get("qty_numbers") or []
    }
    if qty_numbers:
        result["qty_numbers"] = qty_numbers
    display_by_property: Dict[str, Dict[str, Dict[str, str]]] = {}
    for item in override.get("display_value_overrides") or []:
        property_id = str(item["property_id"])
        component = item["component"]
        display_by_property.setdefault(property_id, {}).setdefault(component, {})
        for mapping in item["mappings"]:
            display_by_property[property_id][component][mapping["source"]] = mapping["target"]
    if display_by_property:
        result["display_value_overrides_by_property"] = display_by_property
    return result


def _deep_merge_missing(existing: Dict[str, Any], proposed: Dict[str, Any]) -> Dict[str, Any]:
    result = copy.deepcopy(existing)
    for key, value in proposed.items():
        if key not in result:
            result[key] = copy.deepcopy(value)
        elif isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge_missing(result[key], value)
    return result


def _pricing_map_from_payload(payload: Dict[str, Any], props: List[Dict[str, Any]]) -> Dict[str, str]:
    components = _effective_components(props, payload)
    result: Dict[str, str] = {}
    per_property = payload.get("display_value_overrides_by_property") or {}
    if isinstance(per_property, dict):
        for prop in props:
            property_id = int(prop["property_id"])
            if "qty" not in components.get(property_id, []):
                continue
            prop_root = per_property.get(str(property_id), per_property.get(property_id))
            if isinstance(prop_root, dict) and isinstance(prop_root.get("qty"), dict):
                result.update({str(key): str(value) for key, value in prop_root["qty"].items()})
    global_root = payload.get("display_value_overrides") or {}
    if isinstance(global_root, dict) and isinstance(global_root.get("qty"), dict):
        for key, value in global_root["qty"].items():
            result.setdefault(str(key), str(value))
    return result


def normalize_pricing(
    payload: Dict[str, Any],
    label_map: Dict[str, str],
) -> Tuple[Dict[str, Any], List[Dict[str, str]]]:
    result = copy.deepcopy(payload)
    pricing = result.get("pricing")
    if not isinstance(pricing, dict) or not label_map:
        return result, []

    mapping_lookup = _canonical_lookup(label_map.keys())
    normalized_pricing: Dict[str, float] = {}
    normalizations: List[Dict[str, str]] = []
    for raw_key, price in pricing.items():
        source_key = None
        exact = mapping_lookup.get(normalize_text(raw_key), [])
        if len(exact) == 1:
            source_key = exact[0]
        else:
            candidates = [
                (SequenceMatcher(None, normalize_text(raw_key), normalize_text(candidate)).ratio(), candidate)
                for candidate in label_map
            ]
            candidates.sort(reverse=True)
            if candidates and candidates[0][0] >= 0.96 and (len(candidates) == 1 or candidates[0][0] > candidates[1][0]):
                source_key = candidates[0][1]
        target_key = label_map.get(source_key, str(raw_key)) if source_key is not None else str(raw_key)
        if target_key in normalized_pricing and float(normalized_pricing[target_key]) != float(price):
            raise AIAnalysisError("Pricing normalization collision for %r" % target_key)
        normalized_pricing[target_key] = float(price)
        if str(raw_key) != target_key:
            normalizations.append({"source": str(raw_key), "target": target_key})
    result["pricing"] = normalized_pricing
    return result, normalizations


def apply_analysis(
    payload: Dict[str, Any],
    props: List[Dict[str, Any]],
    analysis: Dict[str, Any],
) -> Tuple[Dict[str, Any], Dict[str, Any], List[Dict[str, str]]]:
    proposed_override = analysis_to_override(analysis)
    result = _deep_merge_missing(payload, proposed_override)
    label_map = _pricing_map_from_payload(result, props)
    label_map.update({item["source"]: item["target"] for item in analysis.get("pricing_label_map") or []})
    result, normalizations = normalize_pricing(result, label_map)
    return result, proposed_override, normalizations


def _context_signature(profile: str, payload: Dict[str, Any], props: List[Dict[str, Any]]) -> str:
    context = {
        "profile": profile,
        "quantities": sorted(normalize_text(value) for value in _source_values(payload, "qty")),
        "pricing_by": normalize_text(payload.get("pricing_by")),
        "properties": sorted(_property_identity(prop) for prop in props),
    }
    raw = json.dumps(context, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _rule_path() -> Path:
    configured = os.getenv("VARIANT_MAPPING_RULES_PATH")
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parent.parent / "inputs" / "variant_mapping_rules.json"


def _read_rules(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {"version": 1, "rules": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("rules"), list):
            return data
    except Exception:
        pass
    return {"version": 1, "rules": []}


def load_saved_analysis(
    profile: str,
    payload: Dict[str, Any],
    props: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    path = _rule_path()
    data = _read_rules(path)
    signature = _context_signature(profile, payload, props)
    current_by_identity = {_property_identity(prop): int(prop["property_id"]) for prop in props}
    for rule in data.get("rules") or []:
        if rule.get("signature") != signature:
            continue
        old_identities = rule.get("property_identities") or {}
        id_map = {}
        for old_id, identity in old_identities.items():
            current_id = current_by_identity.get(identity)
            if current_id is None:
                id_map = {}
                break
            id_map[int(old_id)] = current_id
        if not id_map and old_identities:
            continue
        analysis = copy.deepcopy(rule.get("analysis"))
        if not isinstance(analysis, dict):
            continue
        for key in ("component_overrides", "delim_overrides", "display_value_overrides"):
            for item in (analysis.get("override") or {}).get(key) or []:
                item["property_id"] = id_map.get(int(item["property_id"]), int(item["property_id"]))
        rule["usage_count"] = int(rule.get("usage_count") or 0) + 1
        rule["last_used_at"] = int(time.time())
        try:
            _write_rules(path, data)
        except Exception:
            pass
        return analysis
    return None


def _write_rules(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def save_successful_analysis(
    profile: str,
    payload: Dict[str, Any],
    props: List[Dict[str, Any]],
    analysis: Dict[str, Any],
) -> None:
    path = _rule_path()
    data = _read_rules(path)
    signature = _context_signature(profile, payload, props)
    record = {
        "signature": signature,
        "profile": profile,
        "property_identities": {str(prop["property_id"]): _property_identity(prop) for prop in props},
        "analysis": copy.deepcopy(analysis),
        "confidence": float(analysis.get("confidence") or 0),
        "source": "ai",
        "usage_count": 1,
        "last_used_at": int(time.time()),
        "created_at": int(time.time()),
    }
    rules = [rule for rule in data.get("rules") or [] if rule.get("signature") != signature]
    rules.append(record)
    data["rules"] = rules[-500:]
    _write_rules(path, data)


def resolve_variant_analysis(
    profile: str,
    payload: Dict[str, Any],
    props: List[Dict[str, Any]],
    api_key: str,
    model: str,
    mode: str = "necessary",
    auto_apply_confidence: float = DEFAULT_AUTO_APPLY_CONFIDENCE,
    min_confidence: float = DEFAULT_MIN_CONFIDENCE,
    timeout_seconds: int = 45,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    working = copy.deepcopy(payload)
    state: Dict[str, Any] = {
        "enabled": True,
        "provider": "openai",
        "model": model,
        "mode": mode,
        "status": "started",
        "requested": False,
        "applied": False,
        "confidence": None,
        "reason": "",
        "generated_override": {},
        "pricing_normalizations": [],
    }

    deterministic = validate_ai_analysis(build_deterministic_analysis(working, props), working, props)
    if deterministic["override_required"]:
        working, generated, normalizations = apply_analysis(working, props, deterministic)
        state["generated_override"] = _deep_merge_missing(state["generated_override"], generated)
        state["pricing_normalizations"].extend(normalizations)
        state["status"] = "deterministic_applied"
        state["applied"] = True

    saved = load_saved_analysis(profile, working, props)
    if saved is not None:
        try:
            saved = validate_ai_analysis(saved, working, props)
            working, generated, normalizations = apply_analysis(working, props, saved)
            state["generated_override"] = _deep_merge_missing(state["generated_override"], generated)
            state["pricing_normalizations"].extend(normalizations)
            state["status"] = "saved_mapping_applied"
            state["applied"] = True
            state["confidence"] = saved["confidence"]
            state["reason"] = saved["reason"]
        except AIAnalysisError as exc:
            state["saved_mapping_error"] = str(exc)

    needs_ai, reason = analysis_needed(working, props)
    state["reason"] = state["reason"] or reason
    if mode != "always" and not needs_ai:
        if state["status"] == "started":
            state["status"] = (
                "skipped_not_applicable"
                if "AI cannot create a property ID" in reason
                else "skipped_deterministic_sufficient"
            )
        return working, state

    if not api_key:
        state["status"] = "unavailable"
        state["reason"] = "OpenAI API key is not configured; existing engine workflow continues."
        return working, state

    state["requested"] = True
    context = build_request_context(profile, working, props)
    try:
        raw_analysis = request_openai_analysis(api_key, model, context, timeout_seconds=timeout_seconds)
    except AIUnavailableError as exc:
        state["status"] = "unavailable"
        state["reason"] = str(exc)
        return working, state
    try:
        analysis = validate_ai_analysis(raw_analysis, working, props)
    except (AIAnalysisError, KeyError, TypeError, ValueError) as exc:
        state["status"] = "invalid_response"
        state["reason"] = str(exc)
        return working, state

    state["confidence"] = analysis["confidence"]
    state["reason"] = analysis["reason"]
    if analysis["confidence"] < min_confidence:
        state["status"] = "low_confidence"
        return working, state
    if analysis["confidence"] < auto_apply_confidence:
        state["status"] = "confirmation_required"
        state["proposed_analysis"] = analysis
        state["proposed_override"] = analysis_to_override(analysis)
        return working, state

    working, generated, normalizations = apply_analysis(working, props, analysis)
    state["generated_override"] = _deep_merge_missing(state["generated_override"], generated)
    state["pricing_normalizations"].extend(normalizations)
    state["status"] = "ai_applied"
    state["applied"] = True
    state["_save_candidate"] = analysis
    return working, state
