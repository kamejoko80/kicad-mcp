"""kicad-cli subprocess helpers.

Author: Henry Dang
Email: phuongminh.dang@gmail.com
"""

import os
import subprocess
import tempfile
from dataclasses import dataclass

from kicad_mcp.config import resolve_kicad_cli


@dataclass
class CliResult:
    stdout: str
    stderr: str
    returncode: int
    output_path: str | None = None


def run_kicad_cli(args: list[str], cwd: str | None = None) -> CliResult:
    """Run kicad-cli and capture stdout/stderr."""
    cmd = [resolve_kicad_cli(), *args]
    result = subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    return CliResult(
        stdout=result.stdout,
        stderr=result.stderr,
        returncode=result.returncode,
    )


def run_kicad_cli_with_output(args: list[str], suffix: str, cwd: str | None = None) -> CliResult:
    """Run kicad-cli writing output to a temporary file."""
    kicad_cli = resolve_kicad_cli()
    if not os.path.isfile(kicad_cli):
        return CliResult(
            stdout="",
            stderr=f"KiCad CLI not found at: {kicad_cli}",
            returncode=127,
        )

    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as handle:
        output_path = handle.name

    if not args:
        return CliResult(stdout="", stderr="No CLI arguments provided.", returncode=2)

    input_file = args[-1]
    cmd = [kicad_cli, *args[:-1], "--output", output_path, input_file]
    result = subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode != 0 and not os.path.exists(output_path):
        try:
            os.remove(output_path)
        except OSError:
            pass
        return CliResult(
            stdout=result.stdout,
            stderr=result.stderr,
            returncode=result.returncode,
        )

    return CliResult(
        stdout=result.stdout,
        stderr=result.stderr,
        returncode=result.returncode,
        output_path=output_path,
    )


def read_output_file(output_path: str | None) -> str:
    if not output_path or not os.path.exists(output_path):
        return ""

    try:
        with open(output_path, encoding="utf-8") as handle:
            return handle.read()
    finally:
        try:
            os.remove(output_path)
        except OSError:
            pass
