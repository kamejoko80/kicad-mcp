---
name: kicad_review
description: Review KiCad schematic and PCB layout via the kicad-mcp MCP server. Use when reviewing hardware design, running ERC/DRC, checking footprints, netlists, power rails, or when the user mentions KiCad, schematic, PCB, or layout review.
---

# kicad_review

Schematic design workflows:

- Access MCP to querry the project information.
- Scan the project info, project structure.
- Check schematic ERC, get component list, get electrical nest list.
- Review pull up, pull down resistors.
- Review decoupling capacitors.
- Review unconected pins.
- Review power supply current capability.

Layout design workflows:

- Get board status
- Check layout DRC
- When DRC reports errors, `check_pcb_drc` exports SVG+PNG under `<project_dir>/mcp_exports/review/drc/` and returns a **DRC Error Snapshots** table (`# | Rule | Location | Snapshot`) with clickable `file://` links to PNG files in the Snapshot column. Requires `cairosvg` (restart MCP after updating dependencies).
- Compare schematic & PCB nets
- Review clearance, layout shorting failures.
- Review decoupling capacitor layout.
- Review maximun current of the power rail traces.
- Review impedance control, splited ground plane, vias avoidance effects on trace impedance.

Footprint review:

- Use `get_component_footprint` for structured pad/outline data.
- Use `export_component_footprint_preview` to export an annotated SVG+PNG under `<project_dir>/mcp_exports/review/footprints/` with package W/L/H, pad width/length, and pad pitch dimension lines.
