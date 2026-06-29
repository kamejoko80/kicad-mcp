"""Unit tests for SamacSys ECAD library integration.

Author: Henry Dang
Email: phuongminh.dang@gmail.com
"""

from __future__ import annotations

import io
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from kicad_mcp.library.credentials import CredentialStore, ProviderId
from kicad_mcp.library.ecad.samacsys import SamacSysClient, SamacSysLibraryUnavailableError


class SamacSysCredentialTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = CredentialStore(config_dir=Path(self.temp_dir.name))

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_samacsys_credentials_from_environment(self) -> None:
        with patch.dict(
            "os.environ",
            {"SAMACSYS_USERNAME": "user@example.com", "SAMACSYS_PASSWORD": "secret-pass"},
            clear=False,
        ):
            username, password, source = self.store.get_samacsys_credentials()
        self.assertEqual(username, "user@example.com")
        self.assertEqual(password, "secret-pass")
        self.assertEqual(source, "environment")

    def test_provider_status_masks_username(self) -> None:
        self.store.set_samacsys_credentials("engineer@example.com", "secret-pass")
        status = self.store.get_provider_status(ProviderId.SAMACSYS)
        self.assertTrue(status.configured)
        self.assertEqual(status.auth_type, "basic_auth")
        self.assertEqual(status.masked_credential, "engi....com")


class SamacSysClientTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = CredentialStore(config_dir=Path(self.temp_dir.name))
        self.store.set_samacsys_credentials("user@example.com", "secret-pass")
        self.client = SamacSysClient(self.store)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_extract_part_ids_from_entry_html(self) -> None:
        html = "<input type='hidden' id='partID' name='partID' value='17275821' />"
        self.assertEqual(SamacSysClient._extract_part_ids(html), ["17275821"])

    def test_extract_part_ids_ignores_zero(self) -> None:
        html = "<input name='partID' value='0' /><a href='symbol.php?partID=12345'>"
        self.assertEqual(SamacSysClient._extract_part_ids(html), ["12345"])

    def test_match_from_part_view(self) -> None:
        html = (
            "<html><head><meta name='description' content='Thick Film Resistor'></head>"
            "<img src='symbol.php?partID=12345'>"
            "<img src='footprint.php?partID=12345'>"
            "</html>"
        )
        match = self.client._match_from_part_view("0201WMF220JTEE", "Royalohm", html)
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match.part_id, "12345")
        self.assertTrue(match.downloadable)
        self.assertTrue(match.has_symbol)
        self.assertTrue(match.has_footprint)

    def test_match_from_model_request_page_returns_none(self) -> None:
        html = "<html>What CAD Models would you like us to build?</html>"
        match = self.client._match_from_part_view("FAKEPART", "ExampleMfr", html)
        self.assertIsNone(match)

    def test_collect_exact_search_candidates_ignores_fuzzy_hits(self) -> None:
        html = (
            "<a href='/part-view/FAKEPARTLONG/Other%20Corp'>"
            "<a href='/part-view/FAKEPART/Example%20Mfr'>"
        )
        candidates = self.client._collect_exact_search_candidates("FAKEPART", html)
        self.assertEqual(candidates, [("FAKEPART", "Example Mfr")])

    def test_search_without_downloadable_library_returns_error(self) -> None:
        html = "<a href='/part-view/FAKEPARTLONG/Other%20Corp'>"

        def fake_request(url: str, *, require_auth: bool = False, accept: str = "*/*"):
            return 200, {}, html.encode("utf-8")

        with patch.object(SamacSysClient, "_request", side_effect=fake_request):
            result = self.client.search_components("FAKEPART")

        self.assertEqual(result.total_results, 0)
        self.assertEqual(result.matches, [])
        self.assertEqual(len(result.errors), 1)
        self.assertIn("No downloadable KiCad library", result.errors[0])

    def test_search_with_manufacturer_and_no_library(self) -> None:
        model_page = "<html>Schematic Symbol is unavailable for download</html>"

        def fake_request(url: str, *, require_auth: bool = False, accept: str = "*/*"):
            return 200, {}, model_page.encode("utf-8")

        with patch.object(SamacSysClient, "_request", side_effect=fake_request):
            result = self.client.search_components("FAKEPART", manufacturer="ExampleMfr")

        self.assertEqual(result.total_results, 0)
        self.assertIn("FAKEPART", result.errors[0])
        self.assertIn("ExampleMfr", result.errors[0])

    def test_resolve_part_raises_when_no_library(self) -> None:
        with patch.object(
            SamacSysClient,
            "search_components",
            return_value=SamacSysClient._no_library_result("FAKEPART"),
        ):
            with self.assertRaises(SamacSysLibraryUnavailableError):
                self.client.resolve_part("FAKEPART")

    def test_download_raises_when_no_library(self) -> None:
        with patch.object(
            SamacSysClient,
            "resolve_part",
            side_effect=SamacSysLibraryUnavailableError("FAKEPART", "ExampleMfr"),
        ):
            with self.assertRaises(SamacSysLibraryUnavailableError):
                self.client.download_component_library(
                    part_number="FAKEPART",
                    manufacturer="ExampleMfr",
                )

    def test_extract_kicad_assets_from_zip(self) -> None:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr(
                "0201WMF220JTEE/KiCad/0201WMF220JTEE.kicad_sym",
                '(kicad_symbol_lib (version "") (symbol "R1"))',
            )
            archive.writestr(
                "0201WMF220JTEE/KiCad/0201WMF220JTEE.pretty/resistor.kicad_mod",
                "(footprint)",
            )
            archive.writestr("0201WMF220JTEE/3D/0201WMF220JTEE.stp", "STEP")

        output_root = Path(self.temp_dir.name) / "out"
        extracted = SamacSysClient._extract_kicad_assets(
            buffer.getvalue(),
            output_root,
            "0201WMF220JTEE",
        )
        self.assertEqual(len(extracted), 3)
        self.assertTrue(any(path.endswith(".kicad_sym") for path in extracted))
        self.assertTrue(any(path.endswith(".kicad_mod") for path in extracted))
        self.assertTrue(any(path.endswith(".stp") for path in extracted))

    def test_download_component_library(self) -> None:
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w") as archive:
            archive.writestr(
                "0201WMF220JTEE/KiCad/0201WMF220JTEE.kicad_sym",
                '(kicad_symbol_lib (version ""))',
            )

        fake_match = self.client._match_from_part_view(
            "0201WMF220JTEE",
            "Royalohm",
            "<input name='partID' value='17275821'>",
        )

        def fake_request(url: str, *, require_auth: bool = False, accept: str = "*/*"):
            self.assertTrue(require_auth)
            self.assertIn("partID=17275821", url)
            return (
                200,
                {
                    "content-type": "application/x-zip",
                    "content-disposition": 'attachment; filename="LIB_0201WMF220JTEE.zip"',
                },
                zip_buffer.getvalue(),
            )

        with patch.object(SamacSysClient, "resolve_part", return_value=fake_match):
            with patch.object(SamacSysClient, "_request", side_effect=fake_request):
                result = self.client.download_component_library(
                    part_number="0201WMF220JTEE",
                    manufacturer="Royalohm",
                    output_dir=str(Path(self.temp_dir.name) / "downloads"),
                    extract=True,
                    overwrite=True,
                )

        self.assertEqual(result.part_id, "17275821")
        self.assertTrue(Path(result.zip_path).is_file())
        self.assertGreaterEqual(len(result.extracted_files), 1)


if __name__ == "__main__":
    unittest.main()
