"""Unit tests for component library search modules.

Author: Henry Dang
Email: phuongminh.dang@gmail.com
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from kicad_mcp.library.credentials import CredentialStore, ProviderId
from kicad_mcp.library.providers.base import ProviderNotConfiguredError
from kicad_mcp.library.providers.digikey import DigiKeyProvider
from kicad_mcp.library.providers.mouser import MouserProvider
from kicad_mcp.library.registry import get_provider, resolve_provider_id


class CredentialStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = CredentialStore(config_dir=Path(self.temp_dir.name))

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_mouser_api_key_from_environment(self) -> None:
        with patch.dict("os.environ", {"MOUSER_API_KEY": "test-key-12345678"}, clear=False):
            api_key, source = self.store.get_mouser_api_key()
        self.assertEqual(api_key, "test-key-12345678")
        self.assertEqual(source, "environment")

    def test_mouser_api_key_session_overrides_environment(self) -> None:
        with patch.dict("os.environ", {"MOUSER_API_KEY": "env-key"}, clear=False):
            self.store.set_mouser_api_key("session-key")
            api_key, source = self.store.get_mouser_api_key()
        self.assertEqual(api_key, "session-key")
        self.assertEqual(source, "session")

    def test_persist_mouser_api_key_to_file(self) -> None:
        self.store.set_mouser_api_key("persisted-key", persist=True)
        reloaded = CredentialStore(config_dir=Path(self.temp_dir.name))
        api_key, source = reloaded.get_mouser_api_key()
        self.assertEqual(api_key, "persisted-key")
        self.assertEqual(source, "file")

    def test_provider_status_masks_secret(self) -> None:
        self.store.set_mouser_api_key("abcd1234wxyz9876")
        status = self.store.get_provider_status(ProviderId.MOUSER)
        self.assertTrue(status.configured)
        self.assertEqual(status.masked_credential, "abcd...9876")

    def test_digikey_credentials_from_environment(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "DIGIKEY_CLIENT_ID": "client-id-12345678",
                "DIGIKEY_CLIENT_SECRET": "client-secret-abcdefgh",
            },
            clear=False,
        ):
            values, source = self.store.get_digikey_credentials()
        self.assertEqual(values["client_id"], "client-id-12345678")
        self.assertEqual(values["client_secret"], "client-secret-abcdefgh")
        self.assertEqual(source, "environment")

    def test_digikey_provider_status_notes(self) -> None:
        self.store.set_digikey_credentials(
            client_id="client-id-12345678",
            client_secret="client-secret-abcdefgh",
        )
        status = self.store.get_provider_status(ProviderId.DIGIKEY)
        self.assertTrue(status.configured)
        self.assertEqual(status.auth_type, "oauth2")
        self.assertEqual(status.masked_credential, "clie...5678")
        self.assertIn("Product Information V4", status.notes)


class MouserProviderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = CredentialStore(config_dir=Path(self.temp_dir.name))
        self.store.set_mouser_api_key("fake-api-key")
        self.provider = MouserProvider(self.store)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_search_by_keyword_normalizes_response(self) -> None:
        payload = {
            "Errors": [],
            "SearchResults": {
                "NumberOfResult": 1,
                "Parts": [
                    {
                        "MouserPartNumber": "595-NE555P",
                        "ManufacturerPartNumber": "NE555P",
                        "Manufacturer": "Texas Instruments",
                        "Description": "Standard Timer Single 8-Pin",
                        "Category": "Timers",
                        "DataSheetUrl": "https://example.com/ds.pdf",
                        "ProductDetailUrl": "https://example.com/product",
                        "ImagePath": "https://example.com/image.jpg",
                        "Availability": "100 In Stock",
                        "AvailabilityInStock": "100",
                        "LeadTime": "12 Weeks",
                        "LifecycleStatus": "Active",
                        "Min": "1",
                        "Mult": "1",
                        "RohsStatus": "RoHS Compliant",
                        "PriceBreaks": [
                            {"Quantity": 1, "Price": "$0.50", "Currency": "USD"},
                        ],
                    }
                ],
            },
        }

        with patch.object(MouserProvider, "_post", return_value=payload):
            result = self.provider.search_by_keyword("ne555 timer", records=5)

        self.assertEqual(result.total_results, 1)
        self.assertEqual(len(result.records), 1)
        record = result.records[0]
        self.assertEqual(record.provider, "mouser")
        self.assertEqual(record.distributor_part_number, "595-NE555P")
        self.assertEqual(record.manufacturer_part_number, "NE555P")
        self.assertEqual(record.price_breaks[0].price, "$0.50")

    def test_search_by_part_number_uses_v1_without_manufacturer(self) -> None:
        payload = {
            "Errors": [],
            "SearchResults": {
                "NumberOfResult": 1,
                "Parts": [
                    {
                        "MouserPartNumber": "603-RC0402FR-070RL",
                        "ManufacturerPartNumber": "RC0402FR-070RL",
                        "Manufacturer": "YAGEO",
                        "Description": "0 ohm resistor",
                        "PriceBreaks": [{"Quantity": 1, "Price": "$0.10", "Currency": "USD"}],
                    }
                ],
            },
        }

        with patch.object(MouserProvider, "_post", return_value=payload) as post_mock:
            result = self.provider.search_by_part_number("RC0402FR-070RL", match_mode="Exact")

        post_mock.assert_called_once()
        self.assertEqual(post_mock.call_args.args[0], "search/partnumber")
        self.assertEqual(post_mock.call_args.kwargs.get("api_version"), "v1")
        self.assertEqual(len(result.records), 1)
        self.assertEqual(result.records[0].manufacturer_part_number, "RC0402FR-070RL")

    def test_search_by_part_number_requires_credentials(self) -> None:
        empty_store = CredentialStore(config_dir=Path(self.temp_dir.name))
        provider = MouserProvider(empty_store)
        with self.assertRaises(ProviderNotConfiguredError):
            provider.search_by_part_number("NE555P")


class DigiKeyProviderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = CredentialStore(config_dir=Path(self.temp_dir.name))
        self.store.set_digikey_credentials(
            client_id="fake-client-id",
            client_secret="fake-client-secret",
        )
        self.provider = DigiKeyProvider(self.store)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_search_by_keyword_normalizes_response(self) -> None:
        payload = {
            "ProductsCount": 1,
            "Products": [
                {
                    "DigiKeyProductNumber": "296-6501-1-ND",
                    "ManufacturerProductNumber": "CRCW080510K0FKEA",
                    "ManufacturerName": "Vishay Dale",
                    "ProductDescription": "RES SMD 10K OHM 1% 1/8W 0805",
                    "DetailedDescription": "Thick Film Resistors",
                    "QuantityAvailable": 10000,
                    "StockNote": "In Stock",
                    "ManufacturerLeadWeeks": "10 Weeks",
                    "ProductStatus": "Active",
                    "MinimumOrderQuantity": 1,
                    "RohsStatus": "RoHS Compliant",
                    "PrimaryDatasheetUrl": "https://example.com/ds.pdf",
                    "ProductUrl": "https://www.digikey.com/example",
                    "PrimaryPhotoUrl": "https://example.com/photo.jpg",
                    "Category": {"Name": "Resistors"},
                    "PackageType": {"Name": "0805"},
                    "StandardPricing": [
                        {"BreakQuantity": 1, "UnitPrice": 0.1},
                        {"BreakQuantity": 100, "UnitPrice": 0.05},
                    ],
                }
            ],
        }

        with patch.object(DigiKeyProvider, "_request", return_value=payload):
            with patch.object(DigiKeyProvider, "_enrich_products_with_pricing", side_effect=lambda products: products):
                result = self.provider.search_by_keyword("CRCW080510K0FKEA", records=5)

        self.assertEqual(result.total_results, 1)
        self.assertEqual(len(result.records), 1)
        record = result.records[0]
        self.assertEqual(record.provider, "digikey")
        self.assertEqual(record.distributor_part_number, "296-6501-1-ND")
        self.assertEqual(record.manufacturer_part_number, "CRCW080510K0FKEA")
        self.assertEqual(record.price_breaks[0].price, "$0.1")

    def test_search_by_part_number_filters_exact_mpn(self) -> None:
        payload = {
            "ProductsCount": 2,
            "Products": [
                {
                    "DigiKeyProductNumber": "111-AAA-ND",
                    "ManufacturerProductNumber": "NE555P",
                    "ManufacturerName": "Texas Instruments",
                    "ProductDescription": "Timer IC",
                    "StandardPricing": [{"BreakQuantity": 1, "UnitPrice": 0.5}],
                },
                {
                    "DigiKeyProductNumber": "222-BBB-ND",
                    "ManufacturerProductNumber": "NE555P-TI",
                    "ManufacturerName": "Texas Instruments",
                    "ProductDescription": "Other timer",
                    "StandardPricing": [{"BreakQuantity": 1, "UnitPrice": 0.6}],
                },
            ],
        }

        with patch.object(DigiKeyProvider, "_request", return_value=payload):
            with patch.object(DigiKeyProvider, "_enrich_products_with_pricing", side_effect=lambda products: products):
                result = self.provider.search_by_part_number("NE555P", match_mode="Exact")

        self.assertEqual(len(result.records), 1)
        self.assertEqual(result.records[0].manufacturer_part_number, "NE555P")

    def test_fetch_access_token_caches_until_expiry(self) -> None:
        token_payload = {"access_token": "token-abc", "expires_in": 3600}

        def fake_urlopen(request, timeout=30):
            self.assertIn("/v1/oauth2/token", request.full_url)
            class FakeResponse:
                def __enter__(self):
                    return self

                def __exit__(self, exc_type, exc, tb):
                    return False

                def read(self):
                    import json as json_module

                    return json_module.dumps(token_payload).encode("utf-8")

            return FakeResponse()

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            token_one = self.provider._fetch_access_token("fake-client-id", "fake-client-secret")
            token_two = self.provider._get_access_token()[1]

        self.assertEqual(token_one, "token-abc")
        self.assertEqual(token_two, "token-abc")

    def test_search_by_part_number_requires_credentials(self) -> None:
        empty_store = CredentialStore(config_dir=Path(self.temp_dir.name))
        provider = DigiKeyProvider(empty_store)
        result = provider.search_by_part_number("NE555P")
        self.assertEqual(result.total_results, 0)
        self.assertTrue(result.errors)
        self.assertIn("not configured", result.errors[0].lower())

    def test_enrich_products_with_pricing_merges_details(self) -> None:
        base_product = {
            "ManufacturerProductNumber": "STM32F401CCU6",
            "QuantityAvailable": 680,
        }
        details = {
            "DigiKeyProductNumber": "497-STM32F401CCU6-ND",
            "ManufacturerName": "STMicroelectronics",
            "StandardPricing": [{"BreakQuantity": 1, "UnitPrice": 4.25}],
        }

        with patch.object(DigiKeyProvider, "_fetch_product_details", return_value=details):
            enriched = self.provider._enrich_products_with_pricing([base_product])

        self.assertEqual(len(enriched), 1)
        record = self.provider._normalize_product(enriched[0])
        self.assertEqual(record.distributor_part_number, "497-STM32F401CCU6-ND")
        self.assertEqual(record.manufacturer, "STMicroelectronics")
        self.assertEqual(record.price_breaks[0].price, "$4.25")


class RegistryTests(unittest.TestCase):
    def test_resolve_provider_id(self) -> None:
        self.assertEqual(resolve_provider_id("Mouser"), ProviderId.MOUSER)

    def test_get_provider_instances(self) -> None:
        store = CredentialStore(config_dir=Path(tempfile.mkdtemp()))
        mouser = get_provider("mouser", credential_store=store)
        digikey = get_provider("digikey", credential_store=store)
        lcsc = get_provider("lcsc", credential_store=store)
        self.assertEqual(mouser.display_name, "Mouser")
        self.assertEqual(digikey.display_name, "DigiKey")
        self.assertEqual(lcsc.display_name, "LCSC")


if __name__ == "__main__":
    unittest.main()
