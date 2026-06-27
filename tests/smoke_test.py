"""Direct KiCad CLI smoke test (no MCP server).

Author: Henry Dang
Email: phuongminh.dang@gmail.com
"""

import re

from kicad_mcp.cli import read_output_file, run_kicad_cli_with_output
from kicad_mcp.config import resolve_kicad_cli
from kicad_mcp.parsing import extract_pcb_net_names, extract_schematic_net_names
from kicad_mcp.project import find_project_files

proj = r"D:\Workspace\HW\KiCad\Projects\kicad_hw_design\cardinal_bes2800_rev2.0"
print("CLI:", resolve_kicad_cli())
paths = find_project_files(proj)

r = run_kicad_cli_with_output(
    ["sch", "erc", "--format", "json", "--severity-all", paths.root_schematic], ".json"
)
content = read_output_file(r.output_path)
print("ERC rc:", r.returncode, "preview:", content[:120])

r = run_kicad_cli_with_output(
    ["sch", "export", "netlist", "--format", "kicadsexpr", paths.root_schematic], ".net"
)
nl = read_output_file(r.output_path)
sch_nets = extract_schematic_net_names(nl)
print("Sch nets:", len(sch_nets))

with open(paths.pcb_file, encoding="utf-8") as handle:
    pcb = handle.read()
pcb_nets = extract_pcb_net_names(pcb)
print("PCB nets:", len(pcb_nets))
print("Matched:", len(sch_nets & pcb_nets))

r = run_kicad_cli_with_output(
    ["pcb", "export", "stats", "--format", "json", paths.pcb_file], ".json"
)
stats = read_output_file(r.output_path)
print("Stats rc:", r.returncode, "len:", len(stats))

net = "GND"
escaped = re.escape(net)
pat = (
    rf'\(segment\s+\(start\s+([\d\.-]+)\s+([\d\.-]+)\)\s+\(end\s+([\d\.-]+)\s+([\d\.-]+)\)\s+'
    rf'\(width\s+([\d\.]+)\)\s+\(layer\s+"[^"]+"\)\s+\(net\s+"{escaped}"\)'
)
print("GND segments:", len(re.findall(pat, pcb)))
