import importlib.util
import sys
import types
import unittest
from unittest.mock import Mock, patch

if importlib.util.find_spec("pymysql") is None:
    sys.modules["pymysql"] = types.ModuleType("pymysql")

import run_inventory
from engine import etsy_api
from engine.core import property_ids_for_pricing as modular_property_ids_for_pricing


THREE_VARIATION_PROPERTIES = [
    {"property_id": 513, "components": ["color"]},
    {"property_id": 514, "components": ["length"]},
    {"property_id": 516, "components": ["qty"]},
]


class ThirdVariationTests(unittest.TestCase):
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

    def test_fixed_pricing_does_not_vary_on_a_property(self):
        self.assertEqual(
            run_inventory.property_ids_for_pricing(
                THREE_VARIATION_PROPERTIES,
                "fixed",
            ),
            [],
        )


if __name__ == "__main__":
    unittest.main()
