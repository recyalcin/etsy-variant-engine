import importlib.util
import sys
import types
import unittest
from unittest.mock import Mock, patch

if importlib.util.find_spec("pymysql") is None:
    sys.modules["pymysql"] = types.ModuleType("pymysql")

import run_inventory
from engine import etsy_api
from engine.config import PROFILES as ENGINE_PROFILES
from engine.core import normalize_on_property_fields as modular_normalize_on_property_fields
from engine.core import property_ids_for_pricing as modular_property_ids_for_pricing
from profiles.shiny import ShinyProfile


THREE_VARIATION_PROPERTIES = [
    {"property_id": 513, "components": ["color"]},
    {"property_id": 514, "components": ["length"]},
    {"property_id": 516, "components": ["qty"]},
]


def products_with_property_ids(*property_ids):
    return [
        {
            "property_values": [
                {"property_id": property_id}
                for property_id in property_ids
            ]
        }
    ]


class ThirdVariationTests(unittest.TestCase):
    def setUp(self):
        run_inventory.DB_ACTIONS.clear()

    def test_dry_run_reserves_distinct_codes_for_new_values(self):
        with patch.object(run_inventory, "load_table", return_value=[]), patch.object(
            run_inventory, "table_has_column", return_value=False
        ), patch.object(run_inventory, "fetchall_dict", return_value=[]), patch.object(
            run_inventory, "build_insert_sql", return_value=("INSERT", ())
        ), patch.object(run_inventory, "execute"):
            first = run_inventory.upsert_by_desc_schema("i_qty", "Aquarius", 2)
            second = run_inventory.upsert_by_desc_schema("i_qty", "Aries", 2)
            first_again = run_inventory.upsert_by_desc_schema("i_qty", "Aquarius", 2)

        self.assertEqual(first, "00")
        self.assertEqual(second, "01")
        self.assertEqual(first_again, "00")

    def test_ring_size_property_uses_length_axis_not_fixed_mm_size(self):
        inventory = {
            "products": [{
                "property_values": [
                    {
                        "property_id": 514,
                        "property_name": "Ring Size",
                        "values": ["3"],
                    }
                ]
            }]
        }
        payload = {
            "size": "4mm",
            "lengths_inch": ["3", "3.5", "4"],
        }

        result = run_inventory.analyze_template(inventory, set(), {"3", "3.5", "4"}, payload)

        self.assertEqual(result["properties"][0]["components"], ["length"])
        self.assertEqual(
            run_inventory.normalize_length_for_property("3.5", result["properties"][0]),
            "3.5",
        )

    def test_multiple_quantities_require_an_etsy_quantity_property(self):
        payload = {"quantities": ["garnet", "amethyst", "aqua"]}
        props = [
            {"property_id": 513, "property_name": "Color", "components": ["color"]},
            {"property_id": 514, "property_name": "Chain Length", "components": ["length"]},
        ]

        with self.assertRaisesRegex(
            ValueError,
            "no quantity/stone variation property.*3 Quantity options",
        ):
            run_inventory.validate_quantity_variation_supported(payload, props)

    def test_single_quantity_can_remain_a_fixed_sku_component(self):
        payload = {"quantities": ["garnet"]}
        props = [
            {"property_id": 513, "property_name": "Color", "components": ["color"]},
            {"property_id": 514, "property_name": "Chain Length", "components": ["length"]},
        ]

        run_inventory.validate_quantity_variation_supported(payload, props)

    def test_template_qty_units_do_not_leak_from_length_property(self):
        inventory = {
            "products": [
                {
                    "property_values": [
                        {"property_id": 513, "property_name": "Chain Length", "values": ["14 inches"]},
                        {"property_id": 516, "property_name": "Number of Fishes", "values": ["3 Fishes"]},
                    ]
                },
                {
                    "property_values": [
                        {"property_id": 513, "property_name": "Chain Length", "values": ["16 inches"]},
                        {"property_id": 516, "property_name": "Number of Fishes", "values": ["5 Fishes"]},
                    ]
                },
            ]
        }

        result = run_inventory.analyze_template(inventory, set(), set(), {})

        self.assertEqual(result["qty_unit_plural"], "Fishes")
        qty_prop = next(item for item in result["properties"] if item["property_id"] == 516)
        self.assertEqual(qty_prop["components"], ["qty"])
        self.assertEqual(qty_prop["all_values"], ["3 Fishes", "5 Fishes"])

    def test_delimiter_override_is_applied_during_analysis(self):
        inventory = {
            "products": [{
                "property_values": [{
                    "property_id": 513,
                    "property_name": "Color / Length",
                    "values": ["Gold / 14 inches"],
                }]
            }]
        }
        payload = {"delim_overrides": {"513": " - "}}

        result = run_inventory.analyze_template(inventory, {"gold"}, set(), payload)

        self.assertEqual(result["properties"][0]["delim"], " - ")

    def test_global_display_override_is_resolved(self):
        payload = {"display_value_overrides": {"qty": {"1 tas": "1 Birthstone"}}}
        self.assertEqual(
            run_inventory.resolve_display_override(
                payload, role="qty", property_id=514, raw_value="1 TAS"
            ),
            "1 Birthstone",
        )

    def test_preflight_rejects_value_not_present_in_etsy_property(self):
        profile = run_inventory.PROFILES["shiny"]
        sku_length = sum(profile.sku_lengths()[part] for part in profile.sku_order)
        products = [{
            "sku": "0" * sku_length,
            "property_values": [{"property_id": 514, "values": ["Invented"]}],
            "offerings": [{"price": 10, "quantity": 1}],
        }]
        props = [{
            "property_id": 514,
            "components": ["qty"],
            "sample_values": ["No Engraving", "Backside Engraving"],
            "all_values": ["No Engraving", "Backside Engraving"],
        }]

        with self.assertRaisesRegex(ValueError, "not present in Etsy property"):
            run_inventory.preflight_validate_products(products, props, 1, profile)

    def test_preflight_allows_new_value_for_length_property(self):
        profile = run_inventory.PROFILES["shiny"]
        sku_length = sum(profile.sku_lengths()[part] for part in profile.sku_order)
        products = [{
            "sku": "0" * sku_length,
            "property_values": [{"property_id": 514, "values": ["14 inches"]}],
            "offerings": [{"price": 10, "quantity": 1, "readiness_state_id": 1}],
        }]
        props = [{
            "property_id": 514,
            "components": ["length"],
            "sample_values": ["16 inches", "18 inches"],
            "all_values": ["16 inches", "18 inches"],
        }]

        result = run_inventory.preflight_validate_products(products, props, 1, profile)

        self.assertTrue(result["ok"])

    def test_preflight_rejects_length_value_when_component_is_unknown(self):
        profile = run_inventory.PROFILES["shiny"]
        sku_length = sum(profile.sku_lengths()[part] for part in profile.sku_order)
        products = [{
            "sku": "0" * sku_length,
            "property_values": [{"property_id": 514, "values": ["14 inches"]}],
            "offerings": [{"price": 10, "quantity": 1, "readiness_state_id": 1}],
        }]
        props = [{
            "property_id": 514,
            "components": ["unknown"],
            "sample_values": ["16 inches", "18 inches"],
            "all_values": ["16 inches", "18 inches"],
        }]

        with self.assertRaisesRegex(ValueError, "not present in Etsy property"):
            run_inventory.preflight_validate_products(products, props, 1, profile)

    def test_unresolved_template_property_stops_before_product_generation(self):
        props = [{
            "property_id": 514,
            "property_name": "Zodiac Sign",
            "components": ["unknown"],
        }]
        ai_state = {
            "enabled": True,
            "status": "invalid_response",
            "reason": "Invalid AI mapping",
        }

        with self.assertRaisesRegex(
            ValueError,
            "Unresolved Etsy variation property: 514 \\(Zodiac Sign\\)",
        ):
            run_inventory.validate_template_properties_resolved(props, ai_state)

    def test_preflight_allows_new_combined_property_value(self):
        profile = run_inventory.PROFILES["shiny"]
        sku_length = sum(profile.sku_lengths()[part] for part in profile.sku_order)
        products = [{
            "sku": "0" * sku_length,
            "property_values": [{"property_id": 513, "values": ["Gold / 14 inches"]}],
            "offerings": [{"price": 10, "quantity": 1, "readiness_state_id": 1}],
        }]
        props = [{
            "property_id": 513,
            "components": ["color", "length"],
            "sample_values": ["Gold / 16 inches"],
            "all_values": ["Gold / 16 inches"],
        }]

        result = run_inventory.preflight_validate_products(products, props, 1, profile)

        self.assertTrue(result["ok"])

    def test_empty_shiny_size_uses_two_character_sku_placeholder(self):
        profile = run_inventory.PROFILES["shiny"]

        result = run_inventory.resolve_size_code(
            profile,
            "-",
            [{"code": "0", "desc": "-"}],
        )

        self.assertEqual(result, "00")
        self.assertEqual(len(result), profile.size_len)

    def test_legacy_one_character_size_is_padded_only_for_shiny(self):
        rows = [{"code": "A", "desc": "6mm"}]

        shiny_code = run_inventory.resolve_size_code(
            run_inventory.PROFILES["shiny"], "6mm", rows
        )
        belkymood_code = run_inventory.resolve_size_code(
            run_inventory.PROFILES["belkymood"], "6mm", rows
        )

        self.assertEqual(shiny_code, "0A")
        self.assertEqual(belkymood_code, "A")

    def test_existing_two_character_shiny_size_is_unchanged(self):
        result = run_inventory.resolve_size_code(
            run_inventory.PROFILES["shiny"],
            "8mm",
            [{"code": "A3", "desc": "8mm"}],
        )

        self.assertEqual(result, "A3")

    def test_active_runner_enables_three_variations_on_put(self):
        response = Mock(ok=True)
        response.json.return_value = {"listing_id": 123}

        with patch.object(run_inventory, "etsy_request", return_value=response) as request:
            result = run_inventory.put_inventory_overwrite(123, {"products": []})

        self.assertEqual(result, {"listing_id": 123})
        request.assert_called_once_with(
            "PUT",
            "https://api.etsy.com/v3/application/listings/123/inventory",
            params={"max_variations_supported": 3},
            json={"products": []},
            timeout=140,
        )

    def test_modular_client_enables_three_variations_on_put(self):
        response = Mock(ok=True)
        response.json.return_value = {"listing_id": 123}

        with patch.object(etsy_api, "etsy_request", return_value=response) as request:
            result = etsy_api.put_inventory_overwrite(123, {"products": []})

        self.assertEqual(result, {"listing_id": 123})
        request.assert_called_once_with(
            "PUT",
            "https://api.etsy.com/v3/application/listings/123/inventory",
            params={"max_variations_supported": 3},
            json={"products": []},
            timeout=140,
        )

    def test_qty_pricing_uses_only_qty_property(self):
        self.assertEqual(
            run_inventory.property_ids_for_pricing(
                THREE_VARIATION_PROPERTIES,
                "qty",
            ),
            [516],
        )
        self.assertEqual(
            modular_property_ids_for_pricing(
                THREE_VARIATION_PROPERTIES,
                "qty",
            ),
            [516],
        )

    def test_two_variation_fields_align_when_sku_uses_all_properties(self):
        expected = {
            "price_on_property": [513, 514],
            "quantity_on_property": [],
            "sku_on_property": [513, 514],
        }
        products = products_with_property_ids(514, 513)

        self.assertEqual(
            run_inventory.normalize_on_property_fields(
                products,
                price_on_property=[514],
                quantity_on_property=[],
                sku_on_property=[513, 514],
            ),
            expected,
        )
        self.assertEqual(
            modular_normalize_on_property_fields(
                products,
                price_on_property=[514],
                quantity_on_property=[],
                sku_on_property=[513, 514],
            ),
            expected,
        )

    def test_three_variation_fields_align_when_sku_uses_all_properties(self):
        expected = {
            "price_on_property": [513, 514, 516],
            "quantity_on_property": [],
            "sku_on_property": [513, 514, 516],
        }
        products = products_with_property_ids(516, 513, 514)

        self.assertEqual(
            run_inventory.normalize_on_property_fields(
                products,
                price_on_property=[516],
                quantity_on_property=[],
                sku_on_property=[513, 514, 516],
            ),
            expected,
        )
        self.assertEqual(
            modular_normalize_on_property_fields(
                products,
                price_on_property=[516],
                quantity_on_property=[],
                sku_on_property=[513, 514, 516],
            ),
            expected,
        )

    def test_non_full_fields_remain_specific(self):
        expected = {
            "price_on_property": [516],
            "quantity_on_property": [],
            "sku_on_property": [513],
        }
        self.assertEqual(
            run_inventory.normalize_on_property_fields(
                products_with_property_ids(513, 514, 516),
                price_on_property=[516],
                quantity_on_property=[],
                sku_on_property=[513],
            ),
            expected,
        )

    def test_single_variation_fields_remain_valid(self):
        expected = {
            "price_on_property": [513],
            "quantity_on_property": [],
            "sku_on_property": [513],
        }
        self.assertEqual(
            run_inventory.normalize_on_property_fields(
                products_with_property_ids(513),
                price_on_property=[513],
                quantity_on_property=[],
                sku_on_property=[513],
            ),
            expected,
        )

    def test_fixed_pricing_does_not_vary_on_a_property(self):
        self.assertEqual(
            run_inventory.property_ids_for_pricing(
                THREE_VARIATION_PROPERTIES,
                "fixed",
            ),
            [],
        )

    def test_shiny_size_codes_are_two_characters_everywhere(self):
        self.assertEqual(run_inventory.PROFILES["shiny"].size_len, 2)
        self.assertEqual(ENGINE_PROFILES["shiny"].size_len, 2)
        self.assertEqual(ShinyProfile.code_len["size"], 2)
        self.assertEqual(ShinyProfile.tables["i_size"]["code_len"], 2)


if __name__ == "__main__":
    unittest.main()
