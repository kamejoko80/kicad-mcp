# kicad-mcp

MCP server for KiCad schematic and PCB layout design review.

**Version:** 0.3.0

## Overview

`kicad-mcp` exposes KiCad project data to AI agents through the [Model Context Protocol](https://modelcontextprotocol.io/) over HTTP. The server combines two data sources:

1. **`kicad-cli`** — ERC, DRC, BOM, netlist, board stats, and manufacturing exports (Gerber, drill, pick-and-place).
2. **Direct `.kicad_pcb` parsing** — footprint geometry, pad sizes, placement coordinates, copper zones, tracks, vias, and net routing analysis as structured JSON.

This lets agents review schematics, inspect land patterns (e.g. QFN exposed-pad dimensions), analyze copper pours, and validate fab outputs without opening KiCad manually.

## Workflow

![KiCad MCP design review workflow](img/kicad-mcp-workflow.png)

Typical flow: project discovery → schematic review → layout/geometry review → manufacturing export check.

## Project layout

```
kicad-mcp/
  kicad_mcp/
    app.py                  # MCP server entry (FastMCP + HTTP)
    __main__.py             # python -m kicad_mcp
    config.py               # KiCad CLI path resolution
    project.py              # .kicad_pro / file discovery
    cli.py                  # kicad-cli subprocess helpers
    parsing.py              # netlist / PCB net-name helpers
    sexpr.py                # KiCad S-expression parser
    pcb_model.py            # footprint, geometry, zone, routing model
    prompts.py              # MCP review prompt templates
    review/
      schematic.py          # ERC, BOM, netlist
      layout.py             # DRC, board stats, net trace summary
      geometry.py           # footprint, placement, geometry, pours, routing
      manufacturing.py      # Gerber, drill, position, IPC-D-356 exports
      compare.py            # schematic vs PCB net comparison
  tests/
    test_pcb_model.py       # PCB parser unit tests
    smoke_test.py           # KiCad CLI smoke test (no MCP server)
    integration_test.py     # MCP server integration test
  img/
    kicad-mcp-workflow.png
  pyproject.toml
  README.md
```

## MCP tools

### Schematic tools

| Tool | Description |
|------|-------------|
| `get_project_info` | Resolve project files, net classes, and board defaults from `.kicad_pro` |
| `scan_project_structure` | List schematic sheets and PCB file |
| `get_clean_component_list` | Export BOM (reference, value, footprint) |
| `get_electrical_netlist` | Schematic connectivity netlist (S-expression) |
| `check_schematic_erc` | Run Electrical Rules Check (ERC) |

### Layout tools

| Tool | Description |
|------|-------------|
| `check_pcb_drc` | Run Design Rules Check (DRC) |
| `get_board_stats` | Board size, pad/via counts, copper area (via `kicad-cli`) |
| `list_project_nets` | All PCB nets grouped by power vs signal |
| `inspect_net_trace` | Human-readable net routing summary with IPC-2152 estimate |

### Geometry and footprint tools

These tools return **structured JSON** parsed from `.kicad_pcb`.

| Tool | Parameters | Description |
|------|------------|-------------|
| `get_component_footprint` | `project_dir`, `ref` | Pad size/shape/layer/net, courtyard, fab outline, silkscreen, absolute pad centers |
| `get_component_placement` | `project_dir` | Placement table: ref, value, footprint, side, X/Y, rotation, DNP, bounding box |
| `get_board_geometry` | `project_dir`, `layers?`, `include_graphics?` | Tracks, vias, copper zones, board graphics; optional layer filter e.g. `F.Cu,B.Cu` |
| `analyze_copper_pours` | `project_dir` | Zone fill state, layer, net, hatch, thermal settings, outline, filled islands |
| `analyze_net_routing` | `project_dir`, `net_name` | Segments, vias, zones, pads, connectivity islands, IPC-2152 estimate |

**Example — footprint review for a QFN MCU:**

```
get_component_footprint(
  project_dir: "D:/path/to/project",
  ref: "U4"
)
```

Returns pad dimensions, exposed-pad (EP) size, courtyard polygons, and absolute coordinates — useful for verifying land patterns against datasheet recommendations.

### Manufacturing tools

Export outputs default to `<project_dir>/mcp_exports/<category>/` unless `output_dir` is specified.

| Tool | Parameters | Description |
|------|------------|-------------|
| `export_gerbers` | `project_dir`, `output_dir?`, `layers?` | Generate Gerber fabrication files |
| `export_drill_files` | `project_dir`, `output_dir?`, `format?`, `units?` | Generate Excellon or Gerber drill files |
| `export_position_file` | `project_dir`, `output_dir?`, `format?`, `side?`, `units?`, `exclude_dnp?` | Pick-and-place / centroid file (CSV, ASCII, or Gerber) |
| `export_ipc_d356` | `project_dir`, `output_dir?` | IPC-D-356 netlist for electrical test |
| `inspect_manufacturing_exports` | `project_dir`, `output_dir?` | List files under gerbers, drill, position, and ipc_d356 folders |

Default export layout:

```
<project_dir>/mcp_exports/
  gerbers/
  drill/
  position/
  ipc_d356/
```

### Cross-domain tools

| Tool | Description |
|------|-------------|
| `compare_sch_pcb_nets` | Compare schematic vs PCB net names; flag sch-only or pcb-only nets |

### MCP prompts

| Prompt | Description |
|--------|-------------|
| `schematic_review_checklist` | Guided schematic review workflow |
| `layout_review_checklist` | Guided layout, geometry, and manufacturing review |
| `full_design_review` | End-to-end schematic + layout + fab readiness review |

## Setup

Requires **Python 3.10+** and **KiCad 9 or 10** with `kicad-cli` on PATH (or set `KICAD_CLI`).

```powershell
uv sync
uv run kicad-mcp
```

Alternative:

```powershell
uv run python -m kicad_mcp
```

Stop the server (Windows PowerShell):

```powershell
Stop-Process -Id (Get-NetTCPConnection -LocalPort 8500).OwningProcess -Force
```

## Configuration

| Variable | Default | Purpose |
|----------|---------|---------|
| `KICAD_CLI` | auto-detected | Path to `kicad-cli` |
| `KICAD_MCP_HOST` | `127.0.0.1` | HTTP bind address |
| `KICAD_MCP_PORT` | `8500` | HTTP port |

`kicad-cli` is auto-detected on Windows, macOS, and Linux. KiCad 10 name-only nets (e.g. `(net "GND")` on pads) are supported by the PCB parser.

## Cursor MCP config

Add to your Cursor MCP settings:

```json
{
  "mcpServers": {
    "kicad-hardware-agent": {
      "url": "http://localhost:8500/mcp"
    }
  }
}
```

Restart the MCP server after upgrading so new tools are registered.

## Suggested review workflow

1. **Discovery** — `get_project_info`, `scan_project_structure`
2. **Schematic** — `check_schematic_erc`, `get_clean_component_list`, `get_electrical_netlist`
3. **Layout checks** — `check_pcb_drc`, `get_board_stats`, `compare_sch_pcb_nets`, `list_project_nets`
4. **Geometry** — `get_component_footprint` (critical ICs), `get_component_placement`, `get_board_geometry`, `analyze_copper_pours`
5. **Nets** — `analyze_net_routing` or `inspect_net_trace` on power rails and critical interfaces (GND, VDD, USB, RF, SWD, SPI)
6. **Manufacturing** — `export_gerbers`, `export_drill_files`, `export_position_file`, `inspect_manufacturing_exports`

Or invoke the `full_design_review` MCP prompt for a guided checklist.

## Development

### Unit tests

```powershell
uv run python -m unittest discover -s tests -v
```

### KiCad CLI smoke test (no MCP server)

```powershell
uv run python -u tests/smoke_test.py
```

### MCP integration test

Starts the server, exercises tools over MCP, then stops:

```powershell
uv run python -u tests/integration_test.py
```

With a specific project:

```powershell
uv run python -u tests/integration_test.py --project-dir "D:\path\to\project" --port 8500
```

## License

See repository license file if present.
