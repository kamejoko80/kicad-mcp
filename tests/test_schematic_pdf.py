"""Unit tests for schematic PDF page discovery and export helpers."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from kicad_mcp.cli import CliResult
from kicad_mcp.review.schematic_pdf import register
from kicad_mcp.schematic_pages import (
    default_pdf_output_path,
    list_schematic_pages,
    resolve_page_name,
    resolve_output_path,
)

SAMPLE_ROOT = """
(kicad_sch
  (sheet
    (property "Sheetname" "cover")
    (property "Sheetfile" "cover.kicad_sch")
    (instances
      (project "demo"
        (path "/abc"
          (page "2")
        )
      )
    )
  )
  (sheet
    (property "Sheetname" "mcu")
    (property "Sheetfile" "mcu.kicad_sch")
    (instances
      (project "demo"
        (path "/def"
          (page "3")
        )
      )
    )
  )
  (sheet_instances
    (path "/"
      (page "1")
    )
  )
)
"""


class SchematicPageDiscoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.project_dir = Path(self.temp_dir.name)
        self.root = self.project_dir / "demo.kicad_sch"
        self.root.write_text(SAMPLE_ROOT, encoding="utf-8")
        (self.project_dir / "cover.kicad_sch").write_text("(kicad_sch\n)\n", encoding="utf-8")
        (self.project_dir / "mcu.kicad_sch").write_text("(kicad_sch\n)\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_list_schematic_pages_from_root(self) -> None:
        pages = list_schematic_pages(str(self.root), "demo")
        self.assertEqual([page.page_number for page in pages], [1, 2, 3])
        self.assertEqual(pages[1].sheet_name, "cover")
        self.assertEqual(pages[2].sheet_name, "mcu")

    def test_resolve_page_name_accepts_sheet_file(self) -> None:
        pages = list_schematic_pages(str(self.root), "demo")
        resolved = resolve_page_name(pages, "mcu.kicad_sch")
        self.assertEqual(resolved.page_number, 3)

    def test_default_and_custom_output_paths(self) -> None:
        default_path = default_pdf_output_path(str(self.project_dir), "demo", page_name="mcu")
        self.assertTrue(default_path.endswith("demo_mcu.pdf"))
        resolved = resolve_output_path(
            str(self.project_dir),
            "exports/custom.pdf",
            default_path,
        )
        self.assertTrue(resolved.endswith("exports\\custom.pdf") or resolved.endswith("exports/custom.pdf"))


class SchematicPdfToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.project_dir = Path(self.temp_dir.name)
        self.root = self.project_dir / "demo.kicad_sch"
        self.root.write_text(SAMPLE_ROOT, encoding="utf-8")
        (self.project_dir / "cover.kicad_sch").write_text("(kicad_sch\n)\n", encoding="utf-8")
        (self.project_dir / "mcu.kicad_sch").write_text("(kicad_sch\n)\n", encoding="utf-8")
        (self.project_dir / "demo.kicad_pro").write_text('{"boards":[]}', encoding="utf-8")

        class FakeMcp:
            def __init__(self) -> None:
                self.tools: dict[str, object] = {}

            def tool(self):
                def decorator(func):
                    self.tools[func.__name__] = func
                    return func

                return decorator

        self.fake_mcp = FakeMcp()
        register(self.fake_mcp)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_list_schematic_pdf_pages_tool(self) -> None:
        list_tool = self.fake_mcp.tools["list_schematic_pdf_pages"]
        payload = json.loads(list_tool(str(self.project_dir)))
        self.assertEqual(payload["page_count"], 3)
        self.assertEqual(payload["pages"][2]["sheet_name"], "mcu")

    def test_export_schematic_pdf_tool(self) -> None:
        export_tool = self.fake_mcp.tools["export_schematic_pdf"]
        output_pdf = self.project_dir / "exports" / "mcu.pdf"
        fake_result = CliResult(stdout="Plotted", stderr="", returncode=0, output_path=str(output_pdf))
        output_pdf.parent.mkdir(parents=True, exist_ok=True)
        output_pdf.write_bytes(b"%PDF-1.4")

        with patch("kicad_mcp.review.schematic_pdf.run_kicad_cli_to_path", return_value=fake_result):
            payload = json.loads(
                export_tool(
                    str(self.project_dir),
                    output_path=str(output_pdf),
                    page_name="mcu",
                )
            )

        self.assertTrue(payload["success"])
        self.assertEqual(payload["pages"], "3")
        self.assertEqual(payload["page_name"], "mcu")


if __name__ == "__main__":
    unittest.main()
