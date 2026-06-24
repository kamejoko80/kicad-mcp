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
from kicad_mcp.prompts import register as register_prompts
from kicad_mcp.review.compare import register as register_compare_tools
from kicad_mcp.review.layout import register as register_layout_tools
from kicad_mcp.review.schematic import register as register_schematic_tools

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("kicad-hardware-agent")

mcp = FastMCP(
    "KiCad Comprehensive Auditor",
    instructions=(
        "KiCad schematic and PCB layout review server. Start with get_project_info, "
        "then run ERC/DRC checks and net analysis tools."
    ),
)

register_schematic_tools(mcp)
register_layout_tools(mcp)
register_compare_tools(mcp)
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


def main() -> None:
    host = os.environ.get("KICAD_MCP_HOST", "127.0.0.1")
    port = int(os.environ.get("KICAD_MCP_PORT", "8500"))
    logger.info("Starting KiCad MCP server on %s:%s", host, port)
    mcp.run(transport="http", host=host, port=port)
