"""Tests for BOM DigiKey lookup helpers."""

from __future__ import annotations

import unittest
from unittest.mock import patch

import scripts.build_bom_cost_excel_digikeys as bom_cost


class BomDigiKeyLookupTests(unittest.TestCase):
    def test_lookup_uses_mcp_only(self) -> None:
        with patch.object(bom_cost.asyncio, "run", side_effect=[True, {"Y": {"found": True}}]) as run_mock:
            result = bom_cost.lookup_digikey_prices([], bom_cost.DEFAULT_MCP_URL)
        self.assertEqual(run_mock.call_count, 2)
        self.assertEqual(result, {"Y": {"found": True}})

    def test_lookup_exits_when_mcp_unconfigured(self) -> None:
        with patch.object(bom_cost.asyncio, "run", return_value=False):
            with self.assertRaises(SystemExit):
                bom_cost.lookup_digikey_prices([], bom_cost.DEFAULT_MCP_URL)

    def test_unit_price_for_order_qty_uses_digikey_break_tiers(self) -> None:
        breaks = [(10000, 0.0059), (20000, 0.0053), (100000, 0.0045)]
        self.assertEqual(bom_cost.unit_price_for_order_qty(breaks, 9999), 0.0059)
        self.assertEqual(bom_cost.unit_price_for_order_qty(breaks, 10000), 0.0059)
        self.assertEqual(bom_cost.unit_price_for_order_qty(breaks, 20000), 0.0053)
        self.assertEqual(bom_cost.unit_price_for_order_qty(breaks, 100000), 0.0045)

    def test_is_digikey_in_stock_uses_stock_quantity(self) -> None:
        self.assertTrue(
            bom_cost.is_digikey_in_stock(
                {"stock_quantity": "2768005", "availability": "2768005 In Stock"}
            )
        )
        self.assertFalse(
            bom_cost.is_digikey_in_stock({"stock_quantity": "0", "availability": "Out of Stock"})
        )

    def test_format_availability_label_normalizes_out_of_stock(self) -> None:
        label = bom_cost.format_availability_label(
            {"stock_quantity": "0", "availability": "Backorder"}
        )
        self.assertEqual(label, "Out of Stock")


if __name__ == "__main__":
    unittest.main()
