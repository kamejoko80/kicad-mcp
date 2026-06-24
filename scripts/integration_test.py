#!/usr/bin/env python3
"""Start the KiCad MCP server, exercise tools over MCP HTTP, then stop the server.

Author: Henry Dang
Email: phuongminh.dang@gmail.com
"""

from __future__ import annotations

import argparse
import asyncio
import os
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.types import CallToolResult

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROJECT_DIR = (
    r"D:\Workspace\HW\KiCad\Projects\kicad_hw_design\cardinal_bes2800_rev2.0"
)


@dataclass
class ToolTest:
    name: str
    arguments: dict
    expect: str
    description: str


def tool_text(result: CallToolResult) -> str:
    parts: list[str] = []
    for block in result.content:
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
    return "\n".join(parts)


def wait_for_port(host: str, port: int, timeout: float = 30.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=1):
                return True
        except OSError:
            time.sleep(0.25)
    return False


def start_server(host: str, port: int) -> subprocess.Popen:
    env = os.environ.copy()
    env["KICAD_MCP_HOST"] = host
    env["KICAD_MCP_PORT"] = str(port)
    env["PYTHONUNBUFFERED"] = "1"

    return subprocess.Popen(
        [sys.executable, "-m", "kicad_mcp"],
        cwd=REPO_ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def stop_server(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return

    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def build_tests(project_dir: str) -> list[ToolTest]:
    return [
        ToolTest(
            name="get_project_info",
            arguments={"project_dir": project_dir},
            expect="KiCad Project",
            description="resolve project files and metadata",
        ),
        ToolTest(
            name="scan_project_structure",
            arguments={"project_dir": project_dir},
            expect="schematic sheets",
            description="list schematic sheets and PCB file",
        ),
        ToolTest(
            name="check_schematic_erc",
            arguments={"project_dir": project_dir},
            expect="ERC",
            description="run schematic electrical rules check",
        ),
        ToolTest(
            name="get_clean_component_list",
            arguments={"project_dir": project_dir},
            expect="Bill of Materials",
            description="export BOM through MCP",
        ),
        ToolTest(
            name="get_board_stats",
            arguments={"project_dir": project_dir},
            expect="Board Statistics",
            description="export PCB board statistics",
        ),
        ToolTest(
            name="compare_sch_pcb_nets",
            arguments={"project_dir": project_dir},
            expect="Schematic vs PCB Net Comparison",
            description="compare schematic and PCB net names",
        ),
        ToolTest(
            name="list_project_nets",
            arguments={"project_dir": project_dir},
            expect="Registered Electrical Nets",
            description="list PCB nets grouped by type",
        ),
        ToolTest(
            name="inspect_net_trace",
            arguments={"project_dir": project_dir, "net_name": "GND"},
            expect="Physical Trace Report",
            description="inspect GND trace geometry and current estimate",
        ),
        ToolTest(
            name="check_pcb_drc",
            arguments={"project_dir": project_dir},
            expect="DRC",
            description="run PCB design rules check",
        ),
    ]


async def run_mcp_tests(
    base_url: str,
    tests: list[ToolTest],
    tool_timeout: float,
) -> tuple[int, int]:
    passed = 0
    failed = 0
    timeout = timedelta(seconds=tool_timeout)

    async with streamable_http_client(base_url) as (read_stream, write_stream, _get_session_id):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            tools = await session.list_tools()
            print(f"Connected. Server exposes {len(tools.tools)} tools.\n", flush=True)

            for index, test in enumerate(tests, start=1):
                print(f"[{index}/{len(tests)}] {test.name}: {test.description}", flush=True)
                try:
                    result = await session.call_tool(
                        test.name,
                        test.arguments,
                        read_timeout_seconds=timeout,
                    )
                    text = tool_text(result)

                    if result.isError:
                        print(f"  FAIL: tool returned error\n{text[:400]}\n", flush=True)
                        failed += 1
                        continue

                    if test.expect.lower() not in text.lower():
                        print(f"  FAIL: expected text containing `{test.expect}`\n{text[:400]}\n", flush=True)
                        failed += 1
                        continue

                    preview = text.replace("\n", " ")[:120]
                    print(f"  PASS: {preview}\n", flush=True)
                    passed += 1
                except Exception as exc:
                    print(f"  FAIL: {exc}\n", flush=True)
                    failed += 1

    return passed, failed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--project-dir",
        default=DEFAULT_PROJECT_DIR,
        help="KiCad project directory to use in tool calls",
    )
    parser.add_argument("--host", default=os.environ.get("KICAD_MCP_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("KICAD_MCP_PORT", "8500")))
    parser.add_argument(
        "--startup-timeout",
        type=float,
        default=30.0,
        help="Seconds to wait for the MCP server to accept connections",
    )
    parser.add_argument(
        "--tool-timeout",
        type=float,
        default=300.0,
        help="Seconds to wait for each MCP tool call to complete",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    base_url = f"http://{args.host}:{args.port}/mcp"
    tests = build_tests(args.project_dir)

    print(f"Starting MCP server at {base_url}", flush=True)
    server = start_server(args.host, args.port)

    try:
        if not wait_for_port(args.host, args.port, timeout=args.startup_timeout):
            print("Server failed to start within timeout.", flush=True)
            return 1

        passed, failed = asyncio.run(
            run_mcp_tests(base_url, tests, tool_timeout=args.tool_timeout)
        )
        print(f"Results: {passed} passed, {failed} failed", flush=True)
        return 0 if failed == 0 else 1
    finally:
        print("Stopping MCP server...", flush=True)
        stop_server(server)


if __name__ == "__main__":
    raise SystemExit(main())
