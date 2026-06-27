"""MCP review prompt templates.

Author: Henry Dang
Email: phuongminh.dang@gmail.com
"""


def register(mcp) -> None:
    @mcp.prompt()
    def schematic_review_checklist() -> str:
        """Structured checklist for reviewing a KiCad schematic design."""
        return """You are reviewing a KiCad schematic. Follow this workflow:

1. Call `get_project_info` and `scan_project_structure` to understand the project.
2. Run `check_schematic_erc` and resolve all errors before warnings.
3. Run `get_clean_component_list` and verify:
   - Every placed part has Reference, Value, Footprint, and Datasheet where required
   - No duplicate references
   - DNP/marked parts are intentional
4. Run `get_electrical_netlist` for critical interfaces (power, reset, boot, clocks, buses).
5. Verify power tree integrity:
   - Regulator inputs/outputs and feedback networks
   - Decoupling near IC power pins
   - Correct grounds (GND/PGND/AGND) usage
6. Check connectors and test points for manufacturability and debug access.
7. Summarize findings as: Critical / Major / Minor / Informational.
"""

    @mcp.prompt()
    def layout_review_checklist() -> str:
        """Structured checklist for reviewing a KiCad PCB layout."""
        return """You are reviewing a KiCad PCB layout. Follow this workflow:

1. Call `get_project_info`, `get_board_stats`, and `list_project_nets`.
2. Run `check_pcb_drc` and resolve all violations.
3. Run `compare_sch_pcb_nets` to catch schematic/layout naming drift.
4. Use `get_component_placement` and `get_component_footprint` for critical ICs/connectors.
5. Use `get_board_geometry` and `analyze_copper_pours` to review copper, zones, and keepouts.
6. For each power rail, call `analyze_net_routing` or `inspect_net_trace`.
7. Review board stats for:
   - Outline completeness and board size
   - Component density front/back
   - Via strategy (micro/blind/buried counts)
   - Minimum track width/clearance vs design rules
8. Check critical nets (clocks, diff pairs, high-speed buses, reset, power, RF).
9. Confirm manufacturing readiness with `export_gerbers`, `export_drill_files`,
   `export_position_file`, and `inspect_manufacturing_exports`.
10. Summarize findings as: Critical / Major / Minor / Informational.
"""

    @mcp.prompt()
    def full_design_review() -> str:
        """End-to-end schematic and layout review workflow."""
        return """Perform a full KiCad hardware design review:

Phase 1 - Project discovery:
- `get_project_info`
- `scan_project_structure`

Phase 2 - Schematic review:
- `check_schematic_erc`
- `get_clean_component_list`
- `get_electrical_netlist` (focus on power and interfaces)

Phase 3 - Layout review:
- `get_board_stats`
- `check_pcb_drc`
- `compare_sch_pcb_nets`
- `list_project_nets`
- `get_component_placement`
- `get_component_footprint` for critical parts
- `get_board_geometry`
- `analyze_copper_pours`
- `analyze_net_routing` for major power and interface nets

Phase 4 - Manufacturing readiness:
- `export_gerbers`
- `export_drill_files`
- `export_position_file`
- `inspect_manufacturing_exports`

Deliver a consolidated report with prioritized action items.
"""
