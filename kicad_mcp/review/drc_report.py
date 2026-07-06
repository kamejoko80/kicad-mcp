"""Parse KiCad DRC reports and export region snapshots for violations."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from kicad_mcp.review.pcb_region_svg import export_pcb_region_image

COORD_RE = re.compile(r"@\(([\d.]+)\s+mm,\s+([\d.]+)\s+mm\):\s*(.+)")
RULE_RE = re.compile(r"^\[([^\]]+)\]:\s*(.+)$")
SEVERITY_RE = re.compile(r";\s*(error|warning)\s*$", re.IGNORECASE)
SHORT_NETS_RE = re.compile(r"\(nets\s+(\S+)\s+and\s+(\S+)\)", re.IGNORECASE)
NET_BRACKET_RE = re.compile(r"\[([^\]]+)\]")
LAYER_RE = re.compile(r"\bon\s+([A-Za-z0-9_.]+)")


@dataclass
class DrcLocation:
    x_mm: float
    y_mm: float
    detail: str
    layer: str = ""

    def key(self) -> tuple[float, float]:
        return (round(self.x_mm, 3), round(self.y_mm, 3))


@dataclass
class DrcViolation:
    rule: str
    description: str
    severity: str
    locations: list[DrcLocation] = field(default_factory=list)
    nets: list[str] = field(default_factory=list)

    @property
    def primary_location(self) -> DrcLocation | None:
        return self.locations[0] if self.locations else None


def _extract_layer(detail: str) -> str:
    match = LAYER_RE.search(detail)
    return match.group(1) if match else ""


def _extract_nets(violation: DrcViolation) -> list[str]:
    if violation.nets:
        return violation.nets

    nets: list[str] = []
    short_match = SHORT_NETS_RE.search(violation.description)
    if short_match:
        nets.extend([short_match.group(1).strip(), short_match.group(2).strip()])
    for location in violation.locations:
        for net in NET_BRACKET_RE.findall(location.detail):
            if net not in nets:
                nets.append(net)
    return nets


def _pick_highlight_net(nets: list[str]) -> str:
    for net in nets:
        if net.upper() not in {"GND", "GROUND"}:
            return net
    return nets[0] if nets else ""


def _pick_layers(primary_layer: str) -> list[str]:
    if primary_layer and primary_layer != "Edge.Cuts":
        return [primary_layer, "Edge.Cuts"]
    return ["F.Cu", "B.Cu", "Edge.Cuts"]


def parse_drc_report(report_content: str) -> list[DrcViolation]:
    """Parse KiCad pcb drc text report into structured violations."""
    violations: list[DrcViolation] = []
    current: DrcViolation | None = None

    for raw_line in report_content.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("**"):
            continue

        rule_match = RULE_RE.match(stripped)
        if rule_match:
            if current is not None:
                violations.append(current)
            current = DrcViolation(
                rule=rule_match.group(1),
                description=rule_match.group(2).strip(),
                severity="warning",
            )
            short_match = SHORT_NETS_RE.search(current.description)
            if short_match:
                current.nets = [
                    short_match.group(1).strip(),
                    short_match.group(2).strip(),
                ]
            continue

        if current is None:
            continue

        severity_match = SEVERITY_RE.search(stripped)
        if severity_match:
            current.severity = severity_match.group(1).lower()
            continue

        coord_match = COORD_RE.match(stripped)
        if coord_match:
            detail = coord_match.group(3).strip()
            current.locations.append(
                DrcLocation(
                    x_mm=float(coord_match.group(1)),
                    y_mm=float(coord_match.group(2)),
                    detail=detail,
                    layer=_extract_layer(detail),
                )
            )

    if current is not None:
        violations.append(current)

    return violations


def unique_error_locations(violations: list[DrcViolation]) -> list[tuple[DrcViolation, DrcLocation]]:
    """Return one location per coordinate for error-level violations."""
    seen: set[tuple[float, float]] = set()
    results: list[tuple[DrcViolation, DrcLocation]] = []

    for violation in violations:
        if violation.severity != "error":
            continue
        for location in violation.locations:
            key = location.key()
            if key in seen:
                continue
            seen.add(key)
            results.append((violation, location))

    return results


def export_drc_region_images(
    project_dir: str,
    report_content: str,
    *,
    max_images: int = 5,
    png_min_pixels: int = 1600,
) -> list[dict[str, object]]:
    """Export PNG snapshots for unique DRC error coordinates."""
    violations = parse_drc_report(report_content)
    locations = unique_error_locations(violations)
    exports: list[dict[str, object]] = []

    for index, (violation, location) in enumerate(locations[:max_images], start=1):
        nets = _extract_nets(violation)
        highlight_net = _pick_highlight_net(nets)
        layers = _pick_layers(location.layer)
        tag = f"drc_{index:02d}_{violation.rule}"
        marker_label = violation.rule.replace("_", " ")

        payload = export_pcb_region_image(
            project_dir,
            center_x_mm=location.x_mm,
            center_y_mm=location.y_mm,
            layers=layers,
            highlight_net=highlight_net,
            marker_label=marker_label[:24],
            auto_zoom=True,
            max_window_mm=8.0,
            min_window_mm=4.0,
            search_radius_mm=2.5,
            padding_mm=0.5,
            include_silkscreen=False,
            png_min_pixels=png_min_pixels,
            output_path=os.path.join(
                "mcp_exports",
                "review",
                "drc",
                f"{tag}_x{location.x_mm:.3f}_y{location.y_mm:.3f}.svg",
            ),
        )
        if "error" in payload:
            exports.append(
                {
                    "index": index,
                    "rule": violation.rule,
                    "severity": violation.severity,
                    "x_mm": location.x_mm,
                    "y_mm": location.y_mm,
                    "highlight_net": highlight_net,
                    "layers": layers,
                    "error": payload["error"],
                }
            )
            continue

        exports.append(
            {
                "index": index,
                "rule": violation.rule,
                "description": violation.description,
                "severity": violation.severity,
                "x_mm": location.x_mm,
                "y_mm": location.y_mm,
                "detail": location.detail,
                "highlight_net": highlight_net,
                "layers": layers,
                "region_mm": payload.get("region_mm"),
                "png_path": str(payload.get("png_path", "")),
                "svg_path": str(payload.get("output_path", "")),
                "png_error": payload.get("png_error", ""),
            }
        )

    return exports


def _snapshot_png_path(item: dict[str, object]) -> Path | None:
    """Return the on-disk PNG snapshot path, rasterizing from SVG if needed."""
    from kicad_mcp.review.pcb_region_svg import write_region_png

    png_path = item.get("png_path")
    svg_path = item.get("svg_path")
    region = item.get("region_mm") or {}

    if png_path:
        full_png = Path(str(png_path))
        if full_png.is_file():
            return full_png

    if svg_path and Path(str(svg_path)).is_file():
        svg = Path(str(svg_path))
        target = svg.with_suffix(".png")
        if not target.is_file():
            write_region_png(
                str(svg),
                float(region.get("width", 8.0)),
                float(region.get("height", 8.0)),
                min_pixels=1600,
                png_path=str(target),
            )
        if target.is_file():
            return target

    return None


def _snapshot_table_cell(item: dict[str, object]) -> str:
    png_path = _snapshot_png_path(item)
    if png_path is None:
        png_error = item.get("png_error")
        if png_error:
            return f"*(PNG unavailable: {png_error})*"
        svg_path = item.get("svg_path")
        if svg_path and Path(str(svg_path)).is_file():
            svg = Path(str(svg_path)).resolve()
            return f"[{svg.name}]({svg.as_uri()})"
        return "*(snapshot unavailable)*"

    resolved = png_path.resolve()
    return f"[{resolved.name}]({resolved.as_uri()})"


def format_drc_snapshot_section(exports: list[dict[str, object]]) -> str:
    """Markdown table with file links to PNG snapshots in the last column."""
    if not exports:
        return ""

    successful = [
        item
        for item in exports
        if item.get("png_path") or item.get("svg_path")
    ]
    failed = [item for item in exports if item.get("error")]
    if not successful and not failed:
        return ""

    lines = [
        "",
        "### DRC Error Snapshots",
        "",
        "Region SVG and PNG files are saved under `<project_dir>/mcp_exports/review/drc/`.",
        "",
        "| # | Rule | Location | Snapshot |",
        "|---|------|----------|----------|",
    ]
    for item in successful:
        lines.append(
            f"| {item['index']} | `{item['rule']}` | "
            f"{item['x_mm']:.3f}, {item['y_mm']:.3f} | {_snapshot_table_cell(item)} |"
        )

    if failed:
        lines.extend(["", "Snapshot export failures:"])
        for item in failed:
            lines.append(
                f"- #{item['index']} `{item['rule']}` @ ({item['x_mm']:.3f}, {item['y_mm']:.3f}): "
                f"{item['error']}"
            )

    return "\n".join(lines)


def build_drc_tool_response(
    report_markdown: str,
    exports: list[dict[str, object]],
) -> str:
    """Build DRC MCP tool text with an inline snapshot table."""
    return report_markdown + format_drc_snapshot_section(exports)
