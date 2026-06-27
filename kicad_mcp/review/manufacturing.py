"""Manufacturing export MCP tools.

Author: Henry Dang
Email: phuongminh.dang@gmail.com
"""

from __future__ import annotations

import json
import logging
import os

from kicad_mcp.cli import (
    read_output_directory,
    read_text_file,
    run_kicad_cli_to_path,
    run_kicad_cli_with_output_dir,
)
from kicad_mcp.project import find_project_files, validate_project_dir

logger = logging.getLogger("kicad-hardware-agent")


def _json_response(payload: dict) -> str:
    return json.dumps(payload, indent=2)


def _export_root(project_dir: str, output_dir: str | None) -> str:
    if output_dir:
        return os.path.normpath(output_dir)
    return os.path.normpath(os.path.join(project_dir, "mcp_exports"))


def _category_dir(export_root: str, category: str) -> str:
    return os.path.join(export_root, category)


def register(mcp) -> None:
    @mcp.tool()
    def export_gerbers(
        project_dir: str,
        output_dir: str = "",
        layers: str = "",
    ) -> str:
        """
        Export Gerber fabrication files for the project PCB.

        If output_dir is omitted, files are written under
        `<project_dir>/mcp_exports/gerbers`.
        """
        logger.info("Exporting gerbers for %s", project_dir)
        error = validate_project_dir(project_dir)
        if error:
            return _json_response({"error": error})

        paths = find_project_files(project_dir)
        if not paths.pcb_file:
            return _json_response({"error": "No layout file (*.kicad_pcb) discovered in this directory."})

        target_dir = _category_dir(_export_root(project_dir, output_dir or None), "gerbers")
        args = ["pcb", "export", "gerbers"]
        if layers.strip():
            args.extend(["--layers", layers.strip()])
        args.append(paths.pcb_file)

        result = run_kicad_cli_with_output_dir(args, target_dir)
        files = read_output_directory(target_dir)
        return _json_response(
            {
                "export_type": "gerbers",
                "pcb_file": paths.pcb_file,
                "output_dir": target_dir,
                "success": result.returncode == 0,
                "returncode": result.returncode,
                "file_count": len(files),
                "files": files,
                "stdout": result.stdout.strip(),
                "stderr": result.stderr.strip(),
            }
        )

    @mcp.tool()
    def export_drill_files(
        project_dir: str,
        output_dir: str = "",
        format: str = "excellon",
        units: str = "mm",
    ) -> str:
        """
        Export drill files for the project PCB.

        Supported formats: excellon, gerber.
        """
        logger.info("Exporting drill files for %s", project_dir)
        error = validate_project_dir(project_dir)
        if error:
            return _json_response({"error": error})

        paths = find_project_files(project_dir)
        if not paths.pcb_file:
            return _json_response({"error": "No layout file (*.kicad_pcb) discovered in this directory."})

        target_dir = _category_dir(_export_root(project_dir, output_dir or None), "drill")
        args = [
            "pcb",
            "export",
            "drill",
            "--format",
            format,
            "--excellon-units",
            units,
            paths.pcb_file,
        ]
        result = run_kicad_cli_with_output_dir(args, target_dir)
        files = read_output_directory(target_dir)
        return _json_response(
            {
                "export_type": "drill",
                "pcb_file": paths.pcb_file,
                "output_dir": target_dir,
                "success": result.returncode == 0,
                "returncode": result.returncode,
                "file_count": len(files),
                "files": files,
                "stdout": result.stdout.strip(),
                "stderr": result.stderr.strip(),
            }
        )

    @mcp.tool()
    def export_position_file(
        project_dir: str,
        output_dir: str = "",
        format: str = "csv",
        side: str = "both",
        units: str = "mm",
        exclude_dnp: bool = True,
    ) -> str:
        """
        Export pick-and-place / centroid position data for SMT assembly review.
        """
        logger.info("Exporting position file for %s", project_dir)
        error = validate_project_dir(project_dir)
        if error:
            return _json_response({"error": error})

        paths = find_project_files(project_dir)
        if not paths.pcb_file:
            return _json_response({"error": "No layout file (*.kicad_pcb) discovered in this directory."})

        target_dir = _category_dir(_export_root(project_dir, output_dir or None), "position")
        output_file = os.path.join(target_dir, f"{paths.project_name}-pos.{format}")
        args = [
            "pcb",
            "export",
            "pos",
            "--format",
            format,
            "--side",
            side,
            "--units",
            units,
        ]
        if exclude_dnp:
            args.append("--exclude-dnp")
        args.append(paths.pcb_file)

        result = run_kicad_cli_to_path(args, output_file)
        files = read_output_directory(target_dir)
        preview = read_text_file(output_file, max_chars=4000)
        return _json_response(
            {
                "export_type": "position",
                "pcb_file": paths.pcb_file,
                "output_dir": target_dir,
                "output_file": result.output_path,
                "success": result.returncode == 0 and bool(result.output_path),
                "returncode": result.returncode,
                "file_count": len(files),
                "files": files,
                "preview": preview[:4000],
                "stdout": result.stdout.strip(),
                "stderr": result.stderr.strip(),
            }
        )

    @mcp.tool()
    def export_ipc_d356(project_dir: str, output_dir: str = "") -> str:
        """Export IPC-D-356 netlist for manufacturing test and inspection flows."""
        logger.info("Exporting IPC-D-356 for %s", project_dir)
        error = validate_project_dir(project_dir)
        if error:
            return _json_response({"error": error})

        paths = find_project_files(project_dir)
        if not paths.pcb_file:
            return _json_response({"error": "No layout file (*.kicad_pcb) discovered in this directory."})

        target_dir = _category_dir(_export_root(project_dir, output_dir or None), "ipc_d356")
        output_file = os.path.join(target_dir, f"{paths.project_name}.ipc")
        result = run_kicad_cli_to_path(["pcb", "export", "ipcd356", paths.pcb_file], output_file)
        preview = read_text_file(output_file, max_chars=4000)
        files = read_output_directory(target_dir)
        return _json_response(
            {
                "export_type": "ipc_d356",
                "pcb_file": paths.pcb_file,
                "output_dir": target_dir,
                "output_file": result.output_path,
                "success": result.returncode == 0 and bool(result.output_path),
                "returncode": result.returncode,
                "file_count": len(files),
                "files": files,
                "preview": preview[:4000],
                "stdout": result.stdout.strip(),
                "stderr": result.stderr.strip(),
            }
        )

    @mcp.tool()
    def inspect_manufacturing_exports(project_dir: str, output_dir: str = "") -> str:
        """
        Inspect generated manufacturing outputs under the project export folder.

        Scans gerbers, drill, position, and IPC-D-356 export directories.
        """
        logger.info("Inspecting manufacturing exports for %s", project_dir)
        error = validate_project_dir(project_dir)
        if error:
            return _json_response({"error": error})

        export_root = _export_root(project_dir, output_dir or None)
        categories = ("gerbers", "drill", "position", "ipc_d356")
        summary: dict[str, dict] = {}
        for category in categories:
            category_dir = _category_dir(export_root, category)
            files = read_output_directory(category_dir)
            summary[category] = {
                "output_dir": category_dir,
                "exists": os.path.isdir(category_dir),
                "file_count": len(files),
                "files": files,
            }

        return _json_response(
            {
                "project_dir": project_dir,
                "export_root": export_root,
                "categories": summary,
            }
        )
