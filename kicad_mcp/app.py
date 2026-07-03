"""MCP server bootstrap and HTTP entry point.

Author: Henry Dang
Email: phuongminh.dang@gmail.com
"""

import logging
import os

from fastmcp import FastMCP

from kicad_mcp import __version__
from kicad_mcp.config import resolve_kicad_cli
from kicad_mcp.project import find_project_files, summarize_project_info, validate_project_dir
from kicad_mcp.library.ecad_tools import register as register_ecad_tools
from kicad_mcp.library.search import register as register_library_tools
from kicad_mcp.prompts import register as register_prompts
from kicad_mcp.review.compare import register as register_compare_tools
from kicad_mcp.review.geometry import register as register_geometry_tools
from kicad_mcp.review.layout import register as register_layout_tools
from kicad_mcp.review.manufacturing import register as register_manufacturing_tools
from kicad_mcp.review.schematic import register as register_schematic_tools
from kicad_mcp.review.schematic_pdf import register as register_schematic_pdf_tools

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("kicad-hardware-agent")

mcp = FastMCP(
    "KiCad Comprehensive Auditor",
    instructions=(
        "KiCad schematic and PCB layout review server. Start with get_project_info, "
        "then run ERC/DRC checks, geometry/footprint tools, and net analysis tools. "
        "Use list_schematic_pdf_pages and export_schematic_pdf for schematic PDF output. "
        "For BOM/part lookup, configure Mouser or DigiKey credentials with "
        "set_component_provider_credentials, then use search_components_by_keyword "
        "or search_components_by_part_number (provider='mouser', 'digikey', or 'lcsc'). "
        "LCSC search uses unofficial wmsc.lcsc.com endpoints and requires no credentials. "
        "For KiCad symbols/footprints, configure SamacSys or Ultra Librarian credentials with "
        "set_ecad_provider_credentials, then use search_ecad_components and "
        "download_ecad_component_library."
    ),
)

register_schematic_tools(mcp)
register_schematic_pdf_tools(mcp)
register_layout_tools(mcp)
register_geometry_tools(mcp)
register_manufacturing_tools(mcp)
register_compare_tools(mcp)
register_library_tools(mcp)
register_ecad_tools(mcp)
register_prompts(mcp)


@mcp.resource("kicad://health")
def health_resource() -> str:
    """Server health and KiCad CLI availability."""
    cli_path = resolve_kicad_cli()
    return (
        f"KiCad MCP server v{__version__}\n"
        f"KiCad CLI: {cli_path}\n"
        f"CLI available: {os.path.isfile(cli_path)}\n"
    )


@mcp.resource("kicad://project/{project_dir}/summary")
def project_summary_resource(project_dir: str) -> str:
    """Project file summary for the given directory path."""
    error = validate_project_dir(project_dir)
    if error:
        return error
    paths = find_project_files(project_dir)
    return summarize_project_info(paths)


def _env_flag(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def main() -> None:
    host = os.environ.get("KICAD_MCP_HOST", "127.0.0.1")
    port = int(os.environ.get("KICAD_MCP_PORT", "8500"))
    # Run the HTTP transport statelessly so each request is self-contained.
    # This avoids 400 Bad Request responses when a client (e.g. Cursor) reuses
    # a session ID created by a previous server process after a restart, which
    # would otherwise block tool discovery until the client reconnects.
    stateless = _env_flag("KICAD_MCP_STATELESS_HTTP", True)
    logger.info(
        "Starting KiCad MCP server on %s:%s (stateless_http=%s)", host, port, stateless
    )
    mcp.run(transport="http", host=host, port=port, stateless_http=stateless)
