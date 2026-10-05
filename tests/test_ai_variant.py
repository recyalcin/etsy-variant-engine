import copy
import json
import unittest
from unittest.mock import Mock, patch

from engine.ai_variant import (
    AIAnalysisError,
    AIUnavailableError,
    apply_analysis,
    build_deterministic_analysis,
    load_saved_analysis,
    request_openai_analysis,
    resolve_variant_analysis,
    save_successful_analysis,
    validate_ai_analysis,
)


def qty_property(property_id=514):
    return {
        "property_id": property_id,
        "property_name": "Number of Birthstones",
        "components": ["qty"],
        "delim": None,
        "sample_values": ["1 Birthstone", "2 Birthstones", "3 Birthstones"],
        "all_values": ["1 Birthstone", "2 Birthstones", "3 Birthstones"],
    }


def birthstone_payload():
    return {
        "quantities": ["1 tas", "2 tas", "3 tas"],
        "pricing_by": "qty",
        "pricing": {"1 tas": 64, "2 tas": 85, "3 tas": 99},
    }


def analysis_for(property_id=514):
    return {
        "override_required": True,
        "confidence": 0.98,
        "reason": "Complete semantic match.",
        "override": {
            "component_overrides": [],
            "delim_overrides": [],
            "qty_numbers": [
                {"source": "1 tas", "number": 1},
                {"source": "2 tas", "number": 2},
                {"source": "3 tas", "number": 3},
            ],
            "display_value_overrides": [
                {
                    "property_id": property_id,
                    "component": "qty",
                    "mappings": [
                        {"source": "1 tas", "target": "1 Birthstone"},
                        {"source": "2 tas", "target": "2 Birthstones"},
                        {"source": "3 tas", "target": "3 Birthstones"},
                    ],
                }
            ],
        },
        "pricing_label_map": [
            {"source": "1 tas", "target": "1 Birthstone"},
            {"source": "2 tas", "target": "2 Birthstones"},
            {"source": "3 tas", "target": "3 Birthstones"},
        ],
    }


class AIVariantTests(unittest.TestCase):
    def test_deterministic_birthstone_mapping_is_complete_and_normalizes_prices(self):
        payload = birthstone_payload()
        props = [qty_property()]

        validated = validate_ai_analysis(build_deterministic_analysis(payload, props), payload, props)
        normalized, generated, changes = apply_analysis(payload, props, validated)

        self.assertEqual(
            generated["display_value_overrides_by_property"]["514"]["qty"],
            {
                "1 tas": "1 Birthstone",
                "2 tas": "2 Birthstones",
                "3 tas": "3 Birthstones",
            },
        )
        self.assertEqual(
            normalized["pricing"],
            {"1 Birthstone": 64.0, "2 Birthstones": 85.0, "3 Birthstones": 99.0},
        )
        self.assertEqual(len(changes), 3)

    def test_existing_etsy_pricing_labels_do_not_require_identity_map_entries(self):
        payload = birthstone_payload()
        payload["pricing"] = {
            "1 Birthstone": 64,
            "2 Birthstones": 85,
            "3 Birthstones": 99,
        }
        empty = {
            "override_required": False,
            "confidence": 1,
            "reason": "No override needed.",
            "override": {
                "component_overrides": [],
                "delim_overrides": [],
                "qty_numbers": [],
                "display_value_overrides": [],
            },
            "pricing_label_map": [],
        }

        validated = validate_ai_analysis(empty, payload, [qty_property()])
        self.assertFalse(validated["override_required"])

    def test_validation_rejects_unknown_property_and_partial_mapping(self):
        unknown = analysis_for(999)
        with self.assertRaisesRegex(AIAnalysisError, "Unknown display mapping property_id"):
            validate_ai_analysis(unknown, birthstone_payload(), [qty_property()])

        partial = analysis_for()
        partial["override"]["display_value_overrides"][0]["mappings"].pop()
        with self.assertRaisesRegex(AIAnalysisError, "incomplete"):
            validate_ai_analysis(partial, birthstone_payload(), [qty_property()])

    def test_validation_rejects_invented_and_duplicate_targets(self):
        invented = analysis_for()
        invented["override"]["display_value_overrides"][0]["mappings"][0]["target"] = "Invented"
        with self.assertRaisesRegex(AIAnalysisError, "not an unambiguous allowed value"):
            validate_ai_analysis(invented, birthstone_payload(), [qty_property()])

        duplicate = analysis_for()
        duplicate["override"]["display_value_overrides"][0]["mappings"][1]["target"] = "1 Birthstone"
        with self.assertRaisesRegex(AIAnalysisError, "Duplicate display mapping target"):
            validate_ai_analysis(duplicate, birthstone_payload(), [qty_property()])

    def test_manual_override_wins_over_ai_proposal(self):
        payload = birthstone_payload()
        payload["display_value_overrides_by_property"] = {
            "514": {"qty": {"1 tas": "1 Birthstone"}}
        }
        validated = validate_ai_analysis(analysis_for(), payload, [qty_property()])
        normalized, generated, _ = apply_analysis(payload, [qty_property()], validated)

        self.assertEqual(
            normalized["display_value_overrides_by_property"]["514"]["qty"]["1 tas"],
            "1 Birthstone",
        )
        self.assertIn("display_value_overrides_by_property", generated)

    def test_ai_service_failure_returns_fallback_state_without_mutating_payload(self):
        payload = {"pricing_by": "fixed", "pricing": 10, "quantities": []}
        props = [{
            "property_id": 700,
            "property_name": "Engraving",
            "components": ["unknown"],
            "all_values": ["No Engraving", "Backside Engraving"],
        }]
        with patch(
            "engine.ai_variant.request_openai_analysis",
            side_effect=AIUnavailableError("timeout"),
        ):
            result, state = resolve_variant_analysis(
                "shiny", payload, props, "secret", "gpt-4o-mini", mode="always"
            )

        self.assertEqual(result, payload)
        self.assertEqual(state["status"], "unavailable")
        self.assertEqual(state["reason"], "timeout")

    def test_saved_mapping_reuses_property_name_and_values_with_new_id(self):
        payload = birthstone_payload()
        original_props = [qty_property(514)]
        new_props = [qty_property(999)]
        storage = {"version": 1, "rules": []}

        def read_rules(_path):
            return copy.deepcopy(storage)

        def write_rules(_path, data):
            storage.clear()
            storage.update(copy.deepcopy(data))

        with patch("engine.ai_variant._read_rules", side_effect=read_rules), patch(
            "engine.ai_variant._write_rules", side_effect=write_rules
        ):
            save_successful_analysis("shiny", payload, original_props, analysis_for(514))
            loaded = load_saved_analysis("shiny", payload, new_props)

        self.assertIsNotNone(loaded)
        mapped = loaded["override"]["display_value_overrides"][0]
        self.assertEqual(mapped["property_id"], 999)

    def test_openai_request_uses_strict_structured_output(self):
        response = Mock(ok=True, status_code=200)
        response.json.return_value = {
            "output": [{
                "type": "message",
                "content": [{"type": "output_text", "text": json.dumps(analysis_for())}],
            }]
        }
        with patch("engine.ai_variant.requests.post", return_value=response) as post:
            result = request_openai_analysis("secret", "gpt-4o-mini", {"input": {}})

        self.assertTrue(result["override_required"])
        sent = post.call_args.kwargs["json"]
        self.assertTrue(sent["text"]["format"]["strict"])
        self.assertEqual(sent["text"]["format"]["type"], "json_schema")
        self.assertNotIn("secret", json.dumps(sent))


if __name__ == "__main__":
    unittest.main()
