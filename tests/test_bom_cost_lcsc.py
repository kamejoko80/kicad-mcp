"""Tests for BOM LCSC lookup helpers."""

from __future__ import annotations

import unittest
from unittest.mock import patch

import scripts.build_bom_cost_excel_lcsc as bom_cost


class BomLCSCLookupTests(unittest.TestCase):
    def test_lookup_uses_mcp_only(self) -> None:
        with patch.object(bom_cost.asyncio, "run", side_effect=[True, {"Y": {"found": True}}]) as run_mock:
            result = bom_cost.lookup_lcsc_prices([], bom_cost.DEFAULT_MCP_URL)
        self.assertEqual(run_mock.call_count, 2)
        self.assertEqual(result, {"Y": {"found": True}})

    def test_lookup_exits_when_mcp_unavailable(self) -> None:
        with patch.object(bom_cost.asyncio, "run", return_value=False):
            with self.assertRaises(SystemExit):
                bom_cost.lookup_lcsc_prices([], bom_cost.DEFAULT_MCP_URL)

    def test_manufacturer_variants_include_aliases(self) -> None:
        variants = bom_cost.manufacturer_variants("Murata Electronics", "TDK")
        self.assertIn("Murata", variants)
        self.assertIn("TDK Corporation", variants)

    def test_unit_price_for_order_qty_uses_lcsc_break_tiers(self) -> None:
        breaks = [(1, 2.12), (10, 1.82), (100, 1.32), (1000, 1.20)]
        self.assertEqual(bom_cost.unit_price_for_order_qty(breaks, 1), 2.12)
        self.assertEqual(bom_cost.unit_price_for_order_qty(breaks, 9), 2.12)
        self.assertEqual(bom_cost.unit_price_for_order_qty(breaks, 10), 1.82)
        self.assertEqual(bom_cost.unit_price_for_order_qty(breaks, 100), 1.32)
        self.assertEqual(bom_cost.unit_price_for_order_qty(breaks, 5000), 1.20)

    def test_excel_tiered_unit_price_formula(self) -> None:
        formula = bom_cost.excel_tiered_unit_price_formula(
            "G6",
            [(1, 2.12), (100, 1.32)],
        )
        self.assertIn("INDEX", formula)
        self.assertIn("IFERROR", formula)
        self.assertIn("MATCH(G6", formula)
        self.assertIn("2.12", formula)
        self.assertIn("1.32", formula)

    def test_excel_formula_handles_order_qty_below_minimum_break(self) -> None:
        formula = bom_cost.excel_tiered_unit_price_formula("G6", [(5, 0.3352)])
        self.assertIn("IFERROR", formula)
        self.assertIn("5", formula)

    def test_is_lcsc_in_stock_uses_stock_quantity(self) -> None:
        self.assertTrue(
            bom_cost.is_lcsc_in_stock({"stock_quantity": "248", "availability": "248 In Stock"})
        )
        self.assertFalse(
            bom_cost.is_lcsc_in_stock({"stock_quantity": "0", "availability": "Out of Stock"})
        )

    def test_normalized_price_breaks_skip_na_prices(self) -> None:
        from kicad_mcp.library.models import ComponentRecord, PriceBreak

        record = ComponentRecord(
            provider="lcsc",
            distributor_part_number="C81002",
            manufacturer_part_number="STM32F042F4P6",
            manufacturer="ST",
            description="",
            price_breaks=[
                PriceBreak(quantity=1, price="NA"),
                PriceBreak(quantity=100, price="$1.32"),
            ],
        )
        breaks = bom_cost.normalized_price_breaks(record)
        self.assertEqual(breaks, [(100, 1.32)])


if __name__ == "__main__":
    unittest.main()
