"""Render cropped PCB region SVG from parsed board geometry.

Author: Henry Dang
Email: phuongminh.dang@gmail.com
"""

from __future__ import annotations

import hashlib
import os
import xml.etree.ElementTree as ET
from typing import Any

from kicad_mcp import pcb_model
from kicad_mcp.pcb_model import PcbDocument
from kicad_mcp.schematic_pages import resolve_output_path

DEFAULT_LAYERS = ("F.Cu", "Edge.Cuts")
SILKSCREEN_LAYERS = ("F.Silkscreen", "B.Silkscreen")
DEFAULT_MARKER_SIZE_MM = 0.4
DEFAULT_MARKER_CROSS_MM = 0.7

NET_COLORS = {
    "GND": "#6B5B45",
    "": "#666666",
}

LAYER_COLORS = {
    "Edge.Cuts": "#E0C040",
    "F.Silkscreen": "#E8E8E8",
    "B.Silkscreen": "#C8C8C8",
    "F.Fab": "#808080",
    "B.Fab": "#707070",
    "F.CrtYd": "#008080",
    "B.CrtYd": "#006868",
}


def _distance_mm(x1: float, y1: float, x2: float, y2: float) -> float:
    return ((x1 - x2) ** 2 + (y1 - y2) ** 2) ** 0.5


def _collect_points_near(
    document: PcbDocument,
    center_x_mm: float,
    center_y_mm: float,
    search_radius_mm: float,
    *,
    highlight_net: str = "",
    layer_filter: set[str] | None = None,
) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = [(center_x_mm, center_y_mm)]
    radius = max(0.5, float(search_radius_mm))

    def near(x: float, y: float) -> bool:
        return _distance_mm(x, y, center_x_mm, center_y_mm) <= radius

    def layer_ok(layer: str | None) -> bool:
        if not layer_filter or not layer:
            return layer_filter is None
        return layer in layer_filter

    for footprint in document.footprints:
        fp_box = footprint.get("bounding_box_mm")
        if fp_box:
            cx = (fp_box["min_x"] + fp_box["max_x"]) / 2.0
            cy = (fp_box["min_y"] + fp_box["max_y"]) / 2.0
            if near(cx, cy):
                for corner in (
                    (fp_box["min_x"], fp_box["min_y"]),
                    (fp_box["max_x"], fp_box["max_y"]),
                ):
                    points.append(corner)
        for pad in footprint.get("pads", []):
            if layer_filter:
                pad_layers = {str(layer) for layer in pad.get("layers", [])}
                if not pad_layers.intersection(layer_filter):
                    continue
            center = pad.get("center_mm", {}).get("absolute") or {}
            cx = float(center.get("x", 0.0))
            cy = float(center.get("y", 0.0))
            if not near(cx, cy):
                continue
            points.append((cx, cy))
            size = pad.get("size_mm") or {}
            half_w = float(size.get("x", 0.0)) / 2.0
            half_h = float(size.get("y", half_w)) / 2.0
            points.extend(
                [
                    (cx - half_w, cy - half_h),
                    (cx + half_w, cy + half_h),
                ]
            )

    for segment in document.segments:
        layer = str(segment.get("layer") or "")
        if layer_filter and not layer_ok(layer):
            continue
        start = segment.get("start_mm") or {}
        end = segment.get("end_mm") or {}
        x1 = float(start.get("x", 0.0))
        y1 = float(start.get("y", 0.0))
        x2 = float(end.get("x", 0.0))
        y2 = float(end.get("y", 0.0))
        net_name = str(segment.get("net") or "")
        mid_x = (x1 + x2) / 2.0
        mid_y = (y1 + y2) / 2.0
        include = near(x1, y1) or near(x2, y2) or near(mid_x, mid_y)
        if highlight_net and net_name == highlight_net:
            include = include or _distance_mm(mid_x, mid_y, center_x_mm, center_y_mm) <= radius * 1.5
        if include:
            points.extend([(x1, y1), (x2, y2)])

    for via in document.vias:
        if layer_filter:
            via_layers = {str(layer) for layer in via.get("layers", [])}
            if not via_layers.intersection(layer_filter):
                continue
        center = via.get("center_mm") or {}
        cx = float(center.get("x", 0.0))
        cy = float(center.get("y", 0.0))
        if near(cx, cy):
            size = float(via.get("size_mm") or 0.0) / 2.0
            points.append((cx, cy))
            if size:
                points.extend([(cx - size, cy), (cx + size, cy), (cx, cy - size), (cx, cy + size)])

    return points


def auto_zoom_window(
    document: PcbDocument,
    center_x_mm: float,
    center_y_mm: float,
    *,
    search_radius_mm: float = 5.0,
    padding_mm: float = 1.0,
    min_window_mm: float = 4.0,
    max_window_mm: float = 12.0,
    highlight_net: str = "",
    layers: list[str] | None = None,
) -> tuple[float, float, float, float]:
    """Return center_x, center_y, width_mm, height_mm fitted to nearby geometry."""
    layer_filter = {layer.strip() for layer in (layers or list(DEFAULT_LAYERS)) if layer.strip()}
    points = _collect_points_near(
        document,
        center_x_mm,
        center_y_mm,
        search_radius_mm,
        highlight_net=highlight_net,
        layer_filter=layer_filter,
    )
    max_x_dist = max(abs(x - center_x_mm) for x, _ in points)
    max_y_dist = max(abs(y - center_y_mm) for _, y in points)
    pad = max(0.0, float(padding_mm))
    width = max(float(min_window_mm), 2.0 * (max_x_dist + pad))
    height = max(float(min_window_mm), 2.0 * (max_y_dist + pad))
    cap = max(float(max_window_mm), float(min_window_mm))
    width = min(width, cap)
    height = min(height, cap)
    return center_x_mm, center_y_mm, width, height


def _resolve_layers(layers: list[str] | None, include_silkscreen: bool) -> list[str]:
    layer_list = [layer.strip() for layer in (layers or list(DEFAULT_LAYERS)) if layer.strip()]
    if include_silkscreen:
        for silk_layer in SILKSCREEN_LAYERS:
            if silk_layer not in layer_list:
                layer_list.append(silk_layer)
    else:
        layer_list = [layer for layer in layer_list if layer not in SILKSCREEN_LAYERS]
    return layer_list or list(DEFAULT_LAYERS)


def region_bbox(
    center_x_mm: float,
    center_y_mm: float,
    width_mm: float,
    height_mm: float,
) -> dict[str, float]:
    half_w = width_mm / 2.0
    half_h = height_mm / 2.0
    return {
        "min_x": center_x_mm - half_w,
        "min_y": center_y_mm - half_h,
        "max_x": center_x_mm + half_w,
        "max_y": center_y_mm + half_h,
        "width": width_mm,
        "height": height_mm,
    }


def _boxes_overlap(left: dict[str, float] | None, right: dict[str, float]) -> bool:
    if left is None:
        return True
    return not (
        left["max_x"] < right["min_x"]
        or left["min_x"] > right["max_x"]
        or left["max_y"] < right["min_y"]
        or left["min_y"] > right["max_y"]
    )


def _point_in_region(x: float, y: float, region: dict[str, float]) -> bool:
    return region["min_x"] <= x <= region["max_x"] and region["min_y"] <= y <= region["max_y"]


def _segment_intersects_region(segment: dict[str, Any], region: dict[str, float]) -> bool:
    start = segment.get("start_mm") or {}
    end = segment.get("end_mm") or {}
    x1 = float(start.get("x", 0.0))
    y1 = float(start.get("y", 0.0))
    x2 = float(end.get("x", 0.0))
    y2 = float(end.get("y", 0.0))
    if _point_in_region(x1, y1, region) or _point_in_region(x2, y2, region):
        return True
    seg_box = {
        "min_x": min(x1, x2),
        "min_y": min(y1, y2),
        "max_x": max(x1, x2),
        "max_y": max(y1, y2),
    }
    return _boxes_overlap(seg_box, region)


def _net_color(net_name: str | None, highlight_net: str) -> str:
    name = str(net_name or "")
    if highlight_net and name == highlight_net:
        return "#00E676"
    if name in NET_COLORS:
        return NET_COLORS[name]
    digest = hashlib.sha256(name.encode("utf-8")).hexdigest()
    hue = int(digest[:2], 16) / 255.0 * 300.0
    saturation = 55 + (int(digest[2:4], 16) % 25)
    lightness = 45 + (int(digest[4:6], 16) % 20)
    return _hsl_to_hex(hue, saturation, lightness)


def _hsl_to_hex(h: float, s: float, l: float) -> str:
    s /= 100.0
    l /= 100.0
    c = (1.0 - abs(2.0 * l - 1.0)) * s
    x = c * (1.0 - abs((h / 60.0) % 2.0 - 1.0))
    m = l - c / 2.0
    if h < 60:
        r, g, b = c, x, 0.0
    elif h < 120:
        r, g, b = x, c, 0.0
    elif h < 180:
        r, g, b = 0.0, c, x
    elif h < 240:
        r, g, b = 0.0, x, c
    elif h < 300:
        r, g, b = x, 0.0, c
    else:
        r, g, b = c, 0.0, x
    return "#{:02X}{:02X}{:02X}".format(
        int((r + m) * 255),
        int((g + m) * 255),
        int((b + m) * 255),
    )


def _layer_stroke(layer: str | None) -> str:
    if not layer:
        return "#CCCCCC"
    return LAYER_COLORS.get(layer, "#BBBBBB")


def _add_polygon(
    parent: ET.Element,
    points: list[dict[str, float]],
    *,
    fill: str,
    stroke: str,
    stroke_width: float,
    fill_opacity: str | None = None,
) -> None:
    if len(points) < 2:
        return
    attrs: dict[str, str] = {
        "points": " ".join(f"{point['x']},{point['y']}" for point in points),
        "fill": fill,
        "stroke": stroke,
        "stroke-width": str(stroke_width),
    }
    if fill_opacity is not None:
        attrs["fill-opacity"] = fill_opacity
    ET.SubElement(parent, "polygon", attrs)


def _add_polyline(
    parent: ET.Element,
    points: list[dict[str, float]],
    *,
    stroke: str,
    stroke_width: float,
    closed: bool = False,
) -> None:
    if len(points) < 2:
        return
    tag = "polygon" if closed else "polyline"
    attrs = {
        "points": " ".join(f"{point['x']},{point['y']}" for point in points),
        "fill": "none" if not closed else stroke,
        "stroke": stroke,
        "stroke-width": str(stroke_width),
    }
    if tag == "polyline":
        attrs["fill"] = "none"
    ET.SubElement(parent, tag, attrs)


def _add_line(
    parent: ET.Element,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    *,
    stroke: str,
    stroke_width: float,
) -> None:
    ET.SubElement(
        parent,
        "line",
        {
            "x1": str(x1),
            "y1": str(y1),
            "x2": str(x2),
            "y2": str(y2),
            "stroke": stroke,
            "stroke-width": str(stroke_width),
        },
    )


def _add_circle(
    parent: ET.Element,
    cx: float,
    cy: float,
    radius: float,
    *,
    fill: str,
    stroke: str,
    stroke_width: float,
) -> None:
    ET.SubElement(
        parent,
        "circle",
        {
            "cx": str(cx),
            "cy": str(cy),
            "r": str(radius),
            "fill": fill,
            "stroke": stroke,
            "stroke-width": str(stroke_width),
        },
    )


def _add_pad(
    parent: ET.Element,
    pad: dict[str, Any],
    *,
    layer_filter: set[str],
    highlight_net: str,
) -> None:
    pad_layers = {str(layer) for layer in pad.get("layers", [])}
    if layer_filter and not pad_layers.intersection(layer_filter):
        return
    center = pad.get("center_mm", {}).get("absolute") or {}
    cx = float(center.get("x", 0.0))
    cy = float(center.get("y", 0.0))
    size = pad.get("size_mm") or {}
    width = float(size.get("x", 0.0))
    height = float(size.get("y", width))
    rotation = float(pad.get("rotation_deg") or 0.0)
    net_name = str(pad.get("net") or "")
    fill = _net_color(net_name, highlight_net)
    shape = str(pad.get("shape") or "rect")
    pad_type = str(pad.get("type") or "")

    if shape == "circle" or (width == height and shape in {"roundrect", "circle"}):
        radius = max(width, height) / 2.0
        _add_circle(parent, cx, cy, radius, fill=fill, stroke="#101010", stroke_width=0.01)
        if pad_type == "thru_hole":
            drill = min(width, height) * 0.45
            _add_circle(parent, cx, cy, drill / 2.0, fill="#262626", stroke="none", stroke_width=0.0)
        return

    rect = ET.SubElement(
        parent,
        "rect",
        {
            "x": str(cx - width / 2.0),
            "y": str(cy - height / 2.0),
            "width": str(width),
            "height": str(height),
            "fill": fill,
            "stroke": "#101010",
            "stroke-width": "0.01",
        },
    )
    if rotation:
        rect.set("transform", f"rotate({rotation} {cx} {cy})")


def render_pcb_region_svg(
    document: PcbDocument,
    *,
    center_x_mm: float,
    center_y_mm: float,
    width_mm: float = 10.0,
    height_mm: float = 10.0,
    layers: list[str] | None = None,
    highlight_net: str = "",
    marker: bool = True,
    marker_label: str = "",
    marker_size_mm: float = DEFAULT_MARKER_SIZE_MM,
    auto_zoom: bool = False,
    search_radius_mm: float = 5.0,
    padding_mm: float = 1.0,
    min_window_mm: float = 4.0,
    max_window_mm: float = 12.0,
    include_silkscreen: bool = False,
) -> tuple[str, dict[str, Any]]:
    layer_filter = set(_resolve_layers(layers, include_silkscreen))
    show_silkscreen = bool(layer_filter.intersection(SILKSCREEN_LAYERS))
    auto_zoom_applied = False
    if auto_zoom:
        center_x_mm, center_y_mm, width_mm, height_mm = auto_zoom_window(
            document,
            center_x_mm,
            center_y_mm,
            search_radius_mm=search_radius_mm,
            padding_mm=padding_mm,
            min_window_mm=min_window_mm,
            max_window_mm=min(width_mm, height_mm, max_window_mm),
            highlight_net=highlight_net,
            layers=list(layer_filter),
        )
        auto_zoom_applied = True

    region = region_bbox(center_x_mm, center_y_mm, width_mm, height_mm)

    svg = ET.Element(
        "svg",
        {
            "xmlns": "http://www.w3.org/2000/svg",
            "viewBox": f"{region['min_x']} {region['min_y']} {region['width']} {region['height']}",
            "width": f"{region['width']}mm",
            "height": f"{region['height']}mm",
        },
    )
    ET.SubElement(
        svg,
        "rect",
        {
            "x": str(region["min_x"]),
            "y": str(region["min_y"]),
            "width": str(region["width"]),
            "height": str(region["height"]),
            "fill": "#262626",
        },
    )

    zones_group = ET.SubElement(svg, "g", {"id": "zones"})
    tracks_group = ET.SubElement(svg, "g", {"id": "tracks"})
    vias_group = ET.SubElement(svg, "g", {"id": "vias"})
    pads_group = ET.SubElement(svg, "g", {"id": "pads"})
    footprints_group = ET.SubElement(svg, "g", {"id": "footprints"})
    board_group = ET.SubElement(svg, "g", {"id": "board-graphics"})
    marker_group = ET.SubElement(svg, "g", {"id": "marker"})

    zone_count = 0
    segment_count = 0
    via_count = 0
    pad_count = 0
    footprint_count = 0
    graphic_count = 0

    for zone in document.zones:
        layer = str(zone.get("layer") or "")
        if layer not in layer_filter:
            continue
        zone_box = zone.get("bounding_box_mm")
        if zone_box and not _boxes_overlap(zone_box, region):
            continue
        points = zone.get("outline_points") or []
        if not points:
            for island in zone.get("filled_island_outlines") or []:
                if island:
                    points = island
                    break
        if not points:
            continue
        net_name = str(zone.get("net") or "")
        _add_polygon(
            zones_group,
            points,
            fill=_net_color(net_name, highlight_net),
            stroke=_net_color(net_name, highlight_net),
            stroke_width=0.02,
            fill_opacity="0.35",
        )
        zone_count += 1

    for segment in document.segments:
        layer = str(segment.get("layer") or "")
        if layer not in layer_filter:
            continue
        if not _segment_intersects_region(segment, region):
            continue
        start = segment.get("start_mm") or {}
        end = segment.get("end_mm") or {}
        net_name = str(segment.get("net") or "")
        width = float(segment.get("width_mm") or 0.1)
        _add_line(
            tracks_group,
            float(start.get("x", 0.0)),
            float(start.get("y", 0.0)),
            float(end.get("x", 0.0)),
            float(end.get("y", 0.0)),
            stroke=_net_color(net_name, highlight_net),
            stroke_width=max(width, 0.02),
        )
        segment_count += 1

    for via in document.vias:
        center = via.get("center_mm") or {}
        cx = float(center.get("x", 0.0))
        cy = float(center.get("y", 0.0))
        if not _point_in_region(cx, cy, region):
            continue
        via_layers = {str(layer) for layer in via.get("layers", [])}
        if layer_filter and not via_layers.intersection(layer_filter):
            continue
        size = float(via.get("size_mm") or 0.0)
        net_name = str(via.get("net") or "")
        _add_circle(
            vias_group,
            cx,
            cy,
            size / 2.0,
            fill=_net_color(net_name, highlight_net),
            stroke="#101010",
            stroke_width=0.01,
        )
        drill = float(via.get("drill_mm") or 0.0)
        if drill > 0:
            _add_circle(vias_group, cx, cy, drill / 2.0, fill="#262626", stroke="none", stroke_width=0.0)
        via_count += 1

    for footprint in document.footprints:
        fp_box = footprint.get("bounding_box_mm")
        if fp_box and not _boxes_overlap(fp_box, region):
            continue
        footprint_count += 1
        ref = str(footprint.get("ref") or "")
        for pad in footprint.get("pads", []):
            center = pad.get("center_mm", {}).get("absolute") or {}
            cx = float(center.get("x", 0.0))
            cy = float(center.get("y", 0.0))
            if not _point_in_region(cx, cy, region):
                pad_size = pad.get("size_mm") or {}
                half_w = float(pad_size.get("x", 0.0)) / 2.0
                half_h = float(pad_size.get("y", half_w)) / 2.0
                pad_box = {
                    "min_x": cx - half_w,
                    "min_y": cy - half_h,
                    "max_x": cx + half_w,
                    "max_y": cy + half_h,
                }
                if not _boxes_overlap(pad_box, region):
                    continue
            _add_pad(pads_group, pad, layer_filter=layer_filter, highlight_net=highlight_net)
            pad_count += 1

        for graphic in footprint.get("graphics", []):
            layer = str(graphic.get("layer") or "")
            if layer not in layer_filter:
                continue
            points = graphic.get("points") or []
            if not points:
                continue
            graphic_box = graphic.get("bounding_box_mm")
            if graphic_box and not _boxes_overlap(graphic_box, region):
                continue
            width = float(graphic.get("width_mm") or 0.05)
            _add_polyline(
                footprints_group,
                points,
                stroke=_layer_stroke(layer),
                stroke_width=max(width, 0.02),
                closed=str(graphic.get("type")) in {"fp_poly", "fp_rect"},
            )

        origin = footprint.get("position_mm") or {}
        ox = float(origin.get("x", 0.0))
        oy = float(origin.get("y", 0.0))
        if ref and show_silkscreen and _point_in_region(ox, oy, region):
            label_size = min(1.2, max(0.55, min(width_mm, height_mm) * 0.09))
            label = ET.SubElement(
                footprints_group,
                "text",
                {
                    "x": str(ox),
                    "y": str(oy - 0.3),
                    "fill": "#FFFFFF",
                    "font-size": str(label_size),
                    "font-family": "sans-serif",
                    "text-anchor": "middle",
                },
            )
            label.text = ref

    for graphic in document.graphics:
        layer = str(graphic.get("layer") or "")
        if layer not in layer_filter:
            continue
        points = graphic.get("points") or []
        if not points:
            continue
        graphic_box = graphic.get("bounding_box_mm")
        if graphic_box and not _boxes_overlap(graphic_box, region):
            continue
        width = float(graphic.get("width_mm") or 0.05)
        _add_polyline(
            board_group,
            points,
            stroke=_layer_stroke(layer),
            stroke_width=max(width, 0.05),
            closed=str(graphic.get("type")) == "gr_poly",
        )
        graphic_count += 1

    if marker:
        marker_radius = max(0.15, float(marker_size_mm))
        cross = max(0.3, float(DEFAULT_MARKER_CROSS_MM))
        label_size = min(0.55, max(0.35, min(width_mm, height_mm) * 0.07))
        _add_circle(
            marker_group,
            center_x_mm,
            center_y_mm,
            marker_radius,
            fill="none",
            stroke="#FFFFFF",
            stroke_width=0.04,
        )
        ET.SubElement(
            marker_group,
            "circle",
            {
                "cx": str(center_x_mm),
                "cy": str(center_y_mm),
                "r": str(marker_radius),
                "fill": "#FF1744",
                "fill-opacity": "0.35",
                "stroke": "#FF1744",
                "stroke-width": "0.06",
            },
        )
        _add_line(
            marker_group,
            center_x_mm - cross,
            center_y_mm,
            center_x_mm + cross,
            center_y_mm,
            stroke="#FF1744",
            stroke_width=0.05,
        )
        _add_line(
            marker_group,
            center_x_mm,
            center_y_mm - cross,
            center_x_mm,
            center_y_mm + cross,
            stroke="#FF1744",
            stroke_width=0.05,
        )
        if marker_label:
            text = ET.SubElement(
                marker_group,
                "text",
                {
                    "x": str(center_x_mm),
                    "y": str(center_y_mm - cross - 0.15),
                    "fill": "#FF8A80",
                    "font-size": str(label_size),
                    "font-family": "sans-serif",
                    "text-anchor": "middle",
                },
            )
            text.text = marker_label

    metadata = {
        "pcb_file": os.path.basename(document.path),
        "center_mm": {"x": round(center_x_mm, 4), "y": round(center_y_mm, 4)},
        "region_mm": {key: round(value, 4) for key, value in region.items()},
        "layers": sorted(layer_filter),
        "include_silkscreen": include_silkscreen,
        "highlight_net": highlight_net or None,
        "auto_zoom": auto_zoom_applied,
        "auto_zoom_params": {
            "search_radius_mm": search_radius_mm,
            "padding_mm": padding_mm,
            "min_window_mm": min_window_mm,
            "max_window_mm": max_window_mm,
        } if auto_zoom_applied else None,
        "counts": {
            "zones": zone_count,
            "segments": segment_count,
            "vias": via_count,
            "pads": pad_count,
            "footprints": footprint_count,
            "board_graphics": graphic_count,
        },
    }
    svg_text = ET.tostring(svg, encoding="unicode", xml_declaration=True)
    return svg_text, metadata


def default_region_output_path(
    project_dir: str,
    center_x_mm: float,
    center_y_mm: float,
    *,
    auto_zoom: bool,
    width_mm: float,
    height_mm: float,
) -> str:
    """Default SVG path under ``<project_dir>/mcp_exports/review/``."""
    export_dir = os.path.join(project_dir, "mcp_exports", "review")
    tag = "auto" if auto_zoom else f"w{width_mm:.1f}_h{height_mm:.1f}"
    filename = f"region_x{center_x_mm:.3f}_y{center_y_mm:.3f}_{tag}.svg"
    return os.path.normpath(os.path.join(export_dir, filename))


def export_pcb_region_svg(
    project_dir: str,
    *,
    center_x_mm: float,
    center_y_mm: float,
    width_mm: float = 10.0,
    height_mm: float = 10.0,
    layers: list[str] | None = None,
    highlight_net: str = "",
    marker: bool = True,
    marker_label: str = "",
    marker_size_mm: float = DEFAULT_MARKER_SIZE_MM,
    auto_zoom: bool = False,
    search_radius_mm: float = 5.0,
    padding_mm: float = 1.0,
    min_window_mm: float = 4.0,
    max_window_mm: float = 12.0,
    include_silkscreen: bool = False,
    output_path: str = "",
) -> dict[str, Any]:
    document, load_error = pcb_model.load_pcb_document(project_dir)
    if document is None:
        return {"error": load_error}

    resolved_layers = _resolve_layers(layers, include_silkscreen)
    render_width = width_mm
    render_height = height_mm
    if auto_zoom:
        cap = min(width_mm, height_mm, max_window_mm)
        _, _, render_width, render_height = auto_zoom_window(
            document,
            center_x_mm,
            center_y_mm,
            search_radius_mm=search_radius_mm,
            padding_mm=padding_mm,
            min_window_mm=min_window_mm,
            max_window_mm=cap,
            highlight_net=highlight_net,
            layers=resolved_layers,
        )

    svg_text, metadata = render_pcb_region_svg(
        document,
        center_x_mm=center_x_mm,
        center_y_mm=center_y_mm,
        width_mm=render_width,
        height_mm=render_height,
        layers=resolved_layers,
        highlight_net=highlight_net,
        marker=marker,
        marker_label=marker_label,
        marker_size_mm=marker_size_mm,
        auto_zoom=False,
        include_silkscreen=include_silkscreen,
    )
    metadata["auto_zoom"] = auto_zoom
    if auto_zoom:
        metadata["requested_window_mm"] = {
            "width": round(width_mm, 4),
            "height": round(height_mm, 4),
        }

    export_project_dir = os.path.dirname(document.path)
    default_output = default_region_output_path(
        export_project_dir,
        center_x_mm,
        center_y_mm,
        auto_zoom=auto_zoom,
        width_mm=width_mm,
        height_mm=height_mm,
    )
    resolved_output = resolve_output_path(export_project_dir, output_path, default_output)

    with open(resolved_output, "w", encoding="utf-8") as handle:
        handle.write(svg_text)

    return {
        **metadata,
        "project_dir": export_project_dir,
        "output_path": resolved_output,
        "format": "svg",
    }


def write_region_png(
    svg_path: str,
    width_mm: float,
    height_mm: float,
    *,
    min_pixels: int = 1400,
    png_path: str = "",
) -> str | None:
    """Rasterize SVG so the shorter side is at least `min_pixels` px."""
    try:
        import cairosvg
    except ImportError:
        return None

    short_side_mm = max(0.1, min(float(width_mm), float(height_mm)))
    scale = max(1.0, float(min_pixels) / short_side_mm)
    resolved_png = png_path or os.path.splitext(svg_path)[0] + ".png"
    png_dir = os.path.dirname(resolved_png)
    if png_dir:
        os.makedirs(png_dir, exist_ok=True)
    cairosvg.svg2png(url=svg_path, write_to=resolved_png, scale=scale)
    return resolved_png


def export_pcb_region_image(
    project_dir: str,
    *,
    center_x_mm: float,
    center_y_mm: float,
    width_mm: float = 12.0,
    height_mm: float = 12.0,
    layers: list[str] | None = None,
    highlight_net: str = "",
    marker: bool = True,
    marker_label: str = "",
    marker_size_mm: float = DEFAULT_MARKER_SIZE_MM,
    auto_zoom: bool = True,
    search_radius_mm: float = 4.0,
    padding_mm: float = 0.8,
    min_window_mm: float = 6.0,
    max_window_mm: float = 12.0,
    include_silkscreen: bool = False,
    output_path: str = "",
    png_min_pixels: int = 1400,
    png_path: str = "",
) -> dict[str, Any]:
    result = export_pcb_region_svg(
        project_dir,
        center_x_mm=center_x_mm,
        center_y_mm=center_y_mm,
        width_mm=width_mm,
        height_mm=height_mm,
        layers=layers,
        highlight_net=highlight_net,
        marker=marker,
        marker_label=marker_label,
        marker_size_mm=marker_size_mm,
        auto_zoom=auto_zoom,
        search_radius_mm=search_radius_mm,
        padding_mm=padding_mm,
        min_window_mm=min_window_mm,
        max_window_mm=max_window_mm,
        include_silkscreen=include_silkscreen,
        output_path=output_path,
    )
    if "error" in result:
        return result

    region = result.get("region_mm") or {}
    png_file = write_region_png(
        result["output_path"],
        float(region.get("width", width_mm)),
        float(region.get("height", height_mm)),
        min_pixels=png_min_pixels,
        png_path=png_path,
    )
    if png_file:
        result["png_path"] = png_file
        result["png_min_pixels"] = png_min_pixels
    else:
        result["png_error"] = (
            "PNG rasterization failed. Install the `cairosvg` package "
            "(included in kicad-mcp dependencies) and restart the MCP server."
        )
    return result
