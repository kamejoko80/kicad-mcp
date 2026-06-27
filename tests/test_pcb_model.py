"""Unit tests for PCB parsing and geometry analysis."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from kicad_mcp.pcb_model import (
    analyze_copper_pours,
    analyze_net_routing,
    get_component_footprint,
    load_pcb_document,
)
from kicad_mcp.sexpr import parse_sexpr


MINI_PCB = """
(kicad_pcb (version 20241229) (generator "unit-test")
  (net 0 "")
  (net 1 "GND")
  (net 2 "VDD")
  (footprint "TEST:RES0402"
    (layer "F.Cu")
    (at 10 20 90)
    (property "Reference" "R1")
    (property "Value" "10k")
    (attr smd)
    (pad "1" smd roundrect
      (at -0.51 0)
      (size 0.54 0.64)
      (layers "F.Cu" "F.Paste" "F.Mask")
      (roundrectrratio 0.25)
      (net 2 "VDD")
    )
    (pad "2" smd roundrect
      (at 0.51 0)
      (size 0.54 0.64)
      (layers "F.Cu" "F.Paste" "F.Mask")
      (roundrectrratio 0.25)
      (net 1 "GND")
    )
    (fp_poly
      (pts (xy -0.8 -0.4) (xy 0.8 -0.4) (xy 0.8 0.4) (xy -0.8 0.4))
      (stroke (width 0.05) (type solid))
      (fill no)
      (layer "F.CrtYd")
    )
  )
  (segment
    (start 9.49 20)
    (end 10.51 20)
    (width 0.2)
    (layer "F.Cu")
    (net 2 "VDD")
  )
  (via
    (at 12 20)
    (size 0.6)
    (drill 0.3)
    (layers "F.Cu" "B.Cu")
    (net 1 "GND")
  )
  (zone
    (net 1 "GND")
    (layer "F.Cu")
    (hatch edge 0.5)
    (connect_pads yes (clearance 0.2))
    (min_thickness 0.25)
    (fill yes)
    (polygon
      (pts
        (xy 0 0)
        (xy 30 0)
        (xy 30 30)
        (xy 0 30)
      )
    )
    (filled_polygon
      (island
        (outline
          (pts
            (xy 0 0)
            (xy 30 0)
            (xy 30 30)
            (xy 0 30)
          )
        )
      )
    )
  )
)
"""


class PcbModelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.project_dir = self.temp_dir.name
        self.pcb_path = Path(self.project_dir) / "test.kicad_pcb"
        self.pcb_path.write_text(MINI_PCB, encoding="utf-8")
        (Path(self.project_dir) / "test.kicad_pro").write_text("{}", encoding="utf-8")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_parse_sexpr(self) -> None:
        root = parse_sexpr(MINI_PCB)
        self.assertEqual(root[0], "kicad_pcb")

    def test_load_component_footprint(self) -> None:
        document, error = load_pcb_document(self.project_dir)
        self.assertIsNone(error)
        assert document is not None
        footprint = get_component_footprint(document, "R1")
        self.assertEqual(footprint["ref"], "R1")
        self.assertEqual(footprint["value"], "10k")
        self.assertEqual(len(footprint["pads"]), 2)
        self.assertEqual(footprint["pads"][0]["net"], "VDD")
        self.assertEqual(len(footprint["courtyard"]), 1)

    def test_analyze_net_routing(self) -> None:
        document, error = load_pcb_document(self.project_dir)
        assert document is not None and error is None
        analysis = analyze_net_routing(document, "VDD")
        self.assertEqual(analysis["segments"]["count"], 1)
        self.assertEqual(analysis["pads"]["count"], 1)

    def test_analyze_copper_pours(self) -> None:
        document, error = load_pcb_document(self.project_dir)
        assert document is not None and error is None
        pours = analyze_copper_pours(document)
        self.assertEqual(pours["zone_count"], 1)
        self.assertEqual(pours["zones"][0]["net"], "GND")
        self.assertTrue(pours["zones"][0]["filled"])


if __name__ == "__main__":
    unittest.main()
