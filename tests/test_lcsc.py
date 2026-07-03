"""Unit tests for the LCSC wmsc.lcsc.com provider."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from kicad_mcp.library.credentials import CredentialStore, ProviderId
from kicad_mcp.library.providers.lcsc import LCSCProvider
from kicad_mcp.library.registry import get_provider, resolve_provider_id


def _sample_product(**overrides: object) -> dict:
    product = {
        "productCode": "C46749",
        "productModel": "NE555P",
        "brandNameEn": "TI",
        "encapStandard": "DIP-8",
        "productIntroEn": "DIP-8 Programmable Timers and Oscillators RoHS",
        "stockNumber": 9070,
        "minBuyNumber": 5,
        "split": 5,
        "isEnvironment": True,
        "pdfUrl": "https://wmsc.lcsc.com/wmsc/upload/file/pdf/v2/lcsc/example.pdf",
        "productPriceList": [
            {"ladder": 5, "currencyPrice": 0.3352, "usdPrice": 0.3352, "currencySymbol": "$"},
            {"ladder": 50, "currencyPrice": 0.2613, "usdPrice": 0.2613, "currencySymbol": "$"},
        ],
    }
    product.update(overrides)
    return product


class LCSCProviderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = CredentialStore(config_dir=Path(self.temp_dir.name))
        self.provider = LCSCProvider(self.store)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_credential_status_always_configured(self) -> None:
        status = self.provider.credential_status()
        self.assertTrue(status.configured)
        self.assertEqual(status.auth_type, "none")
        self.assertEqual(status.source, "public")
        self.assertIn("wmsc.lcsc.com", status.notes.lower())

    def test_search_by_lcsc_code_uses_product_detail(self) -> None:
        detail = _sample_product()

        with patch.object(self.provider._session, "product_detail", return_value=detail) as detail_mock:
            with patch.object(self.provider._session, "search") as search_mock:
                result = self.provider.search_by_part_number("C46749", match_mode="Exact")

        detail_mock.assert_called_once_with("C46749")
        search_mock.assert_not_called()
        self.assertEqual(result.total_results, 1)
        record = result.records[0]
        self.assertEqual(record.distributor_part_number, "C46749")
        self.assertEqual(record.manufacturer_part_number, "NE555P")
        self.assertEqual(record.manufacturer, "TI")
        self.assertEqual(record.stock_quantity, "9070")
        self.assertEqual(record.rohs_status, "RoHS Compliant")
        self.assertEqual(record.price_breaks[0].quantity, 5)
        self.assertEqual(record.price_breaks[0].price, "$0.3352")
        self.assertEqual(record.price_breaks[1].quantity, 50)

    def test_search_by_keyword_uses_global_search(self) -> None:
        search_result = {
            "scene": "FULL_MATCH",
            "totalCount": 15,
            "exactMatchResult": [_sample_product()],
        }

        with patch.object(self.provider._session, "search", return_value=search_result) as search_mock:
            result = self.provider.search_by_keyword("NE555P", records=5)

        search_mock.assert_called_once_with("NE555P")
        self.assertEqual(result.total_results, 1)
        self.assertEqual(result.records[0].distributor_part_number, "C46749")

    def test_search_redirect_fetches_product_detail(self) -> None:
        search_result = {
            "scene": "REDIRECT_PRODUCT_DETAIL",
            "tipProductDetailUrlVO": {"productCode": "C46749"},
        }
        detail = _sample_product()

        with patch.object(self.provider._session, "search", return_value=search_result):
            with patch.object(self.provider._session, "product_detail", return_value=detail) as detail_mock:
                result = self.provider.search_by_part_number("C46749", match_mode="Exact")

        detail_mock.assert_called_once_with("C46749")
        self.assertEqual(len(result.records), 1)

    def test_search_by_keyword_empty_query(self) -> None:
        result = self.provider.search_by_keyword("   ")
        self.assertEqual(result.total_results, 0)
        self.assertTrue(result.errors)

    def test_search_by_keyword_empty_results(self) -> None:
        with patch.object(self.provider._session, "search", return_value={"exactMatchResult": []}):
            result = self.provider.search_by_keyword("nonexistent-part-xyz")

        self.assertEqual(result.total_results, 0)
        self.assertEqual(result.records, [])
        self.assertFalse(result.errors)

    def test_search_by_keyword_in_stock_filter(self) -> None:
        search_result = {
            "exactMatchResult": [
                _sample_product(productCode="C1", stockNumber=10),
                _sample_product(productCode="C2", stockNumber=0),
            ]
        }

        with patch.object(self.provider._session, "search", return_value=search_result):
            result = self.provider.search_by_keyword("part", search_options="InStock")

        self.assertEqual(result.total_results, 1)
        self.assertEqual(result.records[0].distributor_part_number, "C1")

    def test_search_by_part_number_exact_match_filters_results(self) -> None:
        search_result = {
            "productSearchResultVO": {
                "productList": [
                    _sample_product(productCode="C111", productModel="NE555P"),
                    _sample_product(productCode="C222", productModel="NE555P-TI"),
                ]
            }
        }

        with patch.object(self.provider._session, "search", return_value=search_result):
            result = self.provider.search_by_part_number("NE555P", match_mode="Exact")

        self.assertEqual(len(result.records), 1)
        self.assertEqual(result.records[0].manufacturer_part_number, "NE555P")

    def test_search_by_part_number_multiple_parts(self) -> None:
        with patch.object(
            self.provider._session,
            "product_detail",
            side_effect=[
                _sample_product(productCode="C1", productModel="NE555P"),
                _sample_product(productCode="C2", productModel="LM358"),
            ],
        ):
            result = self.provider.search_by_part_number("C1|C2", match_mode="Exact")

        self.assertEqual(result.total_results, 2)
        part_numbers = {record.manufacturer_part_number for record in result.records}
        self.assertEqual(part_numbers, {"NE555P", "LM358"})

    def test_search_warns_when_api_returns_partial_matches(self) -> None:
        search_result = {
            "totalCount": 51,
            "exactMatchResult": [_sample_product()],
        }

        with patch.object(self.provider._session, "search", return_value=search_result):
            result = self.provider.search_by_keyword("NE555", records=10)

        self.assertTrue(result.warnings)
        self.assertIn("51", result.warnings[0])

    def test_search_handles_http_error(self) -> None:
        with patch.object(
            self.provider._session,
            "search",
            side_effect=RuntimeError("LCSC API HTTP 503: unavailable"),
        ):
            with self.assertRaises(RuntimeError):
                self.provider.search_by_keyword("capacitor")

    def test_product_detail_handles_missing_part(self) -> None:
        with patch.object(self.provider._session, "product_detail", return_value=None):
            result = self.provider.search_by_part_number("C99999999", match_mode="Exact")

        self.assertEqual(result.total_results, 0)
        self.assertEqual(result.records, [])


class LCSCRegistryTests(unittest.TestCase):
    def test_resolve_provider_id(self) -> None:
        self.assertEqual(resolve_provider_id("LCSC"), ProviderId.LCSC)

    def test_get_provider_instance(self) -> None:
        store = CredentialStore(config_dir=Path(tempfile.mkdtemp()))
        provider = get_provider("lcsc", credential_store=store)
        self.assertEqual(provider.display_name, "LCSC")


if __name__ == "__main__":
    unittest.main()
