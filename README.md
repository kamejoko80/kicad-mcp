# kicad-mcp

MCP server for KiCad schematic and PCB layout design review.

## Workflow

![KiCad MCP design review workflow](img/kicad-mcp-workflow.png)

The agent connects to the MCP server over HTTP, which calls `kicad-cli` against your KiCad project files. Review runs in three phases: project discovery, schematic review, and layout review.

## Project layout

```
kicad-mcp/                  # repository root
  kicad_mcp/                # Python package
    app.py                  # MCP server entry (FastMCP setup + HTTP run)
    __main__.py             # `python -m kicad_mcp`
    config.py               # KiCad CLI path resolution
    project.py              # .kicad_pro / file discovery
    cli.py                  # kicad-cli subprocess helpers
    parsing.py              # netlist / PCB parsing helpers
    prompts.py              # MCP review prompt templates
    review/                 # MCP tool implementations
      schematic.py          # ERC, BOM, netlist
      layout.py             # DRC, board stats, net trace
      compare.py            # schematic vs PCB net comparison
  scripts/
    smoke_test.py           # direct KiCad CLI + parsing smoke test
    integration_test.py     # start MCP server, run tool tests, stop server
  img/
    kicad-mcp-workflow.png  # design review workflow diagram
  pyproject.toml
  README.md
```

## Features

### Schematic tools
- `get_project_info` — resolve project files and settings from `.kicad_pro`
- `scan_project_structure` — list schematic sheets and PCB file
- `get_clean_component_list` — BOM export
- `get_electrical_netlist` — schematic connectivity netlist
- `check_schematic_erc` — Electrical Rules Check (ERC)

### Layout tools
- `check_pcb_drc` — Design Rules Check (DRC)
- `get_board_stats` — board dimensions, pad/via counts, copper area
- `list_project_nets` — PCB net index grouped by power/signal
- `inspect_net_trace` — trace length/width and IPC-2152 current estimate

### Cross-domain tools
- `compare_sch_pcb_nets` — schematic vs PCB net name consistency

### MCP prompts
- `schematic_review_checklist`
- `layout_review_checklist`
- `full_design_review`

## Setup

```powershell
uv sync
uv run kicad-mcp
```

Alternative:

```powershell
uv run python -m kicad_mcp
```

On Windows PowerShell, to stop the MCP server:

```powershell
Stop-Process -Id (Get-NetTCPConnection -LocalPort 8500).OwningProcess -Force
```

## Configuration

| Variable | Default | Purpose |
|----------|---------|---------|
| `KICAD_CLI` | auto-detected | Path to `kicad-cli` |
| `KICAD_MCP_HOST` | `127.0.0.1` | HTTP bind address |
| `KICAD_MCP_PORT` | `8500` | HTTP port |

KiCad 10 is supported. The server auto-detects `kicad-cli` on Windows, macOS, and Linux.

## Cursor MCP config

```json
{
  "mcpServers": {
    "kicad-hardware-agent": {
      "url": "http://localhost:8500/mcp"
    }
  }
}
```

## Suggested review workflow

See the [workflow diagram](#workflow) above. In order:

1. `get_project_info` + `scan_project_structure`
2. `check_schematic_erc` + `get_clean_component_list`
3. `check_pcb_drc` + `get_board_stats` + `compare_sch_pcb_nets`
4. `inspect_net_trace` on major power rails

Or use the `full_design_review` MCP prompt for a guided checklist.

## Development

Direct KiCad CLI smoke test (no MCP server):

```powershell
uv run python -u scripts/smoke_test.py
```

Full MCP integration test (starts server, calls tools over MCP, stops server):

```powershell
uv run python -u scripts/integration_test.py
```

Optional arguments:

```powershell
uv run python -u scripts/integration_test.py --project-dir "D:\path\to\project" --port 8500
```
