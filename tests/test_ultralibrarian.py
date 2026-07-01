"""Unit tests for Ultra Librarian ECAD library integration."""

from __future__ import annotations

import io
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from kicad_mcp.library.credentials import CredentialStore, ProviderId
from kicad_mcp.library.ecad.ultralibrarian import (
    FOOTPRINT_UNIT_METRIC,
    KICAD_V6_EXPORT_ID,
    SYMBOL_ORDER_FUNCTIONAL,
    UltraLibrarianClient,
    _has_export_form,
    _on_authenticated_details,
)


SEARCH_HTML = """
<a href="/details/0728d563-8630-11ea-8c00-0ad2c9526b44/STMicroelectronics/FAKEPART?uid=47417695">
FAKEPART
</a>
"""

DETAILS_HTML_V5_ONLY = """
<input type="hidden" id="PartUniqueId" name="PartUniqueId" value="0728d563-8630-11ea-8c00-0ad2c9526b44" />
<input id="KiCAD" name="exports" type="checkbox" value="24" />
"""

DETAILS_HTML = """
<meta name="description" content="Example microcontroller">
<form id="export-submission-form">
<input type="hidden" id="PartUniqueId" name="PartUniqueId" value="0728d563-8630-11ea-8c00-0ad2c9526b44" />
<input id="KiCADv6" name="exports" type="checkbox" value="42" />
<select name="export_options[0]"><option value="1-2">Functional</option></select>
<select name="export_options[1]"><option value="2-2">Metric (mm)</option></select>
</form>
"""


class UltraLibrarianCredentialTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = CredentialStore(config_dir=Path(self.temp_dir.name))

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_credentials_from_environment(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "ULTRALIBRARIAN_USERNAME": "user@example.com",
                "ULTRALIBRARIAN_PASSWORD": "secret-pass",
            },
            clear=False,
        ):
            username, password, source = self.store.get_ultralibrarian_credentials()
        self.assertEqual(username, "user@example.com")
        self.assertEqual(password, "secret-pass")
        self.assertEqual(source, "environment")

    def test_provider_status_masks_username(self) -> None:
        self.store.set_ultralibrarian_credentials("engineer@example.com", "secret-pass")
        status = self.store.get_provider_status(ProviderId.ULTRALIBRARIAN)
        self.assertTrue(status.configured)
        self.assertEqual(status.auth_type, "session_login")
        self.assertEqual(status.masked_credential, "engi....com")


class UltraLibrarianClientTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = CredentialStore(config_dir=Path(self.temp_dir.name))
        self.store.set_ultralibrarian_credentials("user@example.com", "secret-pass")
        self.client = UltraLibrarianClient(self.store)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_collect_exact_search_candidates(self) -> None:
        candidates = self.client._collect_exact_search_candidates("FAKEPART", SEARCH_HTML)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["part_number"], "FAKEPART")

    def test_match_from_details_requires_kicad_v6(self) -> None:
        candidate = {
            "path": "/details/uuid/STMicroelectronics/FAKEPART?uid=1",
            "uuid": "uuid",
            "manufacturer": "STMicroelectronics",
            "part_number": "FAKEPART",
            "uid": "1",
        }
        match = self.client._match_from_details(candidate, DETAILS_HTML_V5_ONLY)
        self.assertIsNone(match)

    def test_on_authenticated_details_requires_export_form(self) -> None:
        page = MagicMock()
        page.url = (
            "https://app.ultralibrarian.com/details/uuid/STMicroelectronics/FAKEPART?uid=1"
        )
        login_link = MagicMock()
        login_link.count.return_value = 0
        kicad = MagicMock()
        kicad.count.return_value = 1
        export_form = MagicMock()
        export_form.count.return_value = 0
        export_select = MagicMock()
        export_select.count.return_value = 0

        def locator_side_effect(selector: str):
            if selector == "#loginLink, a#loginLink, a[href*='/Account/Login']":
                return login_link
            if selector == "#KiCADv6":
                return kicad
            if selector == "#export-submission-form, form.export-submission-form":
                return export_form
            if selector == "select[name^='export_options']":
                return export_select
            return MagicMock(count=MagicMock(return_value=0))

        page.locator.side_effect = locator_side_effect
        self.assertFalse(_on_authenticated_details(page))

        export_form.count.return_value = 1
        self.assertTrue(_on_authenticated_details(page))

    def test_has_export_form_accepts_export_options_select(self) -> None:
        page = MagicMock()
        kicad = MagicMock()
        kicad.count.return_value = 1
        export_form = MagicMock()
        export_form.count.return_value = 0
        export_select = MagicMock()
        export_select.count.return_value = 1

        def locator_side_effect(selector: str):
            if selector == "#KiCADv6":
                return kicad
            if selector == "#export-submission-form, form.export-submission-form":
                return export_form
            if selector == "select[name^='export_options']":
                return export_select
            return MagicMock(count=MagicMock(return_value=0))

        page.locator.side_effect = locator_side_effect
        self.assertTrue(_has_export_form(page))

    def test_diagnose_session_reports_playwright(self) -> None:
        with patch(
            "kicad_mcp.library.ecad.ultralibrarian._require_playwright",
            return_value=MagicMock(),
        ):
            report = self.client.diagnose_session(attempt_login=False)
        self.assertEqual(report["download_method"], "playwright")
        self.assertTrue(report["playwright_installed"])

    def test_download_component_library_via_playwright(self) -> None:
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w") as archive:
            archive.writestr(
                "FAKEPART/KiCad/FAKEPART.kicad_sym",
                '(kicad_symbol_lib (version ""))',
            )
        zip_buffer.seek(0)
        zip_bytes = zip_buffer.getvalue()

        fake_match = self.client._match_from_details(
            {
                "path": "/details/uuid/STMicroelectronics/FAKEPART?uid=1",
                "uuid": "uuid",
                "manufacturer": "STMicroelectronics",
                "part_number": "FAKEPART",
                "uid": "1",
            },
            DETAILS_HTML,
        )
        assert fake_match is not None

        download_dir = Path(self.temp_dir.name) / "downloads"

        def fake_download(playwright, auth_state, part_number, part_view_url, log, timeout_ms, zip_path):
            zip_path.write_bytes(zip_bytes)

        mock_cm = MagicMock()
        mock_cm.__enter__.return_value = MagicMock()
        mock_cm.__exit__.return_value = None

        with patch(
            "kicad_mcp.library.ecad.ultralibrarian._require_playwright",
            return_value=lambda: mock_cm,
        ):
            with patch(
                "kicad_mcp.library.ecad.ultralibrarian._perform_sso_login",
                return_value={"cookies": []},
            ):
                with patch(
                    "kicad_mcp.library.ecad.ultralibrarian._download_part_library",
                    side_effect=fake_download,
                ):
                    result = self.client.download_component_library(
                                part_number="FAKEPART",
                                manufacturer="STMicroelectronics",
                                part_view_url=fake_match.part_view_url,
                                output_dir=str(download_dir),
                                extract=True,
                                overwrite=True,
                            )

        self.assertTrue(Path(result.zip_path).is_file())
        self.assertEqual(result.part_number, "FAKEPART")
        self.assertGreaterEqual(len(result.extracted_files), 1)


if __name__ == "__main__":
    unittest.main()
