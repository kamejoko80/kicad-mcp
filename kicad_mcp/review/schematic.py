"""Schematic review MCP tools.

Author: Henry Dang
Email: phuongminh.dang@gmail.com
"""

import json
import logging
import os

from kicad_mcp.cli import read_output_file, run_kicad_cli_with_output
from kicad_mcp.project import find_project_files, summarize_project_info, validate_project_dir

logger = logging.getLogger("kicad-hardware-agent")


def register(mcp) -> None:
    @mcp.tool()
    def get_project_info(project_dir: str) -> str:
        """
        Resolve KiCad project files (.kicad_pro, root schematic, PCB) and return
        project metadata including net classes and board defaults.
        """
        logger.info("Resolving project info for: %s", project_dir)
        error = validate_project_dir(project_dir)
        if error:
            return error

        paths = find_project_files(project_dir)
        return summarize_project_info(paths)

    @mcp.tool()
    def scan_project_structure(project_dir: str) -> str:
        """
        Scan the project directory to list schematic sheets and layout files
        before running deeper schematic or PCB analysis.
        """
        logger.info("Scanning project structure for: %s", project_dir)
        error = validate_project_dir(project_dir)
        if error:
            return error

        paths = find_project_files(project_dir)
        if not paths.schematic_sheets:
            return "No matching schematic files detected."

        report = [
            f"## KiCad Hardware Architecture Map: {paths.project_name}",
            f"Discovered **{len(paths.schematic_sheets)}** schematic sheets.\n",
            "### Sheet Catalog",
        ]

        for sch in paths.schematic_sheets:
            size_kb = round(os.path.getsize(sch) / 1024, 2)
            report.append(f"- **{os.path.basename(sch)}** ({size_kb} KB)")

        if paths.pcb_file:
            size_kb = round(os.path.getsize(paths.pcb_file) / 1024, 2)
            report.append(f"\n### PCB Layout\n- **{os.path.basename(paths.pcb_file)}** ({size_kb} KB)")
        else:
            report.append("\n### PCB Layout\n- No `.kicad_pcb` file found.")

        report.append(
            "\nSuggested next steps: `get_clean_component_list`, `check_schematic_erc`, "
            "`get_electrical_netlist`, `check_pcb_drc`, `compare_sch_pcb_nets`."
        )
        return "\n".join(report)

    @mcp.tool()
    def get_clean_component_list(project_dir: str) -> str:
        """
        Extract a consolidated Bill of Materials (BOM) with references, values,
        and footprints for schematic review.
        """
        logger.info("Extracting BOM for project: %s", project_dir)
        error = validate_project_dir(project_dir)
        if error:
            return error

        paths = find_project_files(project_dir)
        if not paths.root_schematic:
            return f"Error: No schematic files (*.kicad_sch) discovered in: {project_dir}"

        result = run_kicad_cli_with_output(
            ["sch", "export", "bom", paths.root_schematic],
            suffix=".csv",
        )
        bom_data = read_output_file(result.output_path)

        if bom_data:
            return f"### Bill of Materials\n\n{bom_data}"

        detail = result.stderr or result.stdout or "Unknown CLI error"
        return f"Failed to extract BOM. CLI exit code {result.returncode}. Details: {detail}"

    @mcp.tool()
    def get_electrical_netlist(project_dir: str) -> str:
        """
        Export the schematic electrical netlist in KiCad S-expression format.
        Use this to trace signal routing, pull-ups, and pull-downs.
        """
        logger.info("Exporting schematic netlist for: %s", project_dir)
        error = validate_project_dir(project_dir)
        if error:
            return error

        paths = find_project_files(project_dir)
        if not paths.root_schematic:
            return f"Error: No schematic files found in: {project_dir}"

        result = run_kicad_cli_with_output(
            ["sch", "export", "netlist", "--format", "kicadsexpr", paths.root_schematic],
            suffix=".net",
        )
        netlist_content = read_output_file(result.output_path)

        if netlist_content:
            return f"### Schematic Netlist\n\n{netlist_content[:120000]}"

        detail = result.stderr or result.stdout or "Unknown CLI error"
        return f"Failed to export netlist. CLI exit code {result.returncode}. Details: {detail}"

    @mcp.tool()
    def check_schematic_erc(project_dir: str) -> str:
        """
        Run KiCad Electrical Rules Check (ERC) on the root schematic and return
        the violation report. Use this for schematic design review.
        """
        logger.info("Running schematic ERC for: %s", project_dir)
        error = validate_project_dir(project_dir)
        if error:
            return error

        paths = find_project_files(project_dir)
        if not paths.root_schematic:
            return "Error: No schematic files (*.kicad_sch) discovered in this directory."

        json_result = run_kicad_cli_with_output(
            [
                "sch",
                "erc",
                "--format",
                "json",
                "--severity-all",
                paths.root_schematic,
            ],
            suffix=".json",
        )
        json_content = read_output_file(json_result.output_path)

        if json_content:
            try:
                report = json.loads(json_content)
            except json.JSONDecodeError:
                return f"ERC completed but JSON report could not be parsed.\n\n{json_content}"

            violations = []
            for sheet in report.get("sheets", []):
                for violation in sheet.get("violations", []):
                    violations.append(
                        {
                            "sheet": sheet.get("path", "/"),
                            "severity": violation.get("severity"),
                            "description": violation.get("description"),
                            "items": violation.get("items", []),
                        }
                    )

            if not violations:
                source = report.get("source", os.path.basename(paths.root_schematic))
                return f"ERC clean. 0 violations found on `{source}`."

            lines = [
                f"ERC violations detected on `{report.get('source', paths.root_schematic)}`:",
                f"Total violations: **{len(violations)}**\n",
            ]
            for index, violation in enumerate(violations[:50], start=1):
                lines.append(
                    f"{index}. [{violation['severity']}] {violation['description']} "
                    f"(sheet `{violation['sheet']}`)"
                )
            if len(violations) > 50:
                lines.append(f"\n... and {len(violations) - 50} more violations.")
            return "\n".join(lines)

        report_result = run_kicad_cli_with_output(
            ["sch", "erc", "--severity-all", paths.root_schematic],
            suffix=".rpt",
        )
        report_content = read_output_file(report_result.output_path)
        if report_content:
            if "0 violations" in report_content.lower():
                return f"ERC clean on `{os.path.basename(paths.root_schematic)}`."
            return f"### Schematic ERC Report\n\n```text\n{report_content}\n```"

        detail = report_result.stderr or report_result.stdout or json_result.stderr
        return f"Failed to run ERC. CLI exit code {report_result.returncode}. Details: {detail}"
