"""Unit tests for PCB region SVG export."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from kicad_mcp.review.pcb_region_svg import export_pcb_region_svg, render_pcb_region_svg
from tests.test_pcb_model import MINI_PCB
from kicad_mcp.pcb_model import load_pcb_document


class PcbRegionSvgTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.project_dir = self.temp_dir.name
        self.pcb_path = Path(self.project_dir) / "test.kicad_pcb"
        self.pcb_path.write_text(MINI_PCB, encoding="utf-8")
        (Path(self.project_dir) / "test.kicad_pro").write_text("{}", encoding="utf-8")
        document, error = load_pcb_document(self.project_dir)
        assert document is not None and error is None
        self.document = document

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_render_contains_geometry_and_viewbox(self) -> None:
        svg, metadata = render_pcb_region_svg(
            self.document,
            center_x_mm=10.0,
            center_y_mm=20.0,
            width_mm=12.0,
            height_mm=8.0,
            layers=["F.Cu", "Edge.Cuts"],
            highlight_net="VDD",
        )
        self.assertIn('viewBox="4.0 16.0 12.0 8.0"', svg)
        self.assertIn("<line", svg)
        self.assertIn("<polygon", svg)
        self.assertEqual(metadata["counts"]["segments"], 1)
        self.assertEqual(metadata["counts"]["zones"], 1)
        self.assertEqual(metadata["highlight_net"], "VDD")

    def test_export_writes_svg_file(self) -> None:
        payload = export_pcb_region_svg(
            self.project_dir,
            center_x_mm=10.0,
            center_y_mm=20.0,
            width_mm=10.0,
            height_mm=10.0,
            highlight_net="GND",
            marker_label="DRC",
        )
        self.assertNotIn("error", payload)
        output_path = Path(payload["output_path"])
        expected_dir = Path(self.project_dir) / "mcp_exports" / "review"
        self.assertEqual(output_path.parent, expected_dir)
        self.assertEqual(payload["project_dir"], self.project_dir)
        self.assertTrue(output_path.is_file())
        content = output_path.read_text(encoding="utf-8")
        self.assertIn("<?xml", content)
        self.assertIn("DRC", content)
        self.assertEqual(payload["format"], "svg")

    def test_export_honors_relative_output_path(self) -> None:
        payload = export_pcb_region_svg(
            self.project_dir,
            center_x_mm=10.0,
            center_y_mm=20.0,
            width_mm=10.0,
            height_mm=10.0,
            output_path="exports/custom_region.svg",
        )
        self.assertNotIn("error", payload)
        output_path = Path(payload["output_path"])
        self.assertEqual(output_path, Path(self.project_dir) / "exports" / "custom_region.svg")
        self.assertTrue(output_path.is_file())

    def test_auto_zoom_fits_local_geometry(self) -> None:
        _, metadata = render_pcb_region_svg(
            self.document,
            center_x_mm=10.0,
            center_y_mm=20.0,
            auto_zoom=True,
            search_radius_mm=4.0,
            padding_mm=0.5,
            min_window_mm=4.0,
            max_window_mm=10.0,
            layers=["F.Cu"],
        )
        self.assertTrue(metadata["auto_zoom"])
        region = metadata["region_mm"]
        self.assertLessEqual(region["width"], 10.0)
        self.assertGreaterEqual(region["width"], 4.0)

        svg, metadata = render_pcb_region_svg(
            self.document,
            center_x_mm=100.0,
            center_y_mm=100.0,
            width_mm=5.0,
            height_mm=5.0,
            marker=False,
        )
        self.assertIn("<svg", svg)
        self.assertEqual(metadata["counts"]["segments"], 0)
        self.assertEqual(metadata["counts"]["pads"], 0)


if __name__ == "__main__":
    unittest.main()
