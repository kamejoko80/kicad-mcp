"""Schematic vs PCB comparison MCP tools.

Author: Henry Dang
Email: phuongminh.dang@gmail.com
"""

import logging
import os

from kicad_mcp.cli import read_output_file, run_kicad_cli_with_output
from kicad_mcp.parsing import extract_pcb_net_names, extract_schematic_net_names, is_auto_unconnected_net
from kicad_mcp.project import find_project_files, validate_project_dir

logger = logging.getLogger("kicad-hardware-agent")


def register(mcp) -> None:
    @mcp.tool()
    def compare_sch_pcb_nets(project_dir: str, include_unconnected: bool = False) -> str:
        """
        Compare schematic net names against PCB registered nets and report nets that
        exist only in schematic, only in layout, or in both. Useful for sch/layout
        consistency review.
        """
        logger.info("Comparing schematic and PCB nets for: %s", project_dir)
        error = validate_project_dir(project_dir)
        if error:
            return error

        paths = find_project_files(project_dir)
        if not paths.root_schematic:
            return "Error: No schematic files found in this directory."
        if not paths.pcb_file:
            return "Error: No layout file (*.kicad_pcb) discovered in this directory."

        netlist_result = run_kicad_cli_with_output(
            ["sch", "export", "netlist", "--format", "kicadsexpr", paths.root_schematic],
            suffix=".net",
        )
        netlist_content = read_output_file(netlist_result.output_path)
        if not netlist_content:
            detail = netlist_result.stderr or netlist_result.stdout or "Unknown CLI error"
            return f"Failed to export schematic netlist for comparison. Details: {detail}"

        try:
            with open(paths.pcb_file, encoding="utf-8") as handle:
                pcb_content = handle.read()
        except OSError as exc:
            return f"Failed to read PCB file: {exc}"

        sch_nets = extract_schematic_net_names(netlist_content)
        pcb_nets = extract_pcb_net_names(pcb_content)

        if not include_unconnected:
            sch_nets = {net for net in sch_nets if not is_auto_unconnected_net(net)}

        only_schematic = sorted(sch_nets - pcb_nets)
        only_pcb = sorted(pcb_nets - sch_nets)
        in_both = sorted(sch_nets & pcb_nets)

        lines = [
            "## Schematic vs PCB Net Comparison",
            f"- Schematic nets: **{len(sch_nets)}**",
            f"- PCB nets: **{len(pcb_nets)}**",
            f"- Matched nets: **{len(in_both)}**",
            f"- Schematic only: **{len(only_schematic)}**",
            f"- PCB only: **{len(only_pcb)}**",
        ]

        if not include_unconnected:
            lines.append("- Auto-generated `unconnected-*` schematic nets were excluded.")

        lines.append("\n### Matched Nets (sample)")
        if in_both:
            for net in in_both[:30]:
                lines.append(f"- `{net}`")
            if len(in_both) > 30:
                lines.append(f"- ... and {len(in_both) - 30} more")
        else:
            lines.append("- None")

        lines.append("\n### Schematic Only")
        if only_schematic:
            for net in only_schematic[:30]:
                lines.append(f"- `{net}`")
            if len(only_schematic) > 30:
                lines.append(f"- ... and {len(only_schematic) - 30} more")
        else:
            lines.append("- None")

        lines.append("\n### PCB Only")
        if only_pcb:
            for net in only_pcb[:30]:
                lines.append(f"- `{net}`")
            if len(only_pcb) > 30:
                lines.append(f"- ... and {len(only_pcb) - 30} more")
        else:
            lines.append("- None")

        if only_schematic or only_pcb:
            lines.append(
                "\nReview nets that differ between schematic and layout before release."
            )
        else:
            lines.append("\nSchematic and PCB net names are fully aligned.")

        return "\n".join(lines)
