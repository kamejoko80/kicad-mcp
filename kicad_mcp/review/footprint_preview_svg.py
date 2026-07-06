"""Render annotated footprint preview SVG/PNG for layout review."""

from __future__ import annotations

import math
import os
import re
from collections import Counter
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET

from kicad_mcp import pcb_model
from kicad_mcp.review.pcb_region_svg import write_region_png
from kicad_mcp.schematic_pages import resolve_output_path

# KiCad footprint-editor-like palette
BG_COLOR = "#0F0F23"
GRID_DOT = "#3A3A5C"
PAD_FILL = "#C83434"
PAD_STROKE = "#8B0000"
FAB_STROKE = "#C0C0C0"
CRTYD_STROKE = "#FF00FF"
AXIS_STROKE = "#6060A0"
LEGEND_BG = "#16162E"
LEGEND_TEXT = "#E8E8F0"
LEGEND_ACCENT = "#FFD54F"
DIM_STROKE = "#FFD54F"

_HEIGHT_RE = re.compile(r"(?:height|body\s*height|H)\s*[:=]?\s*([0-9.]+)\s*mm?", re.I)

FOOTPRINT_VIEW_MM = 5.5
LEGEND_HEIGHT_MM = 2.8
CANVAS_PAD_MM = 0.35


def _absolute_to_local(
    x: float,
    y: float,
    origin_x: float,
    origin_y: float,
    rotation_deg: float,
) -> tuple[float, float]:
    dx = x - origin_x
    dy = y - origin_y
    radians = math.radians(-rotation_deg)
    cosine = math.cos(radians)
    sine = math.sin(radians)
    return dx * cosine - dy * sine, dx * sine + dy * cosine


def _bbox(points: list[dict[str, float]]) -> dict[str, float] | None:
    if not points:
        return None
    xs = [point["x"] for point in points]
    ys = [point["y"] for point in points]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    return {
        "min_x": min_x,
        "min_y": min_y,
        "max_x": max_x,
        "max_y": max_y,
        "width": max_x - min_x,
        "height": max_y - min_y,
    }


def _expand_bbox(box: dict[str, float], margin: float) -> dict[str, float]:
    return {
        "min_x": box["min_x"] - margin,
        "min_y": box["min_y"] - margin,
        "max_x": box["max_x"] + margin,
        "max_y": box["max_y"] + margin,
        "width": box["width"] + 2 * margin,
        "height": box["height"] + 2 * margin,
    }


def _parse_height_mm(properties: dict[str, str]) -> float | None:
    for key in ("Height", "height", "Body Height", "body_height", "H"):
        raw = properties.get(key, "").strip()
        if not raw:
            continue
        match = re.search(r"([0-9.]+)", raw)
        if match:
            return round(float(match.group(1)), 3)
    for value in properties.values():
        match = _HEIGHT_RE.search(str(value))
        if match:
            return round(float(match.group(1)), 3)
    return None


def _graphic_points_local(
    footprint: dict[str, Any],
    graphics: list[dict[str, Any]],
) -> list[dict[str, float]]:
    origin = footprint.get("position_mm") or {}
    ox = float(origin.get("x", 0.0))
    oy = float(origin.get("y", 0.0))
    rotation = float(footprint.get("rotation_deg") or 0.0)
    local_points: list[dict[str, float]] = []
    for graphic in graphics:
        for point in graphic.get("points") or []:
            lx, ly = _absolute_to_local(float(point["x"]), float(point["y"]), ox, oy, rotation)
            local_points.append({"x": round(lx, 4), "y": round(ly, 4)})
    return local_points


def _representative_pad_size(pads: list[dict[str, Any]]) -> tuple[float, float] | None:
    sizes: list[tuple[float, float]] = []
    for pad in pads:
        if str(pad.get("type") or "") not in {"smd", "thru_hole", ""}:
            continue
        size = pad.get("size_mm") or {}
        width = float(size.get("x") or 0.0)
        height = float(size.get("y") or width)
        if width <= 0 or height <= 0:
            continue
        sizes.append((round(min(width, height), 4), round(max(width, height), 4)))
    if not sizes:
        return None
    return Counter(sizes).most_common(1)[0][0]


def _estimate_pad_pitch_mm(pads: list[dict[str, Any]]) -> float | None:
    centers: list[tuple[float, float]] = []
    for pad in pads:
        local = pad.get("center_mm", {}).get("local") or {}
        centers.append((float(local.get("x", 0.0)), float(local.get("y", 0.0))))
    if len(centers) < 2:
        return None

    best_pitch: float | None = None
    tolerance = 0.05
    for axis_index in (0, 1):
        grouped: dict[float, list[tuple[float, float]]] = {}
        for x, y in centers:
            coord = x if axis_index == 0 else y
            cross = y if axis_index == 0 else x
            matched_key = None
            for key in grouped:
                if abs(key - cross) <= tolerance:
                    matched_key = key
                    break
            grouped.setdefault(matched_key if matched_key is not None else cross, []).append((x, y))
        for row in grouped.values():
            if len(row) < 2:
                continue
            row.sort(key=lambda point: point[axis_index])
            pitches = [
                abs(row[index + 1][axis_index] - row[index][axis_index])
                for index in range(len(row) - 1)
                if abs(row[index + 1][axis_index] - row[index][axis_index]) > 0.01
            ]
            if pitches:
                pitch = round(min(pitches), 4)
                if best_pitch is None or pitch < best_pitch:
                    best_pitch = pitch
    return best_pitch


def analyze_footprint_dimensions(footprint: dict[str, Any]) -> dict[str, Any]:
    """Summarize package and pad dimensions from parsed footprint data."""
    pads = footprint.get("pads") or []
    fab_points = _graphic_points_local(footprint, footprint.get("fab_outline") or [])
    crt_points = _graphic_points_local(footprint, footprint.get("courtyard") or [])
    pad_points: list[dict[str, float]] = []
    for pad in pads:
        local = pad.get("center_mm", {}).get("local") or {}
        cx = float(local.get("x", 0.0))
        cy = float(local.get("y", 0.0))
        size = pad.get("size_mm") or {}
        half_w = float(size.get("x", 0.0)) / 2.0
        half_h = float(size.get("y", half_w)) / 2.0
        pad_points.extend(
            [
                {"x": cx - half_w, "y": cy - half_h},
                {"x": cx + half_w, "y": cy + half_h},
            ]
        )

    body_bbox = _bbox(fab_points) or _bbox(crt_points) or _bbox(pad_points)
    pad_size = _representative_pad_size(pads)
    properties = footprint.get("properties") or {}

    package = {
        "width_mm": round(body_bbox["width"], 3) if body_bbox else None,
        "length_mm": round(body_bbox["height"], 3) if body_bbox else None,
        "height_mm": _parse_height_mm(properties),
        "source": "fab_outline" if fab_points else ("courtyard" if crt_points else "pads"),
    }
    pad_dims = {
        "width_mm": pad_size[0] if pad_size else None,
        "length_mm": pad_size[1] if pad_size else None,
        "pitch_mm": _estimate_pad_pitch_mm(pads),
    }
    return {"package_mm": package, "pad_mm": pad_dims}


def _add_rect(parent: ET.Element, box: dict[str, float], *, fill: str, stroke: str, stroke_width: float) -> None:
    ET.SubElement(
        parent,
        "rect",
        {
            "x": str(box["min_x"]),
            "y": str(-box["max_y"]),
            "width": str(box["width"]),
            "height": str(box["height"]),
            "fill": fill,
            "stroke": stroke,
            "stroke-width": str(stroke_width),
        },
    )


def _add_pad_local(parent: ET.Element, pad: dict[str, Any], *, footprint_rotation_deg: float) -> None:
    local = pad.get("center_mm", {}).get("local") or {}
    cx = float(local.get("x", 0.0))
    cy = float(local.get("y", 0.0))
    size = pad.get("size_mm") or {}
    width = float(size.get("x", 0.0))
    height = float(size.get("y", width))
    local_rotation = float(pad.get("rotation_deg") or 0.0) - footprint_rotation_deg
    shape = str(pad.get("shape") or "rect")

    group = ET.SubElement(parent, "g", {"transform": f"translate({cx},{-cy})"})
    if shape == "circle" or width == height:
        radius = max(width, height) / 2.0
        ET.SubElement(
            group,
            "circle",
            {"cx": "0", "cy": "0", "r": str(radius), "fill": PAD_FILL, "stroke": PAD_STROKE, "stroke-width": "0.02"},
        )
    else:
        rect = ET.SubElement(
            group,
            "rect",
            {
                "x": str(-width / 2.0),
                "y": str(-height / 2.0),
                "width": str(width),
                "height": str(height),
                "fill": PAD_FILL,
                "stroke": PAD_STROKE,
                "stroke-width": "0.02",
            },
        )
        if local_rotation:
            rect.set("transform", f"rotate({-local_rotation})")

    label_size = max(0.22, min(0.38, width * 0.55))
    text = ET.SubElement(
        group,
        "text",
        {
            "x": "0",
            "y": str(-label_size * 0.35),
            "fill": "#FFFFFF",
            "font-size": str(label_size),
            "font-family": "sans-serif",
            "font-weight": "bold",
            "text-anchor": "middle",
            "dominant-baseline": "middle",
            "transform": "scale(1,-1)",
        },
    )
    text.text = str(pad.get("number") or "")


def _add_grid(parent: ET.Element, half_extent: float, step: float = 0.5) -> None:
    limit = half_extent
    value = -limit
    while value <= limit + 1e-6:
        x = -limit
        while x <= limit + 1e-6:
            ET.SubElement(parent, "circle", {"cx": str(x), "cy": str(value), "r": "0.025", "fill": GRID_DOT})
            x += step
        value += step


def _add_fab_outline(parent: ET.Element, fab_points: list[dict[str, float]], fab_graphics: list[dict[str, Any]]) -> None:
    box = _bbox(fab_points)
    if box is None:
        return
    _add_rect(parent, box, fill="none", stroke=FAB_STROKE, stroke_width=0.06)
    for graphic in fab_graphics:
        if str(graphic.get("type")) != "fp_line":
            continue
        points = graphic.get("points") or []
        if len(points) != 2:
            continue
        x1, y1 = float(points[0]["x"]), float(points[0]["y"])
        x2, y2 = float(points[1]["x"]), float(points[1]["y"])
        length = math.hypot(x2 - x1, y2 - y1)
        if 0.2 < length < 0.8 and abs(x2 - x1) > 0.05 and abs(y2 - y1) > 0.05:
            _add_line(parent, x1, -y1, x2, -y2, stroke=FAB_STROKE, width=0.06)


def _add_line(parent: ET.Element, x1: float, y1: float, x2: float, y2: float, *, stroke: str, width: float) -> None:
    ET.SubElement(
        parent,
        "line",
        {"x1": str(x1), "y1": str(y1), "x2": str(x2), "y2": str(y2), "stroke": stroke, "stroke-width": str(width)},
    )


def _add_text_svg(
    parent: ET.Element,
    x: float,
    y: float,
    text: str,
    *,
    size: float,
    fill: str = LEGEND_TEXT,
    anchor: str = "start",
    weight: str = "normal",
    flip_y: bool = False,
) -> None:
    attrs = {
        "x": str(x),
        "y": str(y),
        "fill": fill,
        "font-size": str(size),
        "font-family": "Consolas, monospace",
        "text-anchor": anchor,
        "font-weight": weight,
    }
    if flip_y:
        attrs["transform"] = f"translate({x},{y}) scale(1,-1) translate({-x},{-y})"
    node = ET.SubElement(parent, "text", attrs)
    node.text = text


def _add_mini_dimension_h(
    parent: ET.Element,
    x1: float,
    x2: float,
    y_kicad: float,
    label: str,
    *,
    gap: float,
    font_size: float,
) -> None:
    """Dimension line below feature; y_kicad is in KiCad Y-up coordinates."""
    y = -y_kicad - gap
    tick = gap * 0.35
    _add_line(parent, x1, -y_kicad, x1, y - tick, stroke=DIM_STROKE, width=0.03)
    _add_line(parent, x2, -y_kicad, x2, y - tick, stroke=DIM_STROKE, width=0.03)
    _add_line(parent, x1, y, x2, y, stroke=DIM_STROKE, width=0.03)
    _add_text_svg(
        parent,
        (x1 + x2) / 2.0,
        y,
        label,
        size=font_size,
        anchor="middle",
        fill=DIM_STROKE,
        flip_y=True,
    )


def _add_mini_dimension_v(
    parent: ET.Element,
    y1_kicad: float,
    y2_kicad: float,
    x_kicad: float,
    label: str,
    *,
    gap: float,
    font_size: float,
) -> None:
    x = x_kicad - gap
    tick = gap * 0.35
    _add_line(parent, x_kicad, -y1_kicad, x - tick, -y1_kicad, stroke=DIM_STROKE, width=0.03)
    _add_line(parent, x_kicad, -y2_kicad, x - tick, -y2_kicad, stroke=DIM_STROKE, width=0.03)
    _add_line(parent, x, -y2_kicad, x, -y1_kicad, stroke=DIM_STROKE, width=0.03)
    _add_text_svg(
        parent,
        x,
        -(y1_kicad + y2_kicad) / 2.0,
        label,
        size=font_size,
        anchor="end",
        fill=DIM_STROKE,
        flip_y=True,
    )


def render_footprint_preview_svg(
    footprint: dict[str, Any],
    dimensions: dict[str, Any],
    *,
    margin_mm: float = 2.5,
) -> tuple[str, dict[str, float]]:
    """Render editor-style footprint view with a separate dimension legend."""
    _ = margin_mm  # kept for API compatibility; layout uses fixed canvas sizes
    pads = footprint.get("pads") or []
    fp_rotation = float(footprint.get("rotation_deg") or 0.0)
    fab_graphics = footprint.get("fab_outline") or []
    crt_graphics = footprint.get("courtyard") or []

    fab_points = _graphic_points_local(footprint, fab_graphics)
    crt_points = _graphic_points_local(footprint, crt_graphics)
    body_bbox = _bbox(fab_points) or _bbox(crt_points)
    if body_bbox is None:
        pad_pts: list[dict[str, float]] = []
        for pad in pads:
            local = pad.get("center_mm", {}).get("local") or {}
            pad_pts.append({"x": float(local.get("x", 0.0)), "y": float(local.get("y", 0.0))})
        body_bbox = _bbox(pad_pts) or {"min_x": -1, "min_y": -1, "max_x": 1, "max_y": 1, "width": 2, "height": 2}

    crt_bbox = _bbox(crt_points) or _expand_bbox(body_bbox, 0.25)

    canvas_w = FOOTPRINT_VIEW_MM + 2 * CANVAS_PAD_MM
    canvas_h = FOOTPRINT_VIEW_MM + LEGEND_HEIGHT_MM + 2 * CANVAS_PAD_MM
    fp_half = FOOTPRINT_VIEW_MM / 2.0
    fp_center_y = CANVAS_PAD_MM + fp_half

    svg = ET.Element(
        "svg",
        {
            "xmlns": "http://www.w3.org/2000/svg",
            "viewBox": f"0 0 {canvas_w} {canvas_h}",
            "width": f"{canvas_w}mm",
            "height": f"{canvas_h}mm",
        },
    )
    ET.SubElement(svg, "rect", {"x": "0", "y": "0", "width": str(canvas_w), "height": str(canvas_h), "fill": BG_COLOR})

    fp_panel = ET.SubElement(
        svg,
        "g",
        {"id": "footprint-panel", "transform": f"translate({canvas_w / 2.0},{fp_center_y})"},
    )
    _add_grid(fp_panel, fp_half - 0.2, step=0.5)
    _add_line(fp_panel, -fp_half, 0, fp_half, 0, stroke=AXIS_STROKE, width=0.02)
    _add_line(fp_panel, 0, -fp_half, 0, fp_half, stroke=AXIS_STROKE, width=0.02)

    fp_view = ET.SubElement(fp_panel, "g", {"id": "footprint", "transform": "scale(1,-1)"})

    _add_rect(fp_view, crt_bbox, fill="none", stroke=CRTYD_STROKE, stroke_width=0.05)
    _add_fab_outline(fp_view, fab_points, fab_graphics)

    for pad in pads:
        _add_pad_local(fp_view, pad, footprint_rotation_deg=fp_rotation)

    package = dimensions.get("package_mm") or {}
    pad_dims = dimensions.get("pad_mm") or {}
    width_mm = package.get("width_mm")
    length_mm = package.get("length_mm")
    dim_font = 0.18
    dim_gap = 0.28
    dims = ET.SubElement(fp_view, "g", {"id": "dimensions"})
    if width_mm:
        _add_mini_dimension_h(
            dims,
            body_bbox["min_x"],
            body_bbox["max_x"],
            body_bbox["min_y"] - dim_gap,
            f"W {width_mm:.2f}",
            gap=dim_gap,
            font_size=dim_font,
        )
    if length_mm:
        _add_mini_dimension_v(
            dims,
            body_bbox["min_y"],
            body_bbox["max_y"],
            body_bbox["min_x"] - dim_gap,
            f"L {length_mm:.2f}",
            gap=dim_gap,
            font_size=dim_font,
        )

    legend_top = CANVAS_PAD_MM + FOOTPRINT_VIEW_MM + 0.15
    legend_h = LEGEND_HEIGHT_MM - 0.15
    legend = ET.SubElement(svg, "g", {"id": "legend"})
    ET.SubElement(
        legend,
        "rect",
        {
            "x": str(CANVAS_PAD_MM),
            "y": str(legend_top),
            "width": str(canvas_w - 2 * CANVAS_PAD_MM),
            "height": str(legend_h),
            "fill": LEGEND_BG,
            "stroke": "#2A2A48",
            "stroke-width": "0.04",
            "rx": "0.12",
        },
    )

    ref = str(footprint.get("ref") or "")
    value = str(footprint.get("value") or "")
    fp_name = str(footprint.get("footprint") or "")
    title = f"{ref}  {value}".strip() or fp_name
    lx = CANVAS_PAD_MM + 0.25
    ly = legend_top + 0.45
    line_step = 0.62
    legend_font = 0.28

    _add_text_svg(legend, lx, ly, title, size=legend_font, weight="bold")
    _add_text_svg(legend, canvas_w - CANVAS_PAD_MM - 0.25, ly, fp_name, size=legend_font * 0.85, anchor="end", fill=LEGEND_ACCENT)

    pkg_w = package.get("width_mm")
    pkg_l = package.get("length_mm")
    pkg_h = package.get("height_mm")
    pad_w = pad_dims.get("width_mm")
    pad_l = pad_dims.get("length_mm")
    pitch = pad_dims.get("pitch_mm")

    row2_parts = []
    if pkg_w is not None and pkg_l is not None:
        row2_parts.append(f"Package  W {pkg_w:.2f} mm   L {pkg_l:.2f} mm")
    if pkg_h is not None:
        row2_parts.append(f"H {pkg_h:.2f} mm")
    elif row2_parts:
        row2_parts.append("H n/a")
    if row2_parts:
        _add_text_svg(legend, lx, ly + line_step, "   ".join(row2_parts), size=legend_font * 0.92)

    row3_parts = []
    if pad_w is not None and pad_l is not None:
        row3_parts.append(f"Pad  {pad_w:.2f} x {pad_l:.2f} mm")
    if pitch is not None:
        row3_parts.append(f"Pitch  {pitch:.2f} mm")
    if row3_parts:
        _add_text_svg(legend, lx, ly + 2 * line_step, "   ".join(row3_parts), size=legend_font * 0.92, fill=LEGEND_ACCENT)

    view = {"min_x": 0.0, "min_y": 0.0, "max_x": canvas_w, "max_y": canvas_h, "width": canvas_w, "height": canvas_h}
    ET.indent(svg, space="  ")
    return ET.tostring(svg, encoding="unicode"), view


def export_footprint_preview_image(
    project_dir: str,
    ref: str,
    *,
    output_path: str = "",
    png_min_pixels: int = 1600,
    margin_mm: float = 2.5,
    use_kicad_renderer: bool = True,
) -> dict[str, Any]:
    """Export annotated footprint preview SVG and PNG for a PCB reference."""
    document, load_error = pcb_model.load_pcb_document(project_dir)
    if document is None:
        return {"error": load_error}

    footprint = pcb_model.get_component_footprint(document, ref)
    if "error" in footprint:
        return footprint

    if use_kicad_renderer:
        from kicad_mcp.review.footprint_kicad_export import export_component_footprint_preview_native

        native = export_component_footprint_preview_native(
            project_dir,
            footprint,
            output_path=output_path,
            ref=ref,
        )
        if "error" not in native:
            return native
        footprint["native_preview_error"] = native.get("error")

    dimensions = analyze_footprint_dimensions(footprint)
    svg_content, view = render_footprint_preview_svg(
        footprint,
        dimensions,
        margin_mm=margin_mm,
    )

    safe_ref = re.sub(r"[^\w.-]+", "_", ref.strip()) or "component"
    default_rel = os.path.join("mcp_exports", "review", "footprints", f"{safe_ref}_preview.svg")
    default_output = os.path.normpath(os.path.join(project_dir, default_rel))
    svg_file = resolve_output_path(project_dir, output_path.strip(), default_output)
    svg_path = Path(svg_file)
    svg_path.parent.mkdir(parents=True, exist_ok=True)
    svg_path.write_text(svg_content, encoding="utf-8")

    png_path = svg_path.with_suffix(".png")
    png_file = write_region_png(
        str(svg_path),
        float(view["width"]),
        float(view["height"]),
        min_pixels=png_min_pixels,
        png_path=str(png_path),
    )

    result: dict[str, Any] = {
        "ref": footprint.get("ref"),
        "value": footprint.get("value"),
        "footprint": footprint.get("footprint"),
        "side": footprint.get("side"),
        "dimensions": dimensions,
        "svg_path": str(svg_path),
        "region_mm": {"width": round(view["width"], 4), "height": round(view["height"], 4)},
    }
    if png_file:
        result["png_path"] = png_file
        result["png_uri"] = Path(png_file).resolve().as_uri()
        result["preview_link"] = f"[{Path(png_file).name}]({Path(png_file).resolve().as_uri()})"
    else:
        result["png_error"] = (
            "PNG rasterization failed. Install the `cairosvg` package "
            "(included in kicad-mcp dependencies) and restart the MCP server."
        )
    return result
