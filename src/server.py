import os
import glob
import re
import logging
import subprocess
from fastmcp import FastMCP

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("kicad-hardware-agent")

mcp = FastMCP("KiCad Comprehensive Auditor")

# Absolute path to KiCad 10 CLI binary on Windows
KICAD_CLI = r"C:\Program Files\KiCad\10.0\bin\kicad-cli.exe"

def find_root_schematic(project_dir: str) -> str:
    """
    Helper function to locate the main root schematic file.
    Prioritizes a file named after the folder, otherwise falls back to the first found.
    """
    sch_files = glob.glob(os.path.join(project_dir, "*.kicad_sch"))
    if not sch_files:
        return ""

    # Try to find the root sheet matching the project folder name
    folder_name = os.path.basename(os.path.normpath(project_dir))
    for sch in sch_files:
        if os.path.basename(sch).lower() == f"{folder_name.lower()}.kicad_sch":
            return sch

    return sch_files[0]

# --- MCP TOOLS ACCESSIBLE BY THE AI AGENT ---

@mcp.tool()
def get_clean_component_list(project_dir: str) -> str:
    """
    Extracts a consolidated text layout of all component references, footprints,
    and values across the project. Use this for general Bill of Materials (BOM) auditing.
    """
    logger.info(f"Extracting component inventory for project: {project_dir}")

    if not os.path.isdir(project_dir):
        return f"Error: Provided path '{project_dir}' is not a valid directory."

    root_sch = find_root_schematic(project_dir)
    if not root_sch:
        return f"Error: No schematic files (*.kicad_sch) discovered in: {project_dir}"

    if not os.path.exists(KICAD_CLI):
        return f"Error: KiCad 10 executable not found at designated runtime path: {KICAD_CLI}"

    output_path = os.path.join(project_dir, "mcp_bom_extract.csv")

    try:
        # Use native KiCad CLI to extract a comprehensive parts spreadsheet
        cmd = [KICAD_CLI, "sch", "export", "bom", "--output", output_path, root_sch]
        result = subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

        if os.path.exists(output_path):
            with open(output_path, 'r', encoding='utf-8') as f:
                bom_data = f.read()
            os.remove(output_path)
            return f"### Clean Bill of Materials Inventory Layout:\n\n{bom_data}"
        else:
            return f"Error: BOM export completed but output file creation timed out. CLI Stderr: {result.stderr}"

    except Exception as e:
        return f"Failed to extract component layout details due to exception: {str(e)}"


@mcp.tool()
def get_electrical_netlist(project_dir: str) -> str:
    """
    Compiles and returns the full electrical netlist connectivity graph of the project
    in S-Expression format. Use this to trace signal routing, pull-ups, and pull-downs.
    """
    logger.info(f"Compiles netlist connectivity trace for project: {project_dir}")

    if not os.path.isdir(project_dir):
        return f"Error: '{project_dir}' is not a valid directory path."

    root_sch = find_root_schematic(project_dir)
    if not root_sch:
        return f"Error: No schematic files found in: {project_dir}"

    if not os.path.exists(KICAD_CLI):
        return f"Error: KiCad 10 executable missing at: {KICAD_CLI}"

    output_netlist = os.path.join(project_dir, "mcp_netlist_extract.net")

    try:
        # Export the electrical network representation in the pcbnew S-Expression layout format
        cmd = [KICAD_CLI, "sch", "export", "netlist", "--format", "kicadpcbnew", "--output", output_netlist, root_sch]
        result = subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

        if os.path.exists(output_netlist):
            with open(output_netlist, 'r', encoding='utf-8') as f:
                netlist_content = f.read()
            os.remove(output_netlist)

            # Truncate slightly if it exceeds context windows, but 100k chars is well within modern LLM limits
            return f"### Schematic S-Expression Netlist Map:\n\n{netlist_content[:120000]}"
        else:
            return f"Error: Netlist compilation finished but output file dropped. CLI Stderr: {result.stderr}"

    except Exception as e:
        return f"Failed to extract circuit network paths due to error: {str(e)}"

@mcp.tool()
def scan_project_structure(project_dir: str) -> str:
    """
    Scans the targeted folder directory structure to list all active design sheets
    and identify layout scale dependencies before invoking a deep analysis.
    """
    logger.info(f"Scanning hierarchy architecture for: {project_dir}")

    if not os.path.isdir(project_dir):
        return f"Error: Context route '{project_dir}' is invalid."

    sch_files = glob.glob(os.path.join(project_dir, "**", "*.kicad_sch"), recursive=True)
    if not sch_files:
        return f"No matching design files detected."

    report = [
        f"## 📂 KiCad Hardware Architecture Map: {os.path.basename(os.path.normpath(project_dir))}",
        f"Discovered **{len(sch_files)}** schematic architecture sheets in this design tree.\n",
        "### 📑 Sheet Catalog Inventory:"
    ]

    for sch in sorted(sch_files):
        size_kb = round(os.path.getsize(sch) / 1024, 2)
        report.append(f" • **{os.path.basename(sch)}** ({size_kb} KB)")

    report.append("\n💡 *Instructions for Agent:* Use `get_clean_component_list` to pull parts or `get_electrical_netlist` to audit specific hardware interface pins.")
    return "\n".join(report)


@mcp.tool()
def check_pcb_drc(project_dir: str) -> str:
    """
    Executes a headless KiCad 10 Design Rules Check (DRC) on the project's .kicad_pcb layout file
    and returns the complete text violation report to the AI agent.
    """
    logger.info(f"Running automated DRC layout scan for folder: {project_dir}")

    if not os.path.isdir(project_dir):
        return f"Error: Provided path '{project_dir}' is not a valid directory."

    # Locate the physical layout file
    pcb_files = glob.glob(os.path.join(project_dir, "*.kicad_pcb"))
    if not pcb_files:
        return "❌ Error: No layout file (*.kicad_pcb) discovered in this folder directory."

    pcb_path = pcb_files[0]
    report_path = os.path.join(project_dir, "mcp_drc_output.rpt")

    if not os.path.exists(KICAD_CLI):
        return f"Error: KiCad 10 executable not found at designated path: {KICAD_CLI}"

    # Construct headless DRC compilation flags
    cmd = [
        KICAD_CLI, "pcb", "drc",
        "--output", report_path,
        "--severity-all",
        pcb_path
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)

        # Extract and parse output
        if os.path.exists(report_path):
            with open(report_path, "r", encoding="utf-8") as f:
                report_content = f.read()

            os.remove(report_path) # Clean up file after reading

            # Check if completely clean
            if "** Found 0 DRC violations **" in report_content and "** Found 0 unconnected pads **" in report_content:
                return f"✅ **DRC Clean!** 0 layout violations or open connections found on {os.path.basename(pcb_path)}."

            return f"⚠️ **KiCad Layout DRC Violations Detected:**\n\n```text\n{report_content}\n```"
        else:
            return f"❌ Error: KiCad CLI executed but report generation failed.\nStderr: {result.stderr}"

    except Exception as e:
        return f"❌ Python Execution Subprocess Failed: {str(e)}"

@mcp.tool()
def list_project_nets(project_dir: str) -> str:
    """
    Scans the local .kicad_pcb layout file and lists every electrical net name
    (trace/rail name) registered on the board layout.
    """
    logger.info(f"Extracting full electrical net list index from: {project_dir}")

    if not os.path.isdir(project_dir):
        return f"Error: Provided path '{project_dir}' is not a valid directory."

    # 1. Find the physical layout file
    pcb_files = glob.glob(os.path.join(project_dir, "*.kicad_pcb"))
    if not pcb_files:
        return "❌ Error: No layout file (*.kicad_pcb) discovered in this folder directory."

    pcb_path = pcb_files[0]

    try:
        # 2. Read the S-Expression format mapping directly
        with open(pcb_path, 'r', encoding='utf-8') as f:
            pcb_content = f.read()

        # 3. Use regex to pull out all unique registered net declarations
        # Format in KiCad 10: (net 5 "GND") or (net 12 "/MCU_RESET")
        net_pattern = r'\(net\s+\d+\s+"([^"]+)"\)'
        all_nets = re.findall(net_pattern, pcb_content)

        if not all_nets:
            return f"ℹ️ The PCB layout file '{os.path.basename(pcb_path)}' was parsed successfully, but it contains 0 registered electrical nets."

        # Remove duplicates and sort them cleanly for readability
        unique_nets = sorted(list(set(all_nets)))

        # Group nets into clear categories for the AI (Power Rails vs Signals)
        power_nets = []
        signal_nets = []

        for net in unique_nets:
            # Simple naming convention guesser for power lines
            net_lower = net.lower()
            if any(p in net_lower for p in ['vcc', 'vdd', 'gnd', '+', '-', 'vbus', 'batt', '3v3', '1v8', 'pwr']):
                power_nets.append(net)
            else:
                signal_nets.append(net)

        # 4. Generate a clean structural breakdown report
        report = [
            f"## 🗺️ Registered Electrical Net Index for: `{os.path.basename(pcb_path)}`",
            f"Total unique electrical traces discovered: **{len(unique_nets)}**\n",
            "### ⚡ Identified Power & Ground Rails:"
        ]

        for p_net in power_nets:
            report.append(f" • `{p_net}`")

        report.append("\n### 📡 Signal & Interface Networks:")
        # If the list is massive, we columnize or bullet point it cleanly for the LLM window context
        for s_net in signal_nets:
            report.append(f" • `{s_net}`")

        return "\n".join(report)

    except Exception as e:
        return f"❌ Failed to extract net database index layout due to exception: {str(e)}"

@mcp.tool()
def inspect_net_trace(project_dir: str, net_name: str) -> str:
    """
    Queries a specific copper net name (e.g., '+3V3', 'GND', 'SPI_CLK') in the PCB layout file
    to extract trace width, trace length estimation, and calculates maximum DC current thresholds.
    """
    logger.info(f"Querying copper trace trace metrics for net: {net_name} inside {project_dir}")

    if not os.path.isdir(project_dir):
        return f"Error: '{project_dir}' is not a valid directory path."

    pcb_files = glob.glob(os.path.join(project_dir, "*.kicad_pcb"))
    if not pcb_files:
        return "❌ Error: No .kicad_pcb layout file discovered in this directory folder."

    pcb_path = pcb_files[0]

    try:
        # Read the raw text S-Expression content of the .kicad_pcb file directly
        with open(pcb_path, 'r', encoding='utf-8') as f:
            pcb_content = f.read()

        # 1. Look for the net registration ID mapping block
        # Format in KiCad 10: (net 5 "GND")
        net_pattern = rf'\(net\s+(\d+)\s+"{re.escape(net_name)}"\)'
        net_match = re.search(net_pattern, pcb_content)

        if not net_match:
            return f"❌ Net Error: The net name '{net_name}' was not found in the active PCB layout profile layer."

        net_id = net_match.group(1)

        # 2. Extract all segment lengths and widths linked to this specific net index
        # Format in KiCad 10: (segment (start X Y) (end X Y) (width W) (layer L) (net ID))
        segment_pattern = rf'\(segment\s+\(start\s+([\d\.-]+)\s+([\d\.-]+)\)\s+\(end\s+([\d\.-]+)\s+([\d\.-]+)\)\s+\(width\s+([\d\.]+)\)\s+\(layer\s+"[^"]+"\)\s+\(net\s+{net_id}\)\)'
        segments = re.findall(segment_pattern, pcb_content)

        if not segments:
            return f"ℹ️ Net found, but it has 0 physical copper trace segments routed yet on the board."

        total_length_mm = 0.0
        widths_found = set()

        for start_x, start_y, end_x, end_y, width in segments:
            # Calculate physical distance formula
            x1, y1 = float(start_x), float(start_y)
            x2, y2 = float(end_x), float(end_y)
            w_val = float(width)

            length = ((x2 - x1)**2 + (y2 - y1)**2)**0.5
            total_length_mm += length
            widths_found.add(w_val)

        # Determine tracking widths (use the smallest path width discovered for conservative current safety boundaries)
        min_width_mm = min(widths_found)
        max_width_mm = max(widths_found)

        # 3. Engineering Math: Maximum DC Current Estimation via IPC-2152 Framework
        # Assuming standard 1 oz/ft² copper weight plating profile thickness (= 0.035 mm / 1.37 mils)
        # Assuming a conservative target safe continuous ambient temperature rise delta of 10°C
        copper_thickness_mils = 1.37
        trace_width_mils = min_width_mm * 39.3701 # Convert mm to mils

        # Cross-sectional Area (A) = Width * Thickness
        cross_section_sq_mils = trace_width_mils * copper_thickness_mils

        # IPC-2152 Formula Constants for external layer copper traces
        k = 0.048
        b = 0.44
        c = 0.725
        temp_rise = 10.0

        # Current I = k * (Temp_Rise^b) * (Area^c)
        max_current_amps = k * (temp_rise ** b) * (cross_section_sq_mils ** c)

        report = [
            f"## 🏎️ Physical Layout Trace Report: `{net_name}`",
            f"• **Routing Status:** Successfully parsed and mapped out on board geometry.",
            f"• **Total Estimated Trace Length:** {round(total_length_mm, 2)} mm",
            f"• **Trace Width Profile:** {round(min_width_mm, 3)} mm" if min_width_mm == max_width_mm else f"• **Trace Width Bounds:** {round(min_width_mm, 3)} mm (min) to {round(max_width_mm, 3)} mm (max)",
            f"\n### ⚡ IPC-2152 Safe DC Current Capacity Estimates (1 oz/ft² Copper Weight):",
            f"• **Continuous Current Cap ($\Delta T = 10^\circ\text{C}$ Rise):** `{round(max_current_amps, 2)} Amperes`",
            f"• **Continuous Current Cap ($\Delta T = 20^\circ\text{C}$ Rise):** `{round(max_current_amps * (20/10)**b, 2)} Amperes` (Extended thermal dissipation baseline)",
            f"\n⚠️ *Safety Margin Note:* This estimation assumes continuous DC loading across uninterrupted tracks. Ensure dense neck-downs near tight BGA breakouts do not bottleneck current densities!"
        ]

        return "\n".join(report)

    except Exception as e:
        return f"❌ Failed to trace track geometry due to exception error loop: {str(e)}"

if __name__ == "__main__":
    logger.info("Initializing production KiCad Hardware Agent Server on loopback port 8500...")
    mcp.run(transport="http", host="127.0.0.1", port=8500)