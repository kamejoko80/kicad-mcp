"""Schematic PDF export MCP tools.

Author: Henry Dang
Email: phuongminh.dang@gmail.com
"""

from __future__ import annotations

import json
import logging
import os

from kicad_mcp.cli import run_kicad_cli_to_path
from kicad_mcp.project import find_project_files, validate_project_dir
from kicad_mcp.schematic_pages import (
    default_pdf_output_path,
    list_schematic_pages,
    resolve_output_path,
    resolve_page_name,
    resolve_schematic_path,
)

logger = logging.getLogger("kicad-hardware-agent")


def _json_response(payload: dict) -> str:
    return json.dumps(payload, indent=2)


def register(mcp) -> None:
    @mcp.tool()
    def list_schematic_pdf_pages(
        project_dir: str,
        schematic_path: str = "",
    ) -> str:
        """
        List schematic PDF page numbers and sheet names for a KiCad project.

        Page numbers match `kicad-cli sch export pdf --pages`.
        """
        logger.info("Listing schematic PDF pages for %s", project_dir)
        error = validate_project_dir(project_dir)
        if error:
            return _json_response({"error": error})

        paths = find_project_files(project_dir)
        try:
            entry_schematic = resolve_schematic_path(
                paths.project_dir,
                schematic_path,
                paths.root_schematic,
            )
        except ValueError as exc:
            return _json_response({"error": str(exc)})

        pages = list_schematic_pages(entry_schematic, paths.project_name)
        return _json_response(
            {
                "project_dir": paths.project_dir,
                "project_name": paths.project_name,
                "entry_schematic": entry_schematic,
                "page_count": len(pages),
                "pages": [page.to_dict() for page in pages],
            }
        )

    @mcp.tool()
    def export_schematic_pdf(
        project_dir: str,
        output_path: str = "",
        schematic_path: str = "",
        page_name: str = "",
        pages: str = "",
        black_and_white: bool = False,
        exclude_drawing_sheet: bool = False,
    ) -> str:
        """
        Export schematic sheets to PDF using `kicad-cli sch export pdf`.

        Omit `page_name` and `pages` to export all pages. Set `page_name` to a
        sheet name such as `mcu` or `cover.kicad_sch` to export one page.
        Alternatively, set `pages` to a comma-separated KiCad page list such as
        `1,3`. Use `output_path` to choose the PDF destination; when omitted,
        files are written under `<project_dir>/mcp_exports/pdf`.
        """
        logger.info("Exporting schematic PDF for %s", project_dir)
        error = validate_project_dir(project_dir)
        if error:
            return _json_response({"error": error})

        paths = find_project_files(project_dir)
        try:
            entry_schematic = resolve_schematic_path(
                paths.project_dir,
                schematic_path,
                paths.root_schematic,
            )
        except ValueError as exc:
            return _json_response({"error": str(exc)})

        page_catalog = list_schematic_pages(entry_schematic, paths.project_name)
        if not page_catalog:
            return _json_response({"error": "No schematic pages were discovered for PDF export."})

        selected_page_name = page_name.strip()
        selected_pages = pages.strip()
        if selected_page_name and selected_pages:
            return _json_response(
                {"error": "Provide either page_name or pages, not both."}
            )

        page_filter = ""
        resolved_page = None
        if selected_page_name:
            try:
                resolved_page = resolve_page_name(page_catalog, selected_page_name)
            except ValueError as exc:
                return _json_response({"error": str(exc)})
            page_filter = str(resolved_page.page_number)
        elif selected_pages:
            page_filter = selected_pages

        default_output = default_pdf_output_path(
            paths.project_dir,
            paths.project_name,
            page_name=resolved_page.sheet_name if resolved_page else "",
            page_number=resolved_page.page_number if resolved_page else None,
        )
        target_pdf = resolve_output_path(paths.project_dir, output_path, default_output)

        args = ["sch", "export", "pdf"]
        if page_filter:
            args.extend(["--pages", page_filter])
        if black_and_white:
            args.append("--black-and-white")
        if exclude_drawing_sheet:
            args.append("--exclude-drawing-sheet")
        args.append(entry_schematic)

        result = run_kicad_cli_to_path(args, target_pdf)
        success = result.returncode == 0 and os.path.isfile(target_pdf)
        payload = {
            "export_type": "schematic_pdf",
            "project_dir": paths.project_dir,
            "project_name": paths.project_name,
            "entry_schematic": entry_schematic,
            "output_path": target_pdf,
            "page_name": resolved_page.sheet_name if resolved_page else "",
            "pages": page_filter or "all",
            "success": success,
            "returncode": result.returncode,
            "size_bytes": os.path.getsize(target_pdf) if success else 0,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
            "available_pages": [page.to_dict() for page in page_catalog],
        }
        if not success:
            payload["error"] = (
                result.stderr.strip()
                or result.stdout.strip()
                or f"kicad-cli exited with code {result.returncode}"
            )
        return _json_response(payload)
