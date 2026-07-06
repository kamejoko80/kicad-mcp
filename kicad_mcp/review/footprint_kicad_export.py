"""Export footprint previews using KiCad's native fp export svg renderer."""

from __future__ import annotations

import os
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from kicad_mcp.cli import run_kicad_cli_with_output_dir
from kicad_mcp.config import resolve_kicad_cli
from kicad_mcp.review.pcb_region_svg import write_region_png
from kicad_mcp.schematic_pages import resolve_output_path

_URI_RE = re.compile(r'\(lib\s+\(name\s+"([^"]+)"\)[\s\S]*?\(uri\s+"([^"]+)"\)', re.MULTILINE)
_VIEWBOX_RE = re.compile(
    r'viewBox="([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)"',
    re.IGNORECASE,
)
_SIZE_MM_RE = re.compile(
    r'width="([-\d.]+)mm"\s+height="([-\d.]+)mm"',
    re.IGNORECASE,
)
_PAD_NUMBER_DESC_RE = re.compile(r"^\d+$")


def strip_refdes_from_footprint_svg(svg_path: str) -> int:
    """Remove reference/value text from a KiCad fp export SVG; keep pad numbers."""
    try:
        tree = ET.parse(svg_path)
    except ET.ParseError:
        return 0

    parent_map: dict[ET.Element, ET.Element] = {}
    for parent in tree.iter():
        for child in parent:
            parent_map[child] = parent

    removed = 0
    for group in list(tree.iter()):
        if group.tag.split("}")[-1] != "g":
            continue
        if group.get("class") != "stroked-text":
            continue
        desc_node = next((c for c in group if c.tag.split("}")[-1] == "desc"), None)
        label = (desc_node.text or "").strip() if desc_node is not None else ""
        if _PAD_NUMBER_DESC_RE.match(label):
            continue

        parent = parent_map.get(group)
        if parent is not None:
            for sibling in list(parent):
                if sibling is group:
                    continue
                if sibling.tag.split("}")[-1] == "text" and (sibling.text or "").strip() == label:
                    parent.remove(sibling)
                    removed += 1
            parent.remove(group)
            removed += 1

    if removed:
        tree.write(svg_path, encoding="unicode", xml_declaration=True)
    return removed


def split_footprint_id(footprint_id: str) -> tuple[str, str]:
    if ":" in footprint_id:
        library, name = footprint_id.split(":", 1)
        return library.strip(), name.strip()
    return "", footprint_id.strip()


def _expand_kiprojmod(uri: str, project_dir: str) -> str:
    expanded = uri.replace("${KIPRJMOD}", project_dir).replace("${KIPRJMOD}", project_dir)
    return os.path.normpath(expanded)


def resolve_footprint_library_dir(project_dir: str, library_name: str) -> str | None:
    """Locate a .pretty directory for the given library nickname."""
    if not library_name:
        return None

    project_dir = os.path.normpath(project_dir)
    for table_name in ("fp-lib-table", "fp-lib-table.local"):
        table_path = os.path.join(project_dir, table_name)
        if not os.path.isfile(table_path):
            continue
        try:
            content = Path(table_path).read_text(encoding="utf-8")
        except OSError:
            continue
        for match in _URI_RE.finditer(content):
            name, uri = match.group(1), match.group(2)
            if name != library_name:
                continue
            candidate = _expand_kiprojmod(uri, project_dir)
            if os.path.isdir(candidate):
                return candidate

    target = f"{library_name}.pretty"
    for root, dirs, _files in os.walk(project_dir):
        if target in dirs:
            return os.path.normpath(os.path.join(root, target))
    return None


def _svg_page_size_mm(svg_path: str) -> tuple[float, float]:
    try:
        text = Path(svg_path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return 10.0, 10.0

    size_match = _SIZE_MM_RE.search(text)
    if size_match:
        return float(size_match.group(1)), float(size_match.group(2))

    view_match = _VIEWBOX_RE.search(text)
    if view_match:
        return float(view_match.group(3)), float(view_match.group(4))

    return 10.0, 10.0


def export_footprint_via_kicad_cli(
    library_dir: str,
    footprint_name: str,
    output_dir: str,
    *,
    sketch_pads: bool = True,
    hide_refdes: bool = True,
) -> dict[str, Any]:
    """Run `kicad-cli fp export svg` for editor-quality footprint rendering."""
    cli_path = resolve_kicad_cli()
    if not os.path.isfile(cli_path):
        return {"error": f"KiCad CLI not found at: {cli_path}"}

    mod_path = os.path.join(library_dir, f"{footprint_name}.kicad_mod")
    if not os.path.isfile(mod_path):
        return {"error": f"Footprint file not found: {mod_path}"}

    os.makedirs(output_dir, exist_ok=True)
    args = ["fp", "export", "svg", "--footprint", footprint_name]
    if sketch_pads:
        args.append("--sketch-pads-on-fab-layers")
    args.append(library_dir)
    result = run_kicad_cli_with_output_dir(args, output_dir, cwd=os.path.dirname(library_dir) or None)
    if result.returncode != 0:
        message = (result.stderr or result.stdout or "kicad-cli fp export svg failed").strip()
        return {"error": message, "returncode": result.returncode}

    svg_path = os.path.join(output_dir, f"{footprint_name}.svg")
    if not os.path.isfile(svg_path):
        return {"error": f"Expected SVG not created: {svg_path}", "cli_stdout": result.stdout}

    refdes_removed = 0
    if hide_refdes:
        refdes_removed = strip_refdes_from_footprint_svg(svg_path)

    width_mm, height_mm = _svg_page_size_mm(svg_path)
    png_path = os.path.splitext(svg_path)[0] + ".png"
    png_file = write_region_png(
        svg_path,
        width_mm,
        height_mm,
        min_pixels=2400,
        png_path=png_path,
    )

    payload: dict[str, Any] = {
        "renderer": "kicad-cli",
        "svg_path": svg_path,
        "library_dir": library_dir,
        "footprint_name": footprint_name,
        "region_mm": {"width": round(width_mm, 4), "height": round(height_mm, 4)},
        "cli_stdout": result.stdout.strip(),
        "refdes_hidden": hide_refdes,
        "refdes_elements_removed": refdes_removed,
    }
    if png_file:
        payload["png_path"] = png_file
        payload["png_uri"] = Path(png_file).resolve().as_uri()
    else:
        payload["png_error"] = "PNG rasterization failed (install cairosvg)."
    return payload


def export_component_footprint_preview_native(
    project_dir: str,
    footprint: dict[str, Any],
    *,
    output_path: str = "",
    ref: str = "",
) -> dict[str, Any]:
    """Export footprint preview using KiCad's native footprint editor renderer."""
    library_name, footprint_name = split_footprint_id(str(footprint.get("footprint") or ""))
    if not footprint_name:
        return {"error": "Footprint name missing from component data."}

    library_dir = resolve_footprint_library_dir(project_dir, library_name)
    if library_dir is None:
        return {
            "error": (
                f"Could not resolve footprint library '{library_name}' under project. "
                "Ensure fp-lib-table points to the .pretty folder."
            )
        }

    safe_ref = re.sub(r"[^\w.-]+", "_", (ref or footprint.get("ref") or footprint_name).strip())
    default_rel = os.path.join("mcp_exports", "review", "footprints", f"{safe_ref}_kicad")
    default_output = os.path.normpath(os.path.join(project_dir, default_rel))
    export_dir = resolve_output_path(project_dir, output_path.strip(), default_output)
    if export_dir.lower().endswith(".svg"):
        export_dir = os.path.dirname(export_dir)
    os.makedirs(export_dir, exist_ok=True)

    native = export_footprint_via_kicad_cli(library_dir, footprint_name, export_dir)
    if "error" in native:
        return native

    from kicad_mcp.review.footprint_preview_svg import analyze_footprint_dimensions

    dimensions = analyze_footprint_dimensions(footprint)
    native.update(
        {
            "ref": footprint.get("ref"),
            "value": footprint.get("value"),
            "footprint": footprint.get("footprint"),
            "side": footprint.get("side"),
            "dimensions": dimensions,
        }
    )
    png_path = native.get("png_path")
    if png_path:
        resolved = Path(str(png_path)).resolve()
        native["preview_link"] = f"[{resolved.name}]({resolved.as_uri()})"
        # Also write a stable ref-based filename for chat links.
        if ref:
            stable_png = Path(export_dir).parent / f"{safe_ref}_preview.png"
            stable_svg = stable_png.with_suffix(".svg")
            try:
                import shutil
                shutil.copy2(resolved, stable_png)
                svg_src = native.get("svg_path")
                if svg_src and os.path.isfile(str(svg_src)):
                    shutil.copy2(str(svg_src), stable_svg)
                native["png_path"] = str(stable_png)
                native["svg_path"] = str(stable_svg)
                native["png_uri"] = stable_png.resolve().as_uri()
                native["preview_link"] = f"[{stable_png.name}]({stable_png.resolve().as_uri()})"
            except OSError:
                pass
    return native
