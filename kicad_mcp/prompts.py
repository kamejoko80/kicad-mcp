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
   - When DRC errors exist, `check_pcb_drc` returns a snapshot table with PNG file
     links in the Snapshot column; files are saved under
     `<project_dir>/mcp_exports/review/drc/`.
3. Run `compare_sch_pcb_nets` to catch schematic/layout naming drift.
4. For each power rail, call `inspect_net_trace` and verify trace width/current capacity.
5. Review board stats for:
   - Outline completeness and board size
   - Component density front/back
   - Via strategy (micro/blind/buried counts)
   - Minimum track width/clearance vs design rules
6. Check critical nets (clocks, diff pairs, high-speed buses, reset, power).
7. Confirm manufacturing readiness: placement, drill, copper, and silkscreen concerns.
8. Summarize findings as: Critical / Major / Minor / Informational.
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
- `check_pcb_drc` (link exported DRC error PNGs in the snapshot table when present)
- `compare_sch_pcb_nets`
- `list_project_nets`
- `inspect_net_trace` for major power rails

Deliver a consolidated report with prioritized action items.
"""

    @mcp.prompt()
    def schematic_design_workflow() -> str:
        """File-based schematic authoring workflow (Option A)."""
        return """You are authoring a KiCad schematic using file-based MCP design tools.

Workflow:
1. `create_project(name, path)` — create .kicad_pro / .kicad_sch / .kicad_pcb
   - Or `open_schematic(project_path)` for an existing project
2. `get_symbol_pins(project_path, lib_id, position)` — pin coordinates before wiring
3. `add_symbol(project_path, ref, lib_id, value, position)` — position: `x,y` or `x,y,rotation`
4. `add_power_symbol(project_path, value, x_mm, y_mm)` — GND, +5V, +3V3, etc.
5. `add_wire(project_path, x1, y1, x2, y2)` or `add_wire_path` with JSON points
6. `add_label(project_path, text, x, y, label_type)` — local or global net names
7. `save_schematic(project_path)` — write .kicad_sch to disk; user reloads in KiCad

Rules:
- Use KiCad system lib_ids (`Device:R`, `Device:LED`, `Transistor_BJT:Q_NPN_BCE`, …)
- Wire to exact pin coordinates; use orthogonal paths; avoid wires through symbols
- Call save_schematic after each batch of changes
- Validate with `check_schematic_erc` and `get_clean_component_list`
"""
