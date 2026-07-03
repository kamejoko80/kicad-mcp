"""Tests for BOM Mouser lookup helpers."""

from __future__ import annotations

import tempfile
import unittest
from unittest.mock import patch

import scripts.build_bom_cost_excel_mouser as bom_cost


class BomMouserLookupTests(unittest.TestCase):
    def test_lookup_uses_mcp_only(self) -> None:
        with patch.object(bom_cost.asyncio, "run", side_effect=[True, {"Y": {"found": True}}]) as run_mock:
            result = bom_cost.lookup_mouser_prices([], bom_cost.DEFAULT_MCP_URL)
        self.assertEqual(run_mock.call_count, 2)
        self.assertEqual(result, {"Y": {"found": True}})

    def test_lookup_exits_when_mcp_unconfigured(self) -> None:
        with patch.object(bom_cost.asyncio, "run", return_value=False):
            with self.assertRaises(SystemExit):
                bom_cost.lookup_mouser_prices([], bom_cost.DEFAULT_MCP_URL)

    def test_manufacturer_variants_include_aliases(self) -> None:
        variants = bom_cost.manufacturer_variants("Murata Electronics", "TDK")
        self.assertIn("Murata", variants)
        self.assertIn("TDK Corporation", variants)

    def test_unit_price_for_order_qty_uses_mouser_break_tiers(self) -> None:
        breaks = [(1, 0.10), (10, 0.02), (100, 0.017), (2500, 0.003)]
        self.assertEqual(bom_cost.unit_price_for_order_qty(breaks, 1), 0.10)
        self.assertEqual(bom_cost.unit_price_for_order_qty(breaks, 9), 0.10)
        self.assertEqual(bom_cost.unit_price_for_order_qty(breaks, 10), 0.02)
        self.assertEqual(bom_cost.unit_price_for_order_qty(breaks, 100), 0.017)
        self.assertEqual(bom_cost.unit_price_for_order_qty(breaks, 5000), 0.003)

    def test_excel_tiered_unit_price_formula(self) -> None:
        formula = bom_cost.excel_tiered_unit_price_formula(
            "G6",
            [(1, 0.10), (100, 0.017)],
        )
        self.assertIn("INDEX", formula)
        self.assertIn("IFERROR", formula)
        self.assertIn("MATCH(G6", formula)
        self.assertIn("0.1", formula)
        self.assertIn("0.017", formula)

    def test_excel_formula_handles_order_qty_below_minimum_break(self) -> None:
        formula = bom_cost.excel_tiered_unit_price_formula("G6", [(2500, 0.05)])
        self.assertIn("IFERROR", formula)
        self.assertIn("2500", formula)

    def test_is_mouser_in_stock_uses_stock_quantity(self) -> None:
        self.assertTrue(
            bom_cost.is_mouser_in_stock({"stock_quantity": "421", "availability": "421 In Stock"})
        )
        self.assertFalse(
            bom_cost.is_mouser_in_stock(
                {"stock_quantity": "0", "availability": "Factory Lead Time"}
            )
        )

    def test_format_availability_label_normalizes_out_of_stock(self) -> None:
        label = bom_cost.format_availability_label(
            {"stock_quantity": "0", "availability": "Factory Lead Time"}
        )
        self.assertEqual(label, "Out of Stock")

    def test_normalized_price_breaks_skip_na_prices(self) -> None:
        from kicad_mcp.library.models import ComponentRecord, PriceBreak

        record = ComponentRecord(
            provider="mouser",
            distributor_part_number="TEST",
            manufacturer_part_number="TEST",
            manufacturer="Test",
            description="",
            price_breaks=[
                PriceBreak(quantity=1, price="NA"),
                PriceBreak(quantity=2500, price="$0.05"),
            ],
        )
        breaks = bom_cost.normalized_price_breaks(record)
        self.assertEqual(breaks, [(2500, 0.05)])


if __name__ == "__main__":
    unittest.main()
