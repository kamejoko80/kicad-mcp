"""PCB geometry and footprint MCP tools.

Author: Henry Dang
Email: phuongminh.dang@gmail.com
"""

from __future__ import annotations

import json
import logging

from kicad_mcp import pcb_model
from kicad_mcp.project import validate_project_dir
from kicad_mcp.review.pcb_region_svg import export_pcb_region_image as export_pcb_region_svg

logger = logging.getLogger("kicad-hardware-agent")


def _json_response(payload: dict) -> str:
    return json.dumps(payload, indent=2)


def register(mcp) -> None:
    @mcp.tool()
    def get_component_footprint(project_dir: str, ref: str) -> str:
        """
        Return structured footprint geometry for a PCB component reference.

        Includes pad size/shape/layer/net data, courtyard/fab/silk graphics,
        and absolute pad-center coordinates for layout review.
        """
        logger.info("Reading footprint for %s in %s", ref, project_dir)
        error = validate_project_dir(project_dir)
        if error:
            return _json_response({"error": error})

        document, load_error = pcb_model.load_pcb_document(project_dir)
        if document is None:
            return _json_response({"error": load_error})

        payload = pcb_model.get_component_footprint(document, ref)
        if "error" in payload:
            return _json_response(payload)

        payload["pcb_file"] = document.path
        return _json_response(payload)

    @mcp.tool()
    def get_component_placement(project_dir: str) -> str:
        """
        Return SMT/THT component placement data for pick-and-place review.

        Includes reference, value, footprint, board side, XY position, rotation,
        DNP flag, pad count, and bounding box.
        """
        logger.info("Reading component placement for %s", project_dir)
        error = validate_project_dir(project_dir)
        if error:
            return _json_response({"error": error})

        document, load_error = pcb_model.load_pcb_document(project_dir)
        if document is None:
            return _json_response({"error": load_error})

        return _json_response(
            {
                "pcb_file": document.path,
                "component_count": len(document.footprints),
                "components": pcb_model.get_component_placement(document),
            }
        )

    @mcp.tool()
    def get_board_geometry(project_dir: str, layers: str = "", include_graphics: bool = True) -> str:
        """
        Return structured PCB geometry: tracks, vias, copper zones, and board graphics.

        Optionally filter by comma-separated KiCad layer names such as
        `F.Cu,B.Cu,Edge.Cuts`.
        """
        logger.info("Reading board geometry for %s", project_dir)
        error = validate_project_dir(project_dir)
        if error:
            return _json_response({"error": error})

        document, load_error = pcb_model.load_pcb_document(project_dir)
        if document is None:
            return _json_response({"error": load_error})

        layer_list = [layer.strip() for layer in layers.split(",") if layer.strip()] or None
        return _json_response(pcb_model.get_board_geometry(document, layer_list, include_graphics))

    @mcp.tool()
    def analyze_copper_pours(project_dir: str) -> str:
        """
        Analyze copper pour zones: fill state, layer, net, hatch, thermal settings,
        outline geometry, and filled island counts.
        """
        logger.info("Analyzing copper pours for %s", project_dir)
        error = validate_project_dir(project_dir)
        if error:
            return _json_response({"error": error})

        document, load_error = pcb_model.load_pcb_document(project_dir)
        if document is None:
            return _json_response({"error": load_error})

        return _json_response(pcb_model.analyze_copper_pours(document))

    @mcp.tool()
    def analyze_net_routing(project_dir: str, net_name: str) -> str:
        """
        Analyze a PCB net in depth: routed segments, vias, zone participation,
        connected pads, connectivity islands, and IPC-2152 current estimate.
        """
        logger.info("Analyzing net routing %s in %s", net_name, project_dir)
        error = validate_project_dir(project_dir)
        if error:
            return _json_response({"error": error})

        document, load_error = pcb_model.load_pcb_document(project_dir)
        if document is None:
            return _json_response({"error": load_error})

        return _json_response(pcb_model.analyze_net_routing(document, net_name))

    @mcp.tool()
    def export_pcb_region_image(
        project_dir: str,
        center_x_mm: float,
        center_y_mm: float,
        width_mm: float = 12.0,
        height_mm: float = 12.0,
        layers: str = "F.Cu,Edge.Cuts",
        highlight_net: str = "",
        marker: bool = True,
        marker_label: str = "",
        marker_size_mm: float = 0.4,
        auto_zoom: bool = True,
        search_radius_mm: float = 4.0,
        padding_mm: float = 0.8,
        min_window_mm: float = 6.0,
        max_window_mm: float = 12.0,
        include_silkscreen: bool = False,
        png_min_pixels: int = 1400,
        output_path: str = "",
    ) -> str:
        """
        Export a cropped SVG (+ PNG preview) of a PCB region for layout/DRC review.

        Renders geometry from the parsed `.kicad_pcb` file (tracks, pads, vias,
        zones, board outline) within a rectangular window centered
        at `center_x_mm`, `center_y_mm`. Use DRC coordinates directly.

        Silkscreen is hidden by default (`include_silkscreen=False`) so copper,
        pads, and vias stay readable. Set `include_silkscreen=True` to draw
        F.Silkscreen and B.Silkscreen plus reference designators.

        Set `auto_zoom=True` (default) to fit the window to pads/traces/vias
        near the center point. PNG preview is rasterized at `png_min_pixels`
        on the short side so details stay readable in chat.

        Files are written under `<project_dir>/mcp_exports/review/` unless
        `output_path` is set.
        """
        logger.info(
            "Exporting PCB region snapshot at (%.3f, %.3f) for %s",
            center_x_mm,
            center_y_mm,
            project_dir,
        )
        error = validate_project_dir(project_dir)
        if error:
            return _json_response({"error": error})

        layer_list = [layer.strip() for layer in layers.split(",") if layer.strip()] or None
        payload = export_pcb_region_svg(
            project_dir,
            center_x_mm=center_x_mm,
            center_y_mm=center_y_mm,
            width_mm=width_mm,
            height_mm=height_mm,
            layers=layer_list,
            highlight_net=highlight_net.strip(),
            marker=marker,
            marker_label=marker_label.strip(),
            marker_size_mm=marker_size_mm,
            auto_zoom=auto_zoom,
            search_radius_mm=search_radius_mm,
            padding_mm=padding_mm,
            min_window_mm=min_window_mm,
            max_window_mm=max_window_mm,
            include_silkscreen=include_silkscreen,
            output_path=output_path.strip(),
            png_min_pixels=png_min_pixels,
        )
        return _json_response(payload)
