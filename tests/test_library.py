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

    def test_search_by_part_number_requires_credentials(self) -> None:
        empty_store = CredentialStore(config_dir=Path(self.temp_dir.name))
        provider = MouserProvider(empty_store)
        with self.assertRaises(ProviderNotConfiguredError):
            provider.search_by_part_number("NE555P")


class RegistryTests(unittest.TestCase):
    def test_resolve_provider_id(self) -> None:
        self.assertEqual(resolve_provider_id("Mouser"), ProviderId.MOUSER)

    def test_get_provider_instances(self) -> None:
        store = CredentialStore(config_dir=Path(tempfile.mkdtemp()))
        mouser = get_provider("mouser", credential_store=store)
        digikey = get_provider("digikey", credential_store=store)
        self.assertEqual(mouser.display_name, "Mouser")
        self.assertEqual(digikey.display_name, "DigiKey")


if __name__ == "__main__":
    unittest.main()
