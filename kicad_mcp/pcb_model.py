"""Structured PCB model parsing and analysis helpers.

Author: Henry Dang
Email: phuongminh.dang@gmail.com
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from typing import Any

from kicad_mcp.project import find_project_files
from kicad_mcp.sexpr import (
    atom_value,
    atom_values,
    coerce_float,
    find_child,
    find_children,
    parse_sexpr,
    sexpr_atoms,
    sexpr_symbol,
)


@dataclass
class PcbDocument:
  path: str
  root: list[Any]
  net_names: dict[int, str] = field(default_factory=dict)
  registered_net_names: set[str] = field(default_factory=set)
  footprints: list[dict[str, Any]] = field(default_factory=list)
  segments: list[dict[str, Any]] = field(default_factory=list)
  vias: list[dict[str, Any]] = field(default_factory=list)
  zones: list[dict[str, Any]] = field(default_factory=list)
  graphics: list[dict[str, Any]] = field(default_factory=list)

  def all_net_names(self) -> set[str]:
    return _collect_used_net_names(self)


def load_pcb_document(project_dir: str) -> tuple[PcbDocument | None, str | None]:
  paths = find_project_files(project_dir)
  if not paths.pcb_file:
    return None, "Error: No layout file (*.kicad_pcb) discovered in this directory."
  try:
    with open(paths.pcb_file, encoding="utf-8") as handle:
      content = handle.read()
  except OSError as exc:
    return None, f"Failed to read PCB file: {exc}"

  try:
    root = parse_sexpr(content)
  except ValueError as exc:
    return None, f"Failed to parse PCB S-expression: {exc}"

  document = PcbDocument(path=paths.pcb_file, root=root)
  document.net_names, document.registered_net_names = _parse_nets(root)
  document.footprints = [_parse_footprint(node, document.net_names) for node in find_children(root, "footprint")]
  document.segments = [_parse_segment(node, document.net_names) for node in find_children(root, "segment")]
  document.vias = [_parse_via(node, document.net_names) for node in find_children(root, "via")]
  document.zones = [_parse_zone(node, document.net_names) for node in find_children(root, "zone")]
  document.graphics = _parse_board_graphics(root)
  document.registered_net_names = _collect_used_net_names(document)
  return document, None


def get_footprint_by_ref(document: PcbDocument, ref: str) -> dict[str, Any] | None:
  ref_upper = ref.upper()
  for footprint in document.footprints:
    if str(footprint.get("ref", "")).upper() == ref_upper:
      return footprint
  return None


def get_component_footprint(document: PcbDocument, ref: str) -> dict[str, Any]:
  footprint = get_footprint_by_ref(document, ref)
  if footprint is None:
    return {"error": f"Footprint reference `{ref}` was not found in the PCB layout."}
  return footprint


def get_component_placement(document: PcbDocument) -> list[dict[str, Any]]:
  placements: list[dict[str, Any]] = []
  for footprint in document.footprints:
    placements.append(
      {
        "ref": footprint.get("ref"),
        "value": footprint.get("value"),
        "footprint": footprint.get("footprint"),
        "layer": footprint.get("layer"),
        "side": footprint.get("side"),
        "position_mm": footprint.get("position_mm"),
        "rotation_deg": footprint.get("rotation_deg"),
        "dnp": footprint.get("dnp", False),
        "smd": footprint.get("smd", False),
        "through_hole": footprint.get("through_hole", False),
        "bounding_box_mm": footprint.get("bounding_box_mm"),
        "pad_count": len(footprint.get("pads", [])),
      }
    )
  placements.sort(key=lambda item: str(item.get("ref", "")))
  return placements


def get_board_geometry(
  document: PcbDocument,
  layers: list[str] | None = None,
  include_graphics: bool = True,
) -> dict[str, Any]:
  layer_filter = {layer.strip() for layer in layers} if layers else None

  def layer_allowed(layer: str | None) -> bool:
    if layer_filter is None:
      return True
    if layer is None:
      return False
    return layer in layer_filter

  segments = [segment for segment in document.segments if layer_allowed(segment.get("layer"))]
  vias = document.vias if layer_filter is None else [
    via for via in document.vias
    if any(layer_allowed(layer) for layer in via.get("layers", []))
  ]
  zones = [zone for zone in document.zones if layer_allowed(zone.get("layer"))]
  graphics = []
  if include_graphics:
    graphics = [item for item in document.graphics if layer_allowed(item.get("layer"))]

  return {
    "pcb_file": os.path.basename(document.path),
    "layer_filter": sorted(layer_filter) if layer_filter else None,
    "counts": {
      "footprints": len(document.footprints),
      "segments": len(segments),
      "vias": len(vias),
      "zones": len(zones),
      "board_graphics": len(graphics),
    },
    "segments": segments,
    "vias": vias,
    "zones": zones,
    "board_graphics": graphics,
  }


def analyze_copper_pours(document: PcbDocument) -> dict[str, Any]:
  pours: list[dict[str, Any]] = []
  for zone in document.zones:
    pours.append(
      {
        "net": zone.get("net"),
        "layer": zone.get("layer"),
        "filled": zone.get("filled", False),
        "fill_mode": zone.get("fill_mode"),
        "priority": zone.get("priority"),
        "min_thickness_mm": zone.get("min_thickness_mm"),
        "connect_pads_clearance_mm": zone.get("connect_pads_clearance_mm"),
        "thermal_gap_mm": zone.get("thermal_gap_mm"),
        "thermal_bridge_width_mm": zone.get("thermal_bridge_width_mm"),
        "hatch": zone.get("hatch"),
        "outline_points": zone.get("outline_points", []),
        "outline_point_count": len(zone.get("outline_points", [])),
        "filled_island_count": zone.get("filled_island_count", 0),
        "bounding_box_mm": zone.get("bounding_box_mm"),
      }
    )

  by_net: dict[str, list[dict[str, Any]]] = {}
  for pour in pours:
    net_name = str(pour.get("net") or "<no net>")
    by_net.setdefault(net_name, []).append(pour)

  return {
    "pcb_file": os.path.basename(document.path),
    "zone_count": len(pours),
    "filled_zone_count": sum(1 for pour in pours if pour.get("filled")),
    "unfilled_zone_count": sum(1 for pour in pours if not pour.get("filled")),
    "zones_by_net": {
      net: {
        "zone_count": len(items),
        "layers": sorted({str(item.get("layer")) for item in items}),
        "filled_zone_count": sum(1 for item in items if item.get("filled")),
      }
      for net, items in sorted(by_net.items())
    },
    "zones": pours,
  }


def analyze_net_routing(document: PcbDocument, net_name: str) -> dict[str, Any]:
  if net_name not in document.all_net_names():
    return {"error": f"Net `{net_name}` was not found in `{os.path.basename(document.path)}`."}

  net_id = _net_id_for_name(document.net_names, net_name)
  segments = [
    segment for segment in document.segments
    if segment.get("net") == net_name or (net_id is not None and segment.get("net_id") == net_id)
  ]
  vias = [
    via for via in document.vias
    if via.get("net") == net_name or via.get("net_id") == net_id
  ]
  zones = [zone for zone in document.zones if zone.get("net") == net_name]
  pads = _pads_for_net(document, net_name, net_id)

  total_length_mm = sum(segment.get("length_mm", 0.0) for segment in segments)
  widths = [segment.get("width_mm") for segment in segments if segment.get("width_mm") is not None]
  layers = sorted({segment.get("layer") for segment in segments if segment.get("layer")})

  connectivity = _analyze_net_connectivity(pads, segments, vias, zones)

  min_width = min(widths) if widths else None
  max_width = max(widths) if widths else None
  cross_section_sq_mils = (min_width * 39.3701 * 1.37) if min_width else None
  max_current_amps = None
  if cross_section_sq_mils:
    max_current_amps = round(0.048 * (10 ** 0.44) * (cross_section_sq_mils ** 0.725), 2)

  return {
    "net": net_name,
    "routing_status": "routed" if segments or vias or zones else "not_routed",
    "segments": {
      "count": len(segments),
      "total_length_mm": round(total_length_mm, 3),
      "layers": layers,
      "width_mm": {
        "min": round(min_width, 4) if min_width is not None else None,
        "max": round(max_width, 4) if max_width is not None else None,
      },
      "items": segments,
    },
    "vias": {
      "count": len(vias),
      "items": vias,
    },
    "copper_zones": {
      "count": len(zones),
      "items": [
        {
          "layer": zone.get("layer"),
          "filled": zone.get("filled", False),
          "outline_point_count": len(zone.get("outline_points", [])),
          "filled_island_count": zone.get("filled_island_count", 0),
        }
        for zone in zones
      ],
    },
    "pads": {
      "count": len(pads),
      "items": pads,
    },
    "connectivity": connectivity,
    "ipc2152_dc_estimate": {
      "assumptions": "1 oz external copper, 10 C rise, segments only",
      "max_current_amps_10c": max_current_amps,
    },
  }


def _collect_used_net_names(document: PcbDocument) -> set[str]:
  names = set(document.registered_net_names)
  names.update(document.net_names.values())
  for collection in (document.segments, document.vias, document.zones):
    for item in collection:
      net_name = item.get("net")
      if net_name:
        names.add(str(net_name))
  for footprint in document.footprints:
    for pad in footprint.get("pads", []):
      net_name = pad.get("net")
      if net_name:
        names.add(str(net_name))
  names.discard("")
  return names


def _parse_nets(root: list[Any]) -> tuple[dict[int, str], set[str]]:
  net_names: dict[int, str] = {}
  registered_names: set[str] = set()
  for node in find_children(root, "net"):
    values = atom_values(node)
    if not values:
      continue
    if len(values) == 1:
      value = values[0]
      if isinstance(value, int) or (isinstance(value, str) and value.isdigit()):
        net_names[int(value)] = ""
      else:
        registered_names.add(str(value))
      continue
    net_id = int(values[0])
    net_names[net_id] = str(values[1])
  return net_names, registered_names


def _net_id_for_name(net_names: dict[int, str], net_name: str) -> int | None:
  for net_id, name in net_names.items():
    if name == net_name:
      return net_id
  return None


def _parse_net_field(node: Any, net_names: dict[int, str]) -> tuple[int | None, str | None]:
  net_node = find_child(node, "net")
  if net_node is None:
    return None, None
  values = atom_values(net_node)
  if not values:
    return None, None
  if len(values) == 1:
    value = values[0]
    if isinstance(value, int) or (isinstance(value, str) and value.isdigit()):
      net_id = int(value)
      return net_id, net_names.get(net_id)
    net_name = str(value)
    return _net_id_for_name(net_names, net_name), net_name
  net_id = int(values[0])
  net_name = str(values[1]) if len(values) > 1 else net_names.get(net_id)
  return net_id, net_name


def _parse_at(node: Any) -> tuple[float, float, float]:
  at_node = find_child(node, "at")
  values = atom_values(at_node) if at_node else []
  x = coerce_float(values[0]) if len(values) >= 1 else 0.0
  y = coerce_float(values[1]) if len(values) >= 2 else 0.0
  rotation = coerce_float(values[2]) if len(values) >= 3 else 0.0
  return x, y, rotation


def _transform_point(x: float, y: float, origin_x: float, origin_y: float, rotation_deg: float) -> tuple[float, float]:
  radians = math.radians(rotation_deg)
  cosine = math.cos(radians)
  sine = math.sin(radians)
  rotated_x = x * cosine - y * sine + origin_x
  rotated_y = x * sine + y * cosine + origin_y
  return rotated_x, rotated_y


def _parse_xy_points(node: Any) -> list[dict[str, float]]:
  points: list[dict[str, float]] = []
  for xy in find_children(node, "xy"):
    values = atom_values(xy)
    if len(values) >= 2:
      points.append({"x": coerce_float(values[0]), "y": coerce_float(values[1])})
  return points


def _bounding_box(points: list[dict[str, float]]) -> dict[str, float] | None:
  if not points:
    return None
  xs = [point["x"] for point in points]
  ys = [point["y"] for point in points]
  return {
    "min_x": round(min(xs), 4),
    "min_y": round(min(ys), 4),
    "max_x": round(max(xs), 4),
    "max_y": round(max(ys), 4),
    "width": round(max(xs) - min(xs), 4),
    "height": round(max(ys) - min(ys), 4),
  }


def _footprint_properties(footprint_node: list[Any]) -> dict[str, str]:
  properties: dict[str, str] = {}
  for child in footprint_node[1:]:
    if not isinstance(child, list) or not child:
      continue
    if child[0] == "property":
      values = atom_values(child)
      if len(values) >= 2:
        properties[str(values[0])] = str(values[1])
    if child[0] == "fp_text" and len(child) >= 3:
      text_type = str(child[1])
      if text_type in {"reference", "value"} and isinstance(child[2], str):
        properties[text_type] = child[2]
  return properties


def _parse_footprint(footprint_node: list[Any], net_names: dict[int, str]) -> dict[str, Any]:
  origin_x, origin_y, rotation = _parse_at(footprint_node)
  properties = _footprint_properties(footprint_node)
  ref = properties.get("Reference") or properties.get("reference", "")
  value = properties.get("Value") or properties.get("value", "")
  layer_node = find_child(footprint_node, "layer")
  layer = str(atom_value(layer_node, "F.Cu")) if layer_node else "F.Cu"
  attrs = [str(value) for value in atom_values(find_child(footprint_node, "attr") or [])]
  side = "bottom" if layer == "B.Cu" else "front"
  dnp = "dnp" in attrs

  pads: list[dict[str, Any]] = []
  graphics: list[dict[str, Any]] = []
  abs_points: list[dict[str, float]] = []

  for child in footprint_node[1:]:
    if not isinstance(child, list) or not child:
      continue
    symbol = child[0]
    if symbol == "pad":
      pads.append(_parse_pad(child, net_names, origin_x, origin_y, rotation))
      center = pads[-1]["center_mm"]["absolute"]
      abs_points.append(center)
      size = pads[-1]["size_mm"]
      half_w = size["x"] / 2
      half_h = size["y"] / 2
      abs_points.extend(
        [
          {"x": center["x"] - half_w, "y": center["y"] - half_h},
          {"x": center["x"] + half_w, "y": center["y"] + half_h},
        ]
      )
    elif symbol in {"fp_line", "fp_arc", "fp_circle", "fp_rect", "fp_poly", "fp_curve"}:
      graphic = _parse_graphic(child, origin_x, origin_y, rotation)
      graphics.append(graphic)
      abs_points.extend(graphic.get("points", []))

  footprint_name = (
    str(footprint_node[1])
    if len(footprint_node) > 1 and isinstance(footprint_node[1], str)
    else sexpr_symbol(footprint_node)
  )

  return {
    "ref": ref,
    "value": value,
    "footprint": footprint_name,
    "layer": layer,
    "side": side,
    "position_mm": {"x": round(origin_x, 4), "y": round(origin_y, 4)},
    "rotation_deg": round(rotation, 3),
    "dnp": dnp,
    "smd": "smd" in attrs,
    "through_hole": "through_hole" in attrs,
    "pads": pads,
    "graphics": graphics,
    "courtyard": [graphic for graphic in graphics if graphic.get("layer", "").endswith(".CrtYd")],
    "fab_outline": [graphic for graphic in graphics if graphic.get("layer", "").endswith(".Fab")],
    "silkscreen": [graphic for graphic in graphics if graphic.get("layer", "").endswith(".SilkS")],
    "bounding_box_mm": _bounding_box(abs_points),
  }


def _parse_pad(
  pad_node: list[Any],
  net_names: dict[int, str],
  origin_x: float,
  origin_y: float,
  rotation: float,
) -> dict[str, Any]:
  values = atom_values(pad_node)
  number = str(values[0]) if values else ""
  pad_type = str(values[1]) if len(values) > 1 else ""
  pad_shape = str(values[2]) if len(values) > 2 else ""
  local_x, local_y, pad_rotation = _parse_at(pad_node)
  abs_x, abs_y = _transform_point(local_x, local_y, origin_x, origin_y, rotation)
  size_node = find_child(pad_node, "size")
  size_values = atom_values(size_node) if size_node else []
  size_x = coerce_float(size_values[0]) if len(size_values) >= 1 else 0.0
  size_y = coerce_float(size_values[1]) if len(size_values) >= 2 else size_x
  net_id, net_name = _parse_net_field(pad_node, net_names)
  layers = [str(layer) for layer in atom_values(find_child(pad_node, "layers") or [])]
  return {
    "number": number,
    "type": pad_type,
    "shape": pad_shape,
    "net": net_name,
    "net_id": net_id,
    "layers": layers,
    "center_mm": {
      "local": {"x": round(local_x, 4), "y": round(local_y, 4)},
      "absolute": {"x": round(abs_x, 4), "y": round(abs_y, 4)},
    },
    "rotation_deg": round(pad_rotation + rotation, 3),
    "size_mm": {"x": round(size_x, 4), "y": round(size_y, 4)},
    "roundrect_ratio": atom_value(find_child(pad_node, "roundrectrratio")),
    "solder_mask_margin_mm": atom_value(find_child(pad_node, "solder_mask_margin")),
    "solder_paste_margin_mm": atom_value(find_child(pad_node, "solder_paste_margin")),
    "clearance_mm": atom_value(find_child(pad_node, "clearance")),
  }


def _parse_graphic(node: list[Any], origin_x: float, origin_y: float, rotation: float) -> dict[str, Any]:
  symbol = sexpr_symbol(node) or ""
  layer = str(atom_value(find_child(node, "layer"), ""))
  width = coerce_float(atom_value(find_child(node, "width")), 0.0)
  points: list[dict[str, float]] = []

  if symbol == "fp_line":
    start = find_child(node, "start")
    end = find_child(node, "end")
    start_values = atom_values(start) if start else []
    end_values = atom_values(end) if end else []
    if len(start_values) >= 2 and len(end_values) >= 2:
      points.append(dict(zip(("x", "y"), _transform_point(coerce_float(start_values[0]), coerce_float(start_values[1]), origin_x, origin_y, rotation), strict=False)))
      points.append(dict(zip(("x", "y"), _transform_point(coerce_float(end_values[0]), coerce_float(end_values[1]), origin_x, origin_y, rotation), strict=False)))
  elif symbol == "fp_poly":
    for point in _parse_xy_points(find_child(node, "pts") or node):
      abs_x, abs_y = _transform_point(point["x"], point["y"], origin_x, origin_y, rotation)
      points.append({"x": round(abs_x, 4), "y": round(abs_y, 4)})
  elif symbol == "fp_circle":
    center = find_child(node, "center")
    end = find_child(node, "end")
    center_values = atom_values(center) if center else []
    end_values = atom_values(end) if end else []
    if len(center_values) >= 2:
      points.append(dict(zip(("x", "y"), _transform_point(coerce_float(center_values[0]), coerce_float(center_values[1]), origin_x, origin_y, rotation), strict=False)))
    if len(end_values) >= 2:
      points.append(dict(zip(("x", "y"), _transform_point(coerce_float(end_values[0]), coerce_float(end_values[1]), origin_x, origin_y, rotation), strict=False)))
  elif symbol == "fp_rect":
    start = find_child(node, "start")
    end = find_child(node, "end")
    start_values = atom_values(start) if start else []
    end_values = atom_values(end) if end else []
    if len(start_values) >= 2 and len(end_values) >= 2:
      x1, y1 = _transform_point(coerce_float(start_values[0]), coerce_float(start_values[1]), origin_x, origin_y, rotation)
      x2, y2 = _transform_point(coerce_float(end_values[0]), coerce_float(end_values[1]), origin_x, origin_y, rotation)
      points.extend(
        [
          {"x": round(x1, 4), "y": round(y1, 4)},
          {"x": round(x2, 4), "y": round(y1, 4)},
          {"x": round(x2, 4), "y": round(y2, 4)},
          {"x": round(x1, 4), "y": round(y2, 4)},
        ]
      )

  return {
    "type": symbol,
    "layer": layer,
    "width_mm": round(width, 4) if width else None,
    "points": points,
    "bounding_box_mm": _bounding_box(points),
  }


def _parse_segment(segment_node: list[Any], net_names: dict[int, str]) -> dict[str, Any]:
  start = atom_values(find_child(segment_node, "start") or [])
  end = atom_values(find_child(segment_node, "end") or [])
  x1 = coerce_float(start[0]) if len(start) >= 1 else 0.0
  y1 = coerce_float(start[1]) if len(start) >= 2 else 0.0
  x2 = coerce_float(end[0]) if len(end) >= 1 else 0.0
  y2 = coerce_float(end[1]) if len(end) >= 2 else 0.0
  width = coerce_float(atom_value(find_child(segment_node, "width")), 0.0)
  layer = str(atom_value(find_child(segment_node, "layer"), ""))
  net_id, net_name = _parse_net_field(segment_node, net_names)
  length = math.hypot(x2 - x1, y2 - y1)
  return {
    "start_mm": {"x": round(x1, 4), "y": round(y1, 4)},
    "end_mm": {"x": round(x2, 4), "y": round(y2, 4)},
    "width_mm": round(width, 4),
    "layer": layer,
    "net": net_name,
    "net_id": net_id,
    "length_mm": round(length, 4),
  }


def _parse_via(via_node: list[Any], net_names: dict[int, str]) -> dict[str, Any]:
  x, y, _rotation = _parse_at(via_node)
  size = coerce_float(atom_value(find_child(via_node, "size")), 0.0)
  drill = coerce_float(atom_value(find_child(via_node, "drill")), 0.0)
  layers = [str(layer) for layer in atom_values(find_child(via_node, "layers") or [])]
  net_id, net_name = _parse_net_field(via_node, net_names)
  return {
    "center_mm": {"x": round(x, 4), "y": round(y, 4)},
    "size_mm": round(size, 4),
    "drill_mm": round(drill, 4),
    "layers": layers,
    "net": net_name,
    "net_id": net_id,
  }


def _parse_zone(zone_node: list[Any], net_names: dict[int, str]) -> dict[str, Any]:
  net_id, net_name = _parse_net_field(zone_node, net_names)
  layer = str(atom_value(find_child(zone_node, "layer"), ""))
  fill_node = find_child(zone_node, "fill")
  fill_mode = atom_value(fill_node)
  filled = str(fill_mode).lower() not in {"no", "none", ""}
  priority = atom_value(find_child(zone_node, "priority"))
  min_thickness = coerce_float(atom_value(find_child(zone_node, "min_thickness")), 0.0)
  connect_pads = find_child(zone_node, "connect_pads")
  connect_clearance = coerce_float(atom_value(connect_pads), 0.0) if connect_pads else None
  thermal_gap = coerce_float(atom_value(find_child(zone_node, "thermal_gap")), 0.0)
  thermal_bridge = coerce_float(atom_value(find_child(zone_node, "thermal_bridge_width")), 0.0)
  hatch_node = find_child(zone_node, "hatch")
  hatch = atom_values(hatch_node) if hatch_node else []
  polygon_node = find_child(zone_node, "polygon") or []
  outline_points = _parse_xy_points(find_child(polygon_node, "pts") or polygon_node)
  filled_islands = find_children(zone_node, "filled_polygon")
  island_outlines: list[list[dict[str, float]]] = []
  for island_root in filled_islands:
    for island in find_children(island_root, "island"):
      outline = find_child(island, "outline")
      if outline:
        island_outlines.append(_parse_xy_points(find_child(outline, "pts") or outline))
  if not outline_points and island_outlines:
    outline_points = island_outlines[0]
  return {
    "net": net_name,
    "net_id": net_id,
    "layer": layer,
    "filled": filled,
    "fill_mode": fill_mode,
    "priority": priority,
    "min_thickness_mm": round(min_thickness, 4),
    "connect_pads_clearance_mm": round(connect_clearance, 4) if connect_clearance is not None else None,
    "thermal_gap_mm": round(thermal_gap, 4),
    "thermal_bridge_width_mm": round(thermal_bridge, 4),
    "hatch": hatch,
    "outline_points": outline_points,
    "filled_island_outlines": island_outlines,
    "filled_island_count": len(island_outlines),
    "bounding_box_mm": _bounding_box(outline_points),
  }


def _parse_board_graphics(root: list[Any]) -> list[dict[str, Any]]:
  graphics: list[dict[str, Any]] = []
  for symbol in ("gr_line", "gr_arc", "gr_circle", "gr_rect", "gr_poly", "gr_curve"):
    for node in find_children(root, symbol):
      layer = str(atom_value(find_child(node, "layer"), ""))
      width = coerce_float(atom_value(find_child(node, "width")), 0.0)
      points: list[dict[str, float]] = []
      if symbol in {"gr_line", "gr_rect"}:
        start = atom_values(find_child(node, "start") or [])
        end = atom_values(find_child(node, "end") or [])
        if len(start) >= 2:
          points.append({"x": coerce_float(start[0]), "y": coerce_float(start[1])})
        if len(end) >= 2:
          points.append({"x": coerce_float(end[0]), "y": coerce_float(end[1])})
      elif symbol == "gr_poly":
        points = _parse_xy_points(find_child(node, "pts") or node)
      graphics.append(
        {
          "type": symbol,
          "layer": layer,
          "width_mm": round(width, 4) if width else None,
          "points": [{"x": round(point["x"], 4), "y": round(point["y"], 4)} for point in points],
          "bounding_box_mm": _bounding_box(points),
        }
      )
  return graphics


def _pads_for_net(document: PcbDocument, net_name: str, net_id: int | None) -> list[dict[str, Any]]:
  pads: list[dict[str, Any]] = []
  for footprint in document.footprints:
    for pad in footprint.get("pads", []):
      if pad.get("net") == net_name or (net_id is not None and pad.get("net_id") == net_id):
        pads.append(
          {
            "ref": footprint.get("ref"),
            "number": pad.get("number"),
            "center_mm": pad.get("center_mm", {}).get("absolute"),
            "size_mm": pad.get("size_mm"),
            "layers": pad.get("layers"),
          }
        )
  return pads


def _analyze_net_connectivity(
  pads: list[dict[str, Any]],
  segments: list[dict[str, Any]],
  vias: list[dict[str, Any]],
  zones: list[dict[str, Any]],
  tolerance_mm: float = 0.02,
) -> dict[str, Any]:
  nodes: list[tuple[str, float, float]] = []
  for index, pad in enumerate(pads):
    center = pad.get("center_mm") or {}
    nodes.append((f"pad:{index}", coerce_float(center.get("x")), coerce_float(center.get("y"))))
  for index, via in enumerate(vias):
    center = via.get("center_mm") or {}
    nodes.append((f"via:{index}", coerce_float(center.get("x")), coerce_float(center.get("y"))))
  for index, segment in enumerate(segments):
    start = segment.get("start_mm") or {}
    end = segment.get("end_mm") or {}
    nodes.append((f"seg:{index}:start", coerce_float(start.get("x")), coerce_float(start.get("y"))))
    nodes.append((f"seg:{index}:end", coerce_float(end.get("x")), coerce_float(end.get("y"))))

  if not nodes:
    return {
      "connected_component_count": 0,
      "isolated_pad_count": len(pads),
      "isolated_pads": pads,
      "zone_pour_present": len(zones) > 0,
      "note": "No routed copper geometry found for this net.",
    }

  parent = list(range(len(nodes)))

  def find(item: int) -> int:
    while parent[item] != item:
      parent[item] = parent[parent[item]]
      item = parent[item]
    return item

  def union(left: int, right: int) -> None:
    root_left = find(left)
    root_right = find(right)
    if root_left != root_right:
      parent[root_right] = root_left

  def near(left: tuple[str, float, float], right: tuple[str, float, float]) -> bool:
    return math.hypot(left[1] - right[1], left[2] - right[2]) <= tolerance_mm

  for left_index in range(len(nodes)):
    for right_index in range(left_index + 1, len(nodes)):
      if near(nodes[left_index], nodes[right_index]):
        union(left_index, right_index)

  for index, segment in enumerate(segments):
    start = segment.get("start_mm") or {}
    end = segment.get("end_mm") or {}
    start_node = (f"seg:{index}:start", coerce_float(start.get("x")), coerce_float(start.get("y")))
    end_node = (f"seg:{index}:end", coerce_float(end.get("x")), coerce_float(end.get("y")))
    union(nodes.index(start_node), nodes.index(end_node))

  node_to_group = {find(index) for index in range(len(nodes))}
  isolated_pads: list[dict[str, Any]] = []
  for pad_index, pad in enumerate(pads):
    center = pad.get("center_mm") or {}
    pad_node = (f"pad:{pad_index}", coerce_float(center.get("x")), coerce_float(center.get("y")))
    group_id = find(nodes.index(pad_node))
    group_members = [nodes[item][0] for item in range(len(nodes)) if find(item) == group_id]
    has_routing = any(
      member.startswith("seg:") or member.startswith("via:")
      for member in group_members
    )
    if not has_routing:
      isolated_pads.append(pad)

  return {
    "connected_component_count": len(node_to_group),
    "isolated_pad_count": len(isolated_pads),
    "isolated_pads": isolated_pads,
    "zone_pour_present": len(zones) > 0,
    "note": "Connectivity is based on track endpoints, vias, and pad centers within 0.02 mm. Copper pours are reported separately.",
  }
