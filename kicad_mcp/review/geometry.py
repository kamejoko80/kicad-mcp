"""PCB geometry and footprint MCP tools.

Author: Henry Dang
Email: phuongminh.dang@gmail.com
"""

from __future__ import annotations

import json
import logging

from kicad_mcp import pcb_model
from kicad_mcp.project import validate_project_dir

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
