"""Tests for BOM Mouser lookup helpers."""

from __future__ import annotations

import tempfile
import unittest
from unittest.mock import patch

import scripts.build_bom_cost_excel as bom_cost


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


if __name__ == "__main__":
    unittest.main()
