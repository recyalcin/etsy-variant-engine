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
            "sample_values": ["No Engraving", "Backside Engraving"],
            "all_values": ["No Engraving", "Backside Engraving"],
        }]

        with self.assertRaisesRegex(ValueError, "not present in Etsy property"):
            run_inventory.preflight_validate_products(products, props, 1, profile)

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
