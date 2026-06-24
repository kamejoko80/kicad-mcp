"""KiCad project file discovery and metadata.

Author: Henry Dang
Email: phuongminh.dang@gmail.com
"""

import glob
import json
import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ProjectPaths:
    project_dir: str
    project_name: str
    project_file: str | None = None
    root_schematic: str | None = None
    pcb_file: str | None = None
    schematic_sheets: list[str] = field(default_factory=list)


def _match_folder_name(path: str, folder_name: str) -> bool:
    return os.path.basename(path).lower() == folder_name.lower()


def find_project_files(project_dir: str) -> ProjectPaths:
    """Resolve KiCad project files from a directory and optional .kicad_pro metadata."""
    project_dir = os.path.normpath(project_dir)
    folder_name = os.path.basename(project_dir)

    project_file = _find_project_file(project_dir, folder_name)
    project_name = folder_name
    root_schematic = None
    schematic_sheets: list[str] = []
    pcb_file = None

    if project_file:
        project_name = Path(project_file).stem
        metadata = _load_project_metadata(project_file)
        schematic_sheets = metadata.get("schematic_sheets", [])
        root_schematic = metadata.get("root_schematic")
        pcb_file = metadata.get("pcb_file")

    if not root_schematic:
        root_schematic = _find_root_schematic(project_dir, folder_name)

    if not schematic_sheets:
        schematic_sheets = sorted(
            glob.glob(os.path.join(project_dir, "**", "*.kicad_sch"), recursive=True)
        )

    if not pcb_file:
        pcb_file = _find_pcb_file(project_dir, project_name)

    return ProjectPaths(
        project_dir=project_dir,
        project_name=project_name,
        project_file=project_file,
        root_schematic=root_schematic,
        pcb_file=pcb_file,
        schematic_sheets=schematic_sheets,
    )


def _find_project_file(project_dir: str, folder_name: str) -> str | None:
    pro_files = glob.glob(os.path.join(project_dir, "*.kicad_pro"))
    if not pro_files:
        return None

    for pro_file in pro_files:
        if _match_folder_name(pro_file, f"{folder_name}.kicad_pro"):
            return pro_file

    return pro_files[0]


def _find_root_schematic(project_dir: str, folder_name: str) -> str | None:
    sch_files = glob.glob(os.path.join(project_dir, "*.kicad_sch"))
    if not sch_files:
        return None

    for sch in sch_files:
        if _match_folder_name(sch, f"{folder_name}.kicad_sch"):
            return sch

    return sch_files[0]


def _find_pcb_file(project_dir: str, project_name: str) -> str | None:
    preferred = os.path.join(project_dir, f"{project_name}.kicad_pcb")
    if os.path.isfile(preferred):
        return preferred

    pcb_files = glob.glob(os.path.join(project_dir, "*.kicad_pcb"))
    return pcb_files[0] if pcb_files else None


def _load_project_metadata(project_file: str) -> dict:
    project_dir = os.path.dirname(project_file)
    project_name = Path(project_file).stem

    try:
        with open(project_file, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {}

    schematic_sheets: list[str] = []
    root_schematic = None

    top_level_sheets = data.get("schematic", {}).get("top_level_sheets", [])
    for sheet in top_level_sheets:
        filename = sheet.get("filename")
        if not filename:
            continue
        sheet_path = os.path.join(project_dir, filename)
        if os.path.isfile(sheet_path):
            schematic_sheets.append(sheet_path)
            if root_schematic is None:
                root_schematic = sheet_path

    sheet_entries = data.get("sheets", [])
    for entry in sheet_entries:
        if not isinstance(entry, list) or len(entry) < 2:
            continue
        sheet_name = entry[1]
        sheet_path = os.path.join(project_dir, f"{sheet_name}.kicad_sch")
        if os.path.isfile(sheet_path) and sheet_path not in schematic_sheets:
            schematic_sheets.append(sheet_path)

    pcb_file = _find_pcb_file(project_dir, project_name)

    return {
        "root_schematic": root_schematic,
        "schematic_sheets": sorted(set(schematic_sheets)),
        "pcb_file": pcb_file,
        "project_data": data,
    }


def summarize_project_info(paths: ProjectPaths) -> str:
    """Build a human-readable project summary from resolved paths and metadata."""
    lines = [
        f"## KiCad Project: `{paths.project_name}`",
        f"- **Project directory:** `{paths.project_dir}`",
    ]

    if paths.project_file:
        lines.append(f"- **Project file:** `{os.path.basename(paths.project_file)}`")
    else:
        lines.append("- **Project file:** not found")

    if paths.root_schematic:
        lines.append(f"- **Root schematic:** `{os.path.basename(paths.root_schematic)}`")
    else:
        lines.append("- **Root schematic:** not found")

    if paths.pcb_file:
        lines.append(f"- **PCB layout:** `{os.path.basename(paths.pcb_file)}`")
    else:
        lines.append("- **PCB layout:** not found")

    lines.append(f"- **Schematic sheets discovered:** {len(paths.schematic_sheets)}")

    if paths.project_file:
        metadata = _load_project_metadata(paths.project_file)
        project_data = metadata.get("project_data", {})
        net_classes = project_data.get("net_settings", {}).get("classes", [])
        if net_classes:
            lines.append("\n### Net Classes")
            for net_class in net_classes:
                name = net_class.get("name", "Unknown")
                track_width = net_class.get("track_width")
                clearance = net_class.get("clearance")
                lines.append(
                    f"- `{name}`: track width {track_width} mm, clearance {clearance} mm"
                )

        board = project_data.get("board", {}).get("design_settings", {})
        defaults = board.get("defaults", {})
        if defaults:
            lines.append("\n### Board Defaults")
            lines.append(f"- Default copper track width: {defaults.get('copper_line_width')} mm")
            zones = defaults.get("zones", {})
            if zones:
                lines.append(f"- Zone min clearance: {zones.get('min_clearance')} mm")

        erc_rules = project_data.get("erc", {}).get("rule_severities", {})
        if erc_rules:
            lines.append("\n### ERC Rule Severities (sample)")
            for rule, severity in list(erc_rules.items())[:8]:
                lines.append(f"- `{rule}`: {severity}")

    if paths.schematic_sheets:
        lines.append("\n### Schematic Sheets")
        for sheet in paths.schematic_sheets:
            size_kb = round(os.path.getsize(sheet) / 1024, 2)
            lines.append(f"- `{os.path.basename(sheet)}` ({size_kb} KB)")

    return "\n".join(lines)


def validate_project_dir(project_dir: str) -> str | None:
    if not os.path.isdir(project_dir):
        return f"Error: Provided path '{project_dir}' is not a valid directory."
    return None
