"""PCB layout review MCP tools.

Author: Henry Dang
Email: phuongminh.dang@gmail.com
"""

import json
import logging
import os

from kicad_mcp import pcb_model
from kicad_mcp.cli import read_output_file, run_kicad_cli_with_output
from kicad_mcp.parsing import classify_nets, extract_pcb_net_names
from kicad_mcp.project import find_project_files, validate_project_dir

logger = logging.getLogger("kicad-hardware-agent")


def register(mcp) -> None:
    @mcp.tool()
    def check_pcb_drc(project_dir: str) -> str:
        """
        Run KiCad Design Rules Check (DRC) on the project PCB layout and return
        the violation report.
        """
        logger.info("Running PCB DRC for: %s", project_dir)
        error = validate_project_dir(project_dir)
        if error:
            return error

        paths = find_project_files(project_dir)
        if not paths.pcb_file:
            return "Error: No layout file (*.kicad_pcb) discovered in this directory."

        result = run_kicad_cli_with_output(
            ["pcb", "drc", "--severity-all", paths.pcb_file],
            suffix=".rpt",
        )
        report_content = read_output_file(result.output_path)

        if report_content:
            clean = (
                "** Found 0 DRC violations **" in report_content
                and "** Found 0 unconnected pads **" in report_content
            )
            if clean:
                return (
                    f"DRC clean. 0 layout violations or unconnected pads found on "
                    f"`{os.path.basename(paths.pcb_file)}`."
                )
            return f"### KiCad Layout DRC Report\n\n```text\n{report_content}\n```"

        detail = result.stderr or result.stdout or "Unknown CLI error"
        return f"Failed to run DRC. CLI exit code {result.returncode}. Details: {detail}"

    @mcp.tool()
    def get_board_stats(project_dir: str) -> str:
        """
        Export PCB board statistics (dimensions, pad/via counts, component density,
        copper area, and design limits) as structured JSON for layout review.
        """
        logger.info("Exporting board stats for: %s", project_dir)
        error = validate_project_dir(project_dir)
        if error:
            return error

        paths = find_project_files(project_dir)
        if not paths.pcb_file:
            return "Error: No layout file (*.kicad_pcb) discovered in this directory."

        result = run_kicad_cli_with_output(
            ["pcb", "export", "stats", "--format", "json", paths.pcb_file],
            suffix=".json",
        )
        stats_content = read_output_file(result.output_path)

        if stats_content:
            try:
                stats = json.loads(stats_content)
            except json.JSONDecodeError:
                return f"Board stats exported but JSON could not be parsed.\n\n{stats_content}"

            metadata = stats.get("metadata", {})
            board = stats.get("board", {})
            pads = stats.get("pads", {})
            vias = stats.get("vias", {})
            components = stats.get("components", {})

            lines = [
                f"## Board Statistics: `{metadata.get('board_name', paths.project_name)}`",
                f"- KiCad version: {metadata.get('generator', 'unknown')}",
                f"- Board size: {board.get('width')} x {board.get('height')}",
                f"- Board area: {board.get('area')}",
                f"- Board thickness: {board.get('board_thickness')}",
                f"- Has outline: {board.get('has_outline')}",
                f"- Min track width: {board.get('min_track_width')}",
                f"- Min track clearance: {board.get('min_track_clearance')}",
                f"- Min drill diameter: {board.get('min_drill_diameter')}",
                "",
                "### Copper",
                f"- Front copper area: {board.get('front_copper_area')}",
                f"- Back copper area: {board.get('back_copper_area')}",
                f"- Front component density: {board.get('front_component_density')}",
                f"- Back component density: {board.get('back_component_density')}",
                "",
                "### Pads",
                f"- SMD: {pads.get('smd', 0)}",
                f"- Through-hole: {pads.get('through_hole', 0)}",
                f"- NPTH: {pads.get('npth', 0)}",
                "",
                "### Vias",
                f"- Through: {vias.get('through', 0)}",
                f"- Blind: {vias.get('blind', 0)}",
                f"- Buried: {vias.get('buried', 0)}",
                f"- Micro: {vias.get('micro', 0)}",
                "",
                "### Components",
                f"- SMD total: {components.get('smd', {}).get('total', 0)} "
                f"(front {components.get('smd', {}).get('front', 0)}, "
                f"back {components.get('smd', {}).get('back', 0)})",
                f"- THT total: {components.get('tht', {}).get('total', 0)}",
            ]
            return "\n".join(lines)

        detail = result.stderr or result.stdout or "Unknown CLI error"
        return f"Failed to export board stats. CLI exit code {result.returncode}. Details: {detail}"

    @mcp.tool()
    def list_project_nets(project_dir: str) -> str:
        """
        List every electrical net registered in the PCB layout, grouped into
        power rails and signal nets.
        """
        logger.info("Listing PCB nets for: %s", project_dir)
        error = validate_project_dir(project_dir)
        if error:
            return error

        paths = find_project_files(project_dir)
        if not paths.pcb_file:
            return "Error: No layout file (*.kicad_pcb) discovered in this directory."

        try:
            with open(paths.pcb_file, encoding="utf-8") as handle:
                pcb_content = handle.read()
        except OSError as exc:
            return f"Failed to read PCB file: {exc}"

        unique_nets = extract_pcb_net_names(pcb_content)
        if not unique_nets:
            return (
                f"The PCB file `{os.path.basename(paths.pcb_file)}` was parsed, "
                "but it contains 0 registered electrical nets."
            )

        power_nets, signal_nets = classify_nets(unique_nets)
        report = [
            f"## Registered Electrical Nets: `{os.path.basename(paths.pcb_file)}`",
            f"Total unique nets: **{len(unique_nets)}**\n",
            "### Power and Ground Rails",
        ]
        report.extend(f"- `{net}`" for net in power_nets)
        report.append("\n### Signal and Interface Networks")
        report.extend(f"- `{net}`" for net in signal_nets)
        return "\n".join(report)

    @mcp.tool()
    def inspect_net_trace(project_dir: str, net_name: str) -> str:
        """
        Inspect a specific PCB net for routed segment length, trace width profile,
        copper zone participation, and a conservative IPC-2152 DC current capacity estimate.
        """
        logger.info("Inspecting net trace %s in %s", net_name, project_dir)
        error = validate_project_dir(project_dir)
        if error:
            return error

        document, load_error = pcb_model.load_pcb_document(project_dir)
        if document is None:
            return load_error

        if net_name not in document.all_net_names():
            return f"Net `{net_name}` was not found in `{os.path.basename(document.path)}`."

        analysis = pcb_model.analyze_net_routing(document, net_name)
        if "error" in analysis:
            return analysis["error"]

        segments = analysis["segments"]
        zones = analysis["copper_zones"]
        connectivity = analysis["connectivity"]
        ipc = analysis["ipc2152_dc_estimate"]

        if segments["count"] == 0 and zones["count"] == 0:
            return (
                f"Net `{net_name}` exists but has no routed copper segments or copper zones yet. "
                f"Pads on net: {analysis['pads']['count']}."
            )

        width = segments["width_mm"]
        width_line = "n/a"
        if width["min"] is not None:
            width_line = (
                f"{width['min']} mm"
                if width["min"] == width["max"]
                else f"{width['min']} mm (min) to {width['max']} mm (max)"
            )

        report = [
            f"## Physical Trace Report: `{net_name}`",
            f"- Routing status: {analysis['routing_status']}",
            f"- Routed segments: {segments['count']}",
            f"- Copper zones: {zones['count']}",
            f"- Pads on net: {analysis['pads']['count']}",
            f"- Total estimated trace length: {segments['total_length_mm']} mm",
            f"- Trace width: {width_line}",
            f"- Layers used: {', '.join(segments['layers']) if segments['layers'] else 'none'}",
            f"- Isolated pads (track/via graph): {connectivity['isolated_pad_count']}",
            "",
            "### IPC-2152 Approximate DC Capacity (1 oz external copper)",
            f"- At 10 C rise: ~{ipc['max_current_amps_10c']} A",
            "",
            "For full structured routing data, call `analyze_net_routing`.",
        ]
        return "\n".join(report)
