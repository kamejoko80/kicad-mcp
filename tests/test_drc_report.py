"""Unit tests for DRC report parsing and snapshot export."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from kicad_mcp.review.drc_report import (
    build_drc_tool_response,
    export_drc_region_images,
    format_drc_snapshot_section,
    parse_drc_report,
    unique_error_locations,
)
from tests.test_pcb_model import MINI_PCB

SAMPLE_REPORT = """\
** Found 2 DRC violations **
[shorting_items]: Items shorting two nets (nets GND and VDD)
    Local override; error
    @(10.0000 mm, 20.0000 mm): Pad 1 [GND] of U1 on F.Cu
    @(10.0000 mm, 20.0000 mm): Track [VDD] on F.Cu, length 1.0000 mm
[clearance]: Clearance violation ( clearance 0.1000 mm; actual 0.0000 mm)
    Local override; error
    @(10.0000 mm, 20.0000 mm): Pad 1 [GND] of U1 on F.Cu
[silk_overlap]: Silkscreen clearance
    Rule: board setup constraints silk; warning
    @(30.0000 mm, 40.0000 mm): Segment on F.Silkscreen
"""


class DrcReportTests(unittest.TestCase):
    def test_parse_drc_report(self) -> None:
        violations = parse_drc_report(SAMPLE_REPORT)
        self.assertEqual(len(violations), 3)
        self.assertEqual(violations[0].rule, "shorting_items")
        self.assertEqual(violations[0].severity, "error")
        self.assertEqual(violations[0].nets, ["GND", "VDD"])
        self.assertEqual(len(violations[0].locations), 2)
        self.assertEqual(violations[0].locations[0].layer, "F.Cu")

    def test_unique_error_locations_deduplicates_coordinates(self) -> None:
        violations = parse_drc_report(SAMPLE_REPORT)
        locations = unique_error_locations(violations)
        self.assertEqual(len(locations), 1)
        self.assertEqual(locations[0][1].x_mm, 10.0)
        self.assertEqual(locations[0][1].y_mm, 20.0)

    def test_format_drc_snapshot_section(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            png_path = Path(temp_dir) / "drc_01.png"
            png_path.write_bytes(
                b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
                b"\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
                b"\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01"
                b"\r\n-\xdb\x00\x00\x00\x00IEND\xaeB`\x82"
            )
            section = format_drc_snapshot_section(
                [
                    {
                        "index": 1,
                        "rule": "shorting_items",
                        "x_mm": 208.37,
                        "y_mm": 211.97,
                        "highlight_net": "VDD",
                        "png_path": str(png_path),
                        "svg_path": str(png_path.with_suffix(".svg")),
                        "region_mm": {"width": 8.0, "height": 8.0},
                    }
                ]
            )
        self.assertIn("DRC Error Snapshots", section)
        self.assertIn("| # | Rule | Location | Snapshot |", section)
        self.assertIn("`shorting_items`", section)
        self.assertIn("208.370, 211.970", section)
        self.assertIn("[drc_01.png](file:///", section)
        self.assertNotIn("data:image/png;base64,", section)
        self.assertNotIn("<img ", section)
        self.assertNotIn("review_assets", section)
        self.assertNotIn("png_path:", section)

    def test_export_drc_region_images_writes_png_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_dir = Path(temp_dir)
            (project_dir / "test.kicad_pcb").write_text(MINI_PCB, encoding="utf-8")
            (project_dir / "test.kicad_pro").write_text("{}", encoding="utf-8")

            with mock.patch(
                "kicad_mcp.review.drc_report.export_pcb_region_image",
                return_value={
                    "output_path": str(project_dir / "mcp_exports/review/drc/test.svg"),
                    "png_path": str(project_dir / "mcp_exports/review/drc/test.png"),
                },
            ) as export_mock:
                exports = export_drc_region_images(str(project_dir), SAMPLE_REPORT, max_images=2)

            self.assertEqual(len(exports), 1)
            self.assertEqual(exports[0]["highlight_net"], "VDD")
            self.assertNotIn("chat_png_path", exports[0])
            export_mock.assert_called_once()
            call_kwargs = export_mock.call_args.kwargs
            self.assertEqual(call_kwargs["center_x_mm"], 10.0)
            self.assertEqual(call_kwargs["center_y_mm"], 20.0)
            self.assertEqual(call_kwargs["layers"], ["F.Cu", "Edge.Cuts"])

    def test_build_drc_tool_response_includes_snapshot_table(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            png_path = Path(temp_dir) / "snapshot.png"
            png_path.write_bytes(
                b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
                b"\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
                b"\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01"
                b"\r\n-\xdb\x00\x00\x00\x00IEND\xaeB`\x82"
            )
            content = build_drc_tool_response(
                "### Report\n",
                [
                    {
                        "index": 1,
                        "rule": "shorting_items",
                        "x_mm": 10.0,
                        "y_mm": 20.0,
                        "highlight_net": "VDD",
                        "png_path": str(png_path),
                        "region_mm": {"width": 8.0, "height": 8.0},
                    }
                ],
            )
            self.assertIsInstance(content, str)
            self.assertIn("### Report", content)
            self.assertIn("| Snapshot |", content)
            self.assertIn("[snapshot.png](file:///", content)
            self.assertNotIn("data:image/png;base64,", content)


if __name__ == "__main__":
    unittest.main()
