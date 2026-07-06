"""Unit tests for annotated footprint preview export."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from kicad_mcp.review.footprint_preview_svg import (
    analyze_footprint_dimensions,
    export_footprint_preview_image,
    render_footprint_preview_svg,
)
from tests.test_pcb_model import MINI_PCB


class FootprintPreviewTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.project_dir = self.temp_dir.name
        self.pcb_path = Path(self.project_dir) / "test.kicad_pcb"
        self.pcb_path.write_text(MINI_PCB, encoding="utf-8")
        (Path(self.project_dir) / "test.kicad_pro").write_text("{}", encoding="utf-8")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_analyze_footprint_dimensions(self) -> None:
        from kicad_mcp.pcb_model import get_component_footprint, load_pcb_document

        document, error = load_pcb_document(self.project_dir)
        assert document is not None and error is None
        footprint = get_component_footprint(document, "R1")
        dimensions = analyze_footprint_dimensions(footprint)

        self.assertAlmostEqual(dimensions["package_mm"]["width_mm"], 1.6, places=2)
        self.assertAlmostEqual(dimensions["package_mm"]["length_mm"], 0.8, places=2)
        self.assertEqual(dimensions["package_mm"]["source"], "courtyard")
        self.assertAlmostEqual(dimensions["pad_mm"]["width_mm"], 0.54, places=2)
        self.assertAlmostEqual(dimensions["pad_mm"]["length_mm"], 0.64, places=2)
        self.assertAlmostEqual(dimensions["pad_mm"]["pitch_mm"], 1.02, places=2)

    def test_render_footprint_preview_svg_contains_dimensions(self) -> None:
        from kicad_mcp.pcb_model import get_component_footprint, load_pcb_document

        document, _ = load_pcb_document(self.project_dir)
        assert document is not None
        footprint = get_component_footprint(document, "R1")
        dimensions = analyze_footprint_dimensions(footprint)
        svg, _view = render_footprint_preview_svg(footprint, dimensions)

        self.assertIn("W 1.60 mm", svg)
        self.assertIn("L 0.80 mm", svg)
        self.assertIn("Pad  0.54 x 0.64 mm", svg)
        self.assertIn("Pitch  1.02 mm", svg)
        self.assertIn('id="legend"', svg)
        self.assertIn('id="dimensions"', svg)

    def test_export_footprint_preview_image_writes_files(self) -> None:
        with mock.patch(
            "kicad_mcp.review.footprint_preview_svg.write_region_png",
            return_value=str(Path(self.project_dir) / "mcp_exports/review/footprints/R1_preview.png"),
        ):
            payload = export_footprint_preview_image(self.project_dir, "R1")

        self.assertEqual(payload["ref"], "R1")
        self.assertTrue(Path(str(payload["svg_path"])).is_file())
        self.assertIn("dimensions", payload)
        self.assertIn("png_path", payload)
        self.assertIn("png_uri", payload)


if __name__ == "__main__":
    unittest.main()
