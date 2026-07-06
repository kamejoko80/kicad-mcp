"""Tests for KiCad native footprint export."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from kicad_mcp.review.footprint_kicad_export import (
    resolve_footprint_library_dir,
    split_footprint_id,
    strip_refdes_from_footprint_svg,
)


class FootprintKicadExportTests(unittest.TestCase):
    def test_split_footprint_id(self) -> None:
        self.assertEqual(split_footprint_id("acd_parts:SOT65P210X110-6N"), ("acd_parts", "SOT65P210X110-6N"))
        self.assertEqual(split_footprint_id("RES0402"), ("", "RES0402"))

    def test_resolve_footprint_library_from_fp_lib_table(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_dir = Path(temp_dir)
            lib_dir = project_dir / "libs" / "acd_parts.pretty"
            lib_dir.mkdir(parents=True)
            (project_dir / "fp-lib-table").write_text(
                '(fp_lib_table (version 7)\n'
                '  (lib (name "acd_parts")(type "KiCad")'
                '(uri "${KIPRJMOD}/libs/acd_parts.pretty")(options "")(descr ""))\n)\n',
                encoding="utf-8",
            )
            resolved = resolve_footprint_library_dir(str(project_dir), "acd_parts")
            self.assertEqual(resolved, str(lib_dir.resolve()))

    def test_strip_refdes_from_footprint_svg(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            svg_path = Path(temp_dir) / "fp.svg"
            svg_path.write_text(
                """<?xml version='1.0' encoding='UTF-8'?>
<svg xmlns="http://www.w3.org/2000/svg">
  <g>
    <text>IC**</text>
    <g class="stroked-text"><desc>IC**</desc><path d="M0 0 L1 1"/></g>
    <g class="stroked-text"><desc>1</desc><path d="M0 0 L1 1"/></g>
  </g>
</svg>""",
                encoding="utf-8",
            )
            removed = strip_refdes_from_footprint_svg(str(svg_path))
            self.assertEqual(removed, 2)
            content = svg_path.read_text(encoding="utf-8")
            self.assertNotIn("IC**", content)
            self.assertIn(">1<", content)

    def test_export_component_footprint_preview_native(self) -> None:
        from kicad_mcp.review.footprint_kicad_export import export_component_footprint_preview_native

        footprint = {
            "ref": "U6",
            "value": "TEST",
            "footprint": "acd_parts:TESTFP",
            "side": "bottom",
            "pads": [],
            "fab_outline": [],
            "courtyard": [],
            "properties": {},
            "rotation_deg": 0,
            "position_mm": {"x": 0, "y": 0},
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            project_dir = Path(temp_dir)
            lib_dir = project_dir / "acd_parts.pretty"
            lib_dir.mkdir()
            (lib_dir / "TESTFP.kicad_mod").write_text('(footprint "TESTFP")', encoding="utf-8")
            (project_dir / "fp-lib-table").write_text(
                '(fp_lib_table (version 7)\n'
                '  (lib (name "acd_parts")(type "KiCad")'
                f'(uri "${{KIPRJMOD}}/acd_parts.pretty")(options "")(descr ""))\n)\n',
                encoding="utf-8",
            )
            with mock.patch(
                "kicad_mcp.review.footprint_kicad_export.export_footprint_via_kicad_cli",
                return_value={"renderer": "kicad-cli", "svg_path": str(lib_dir / "TESTFP.svg"), "png_path": str(lib_dir / "TESTFP.png")},
            ):
                payload = export_component_footprint_preview_native(str(project_dir), footprint, ref="U6")
            self.assertEqual(payload["renderer"], "kicad-cli")
            self.assertEqual(payload["ref"], "U6")


if __name__ == "__main__":
    unittest.main()
