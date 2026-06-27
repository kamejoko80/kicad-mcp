"""kicad-cli subprocess helpers.

Author: Henry Dang
Email: phuongminh.dang@gmail.com
"""

import os
import subprocess
import tempfile
from dataclasses import dataclass
from typing import Any

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


def run_kicad_cli_to_path(args: list[str], output_path: str, cwd: str | None = None) -> CliResult:
    """Run kicad-cli writing output to an explicit file path."""
    kicad_cli = resolve_kicad_cli()
    if not os.path.isfile(kicad_cli):
        return CliResult(
            stdout="",
            stderr=f"KiCad CLI not found at: {kicad_cli}",
            returncode=127,
        )

    if not args:
        return CliResult(stdout="", stderr="No CLI arguments provided.", returncode=2)

    output_parent = os.path.dirname(output_path)
    if output_parent:
        os.makedirs(output_parent, exist_ok=True)

    input_file = args[-1]
    cmd = [kicad_cli, *args[:-1], "--output", output_path, input_file]
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
        output_path=output_path if os.path.exists(output_path) else None,
    )


def read_output_directory(output_dir: str) -> list[dict[str, Any]]:
    """List files in an export directory with size metadata."""
    files: list[dict[str, Any]] = []
    if not os.path.isdir(output_dir):
        return files
    for root, _dirs, filenames in os.walk(output_dir):
        for filename in sorted(filenames):
            path = os.path.join(root, filename)
            files.append(
                {
                    "path": path,
                    "name": filename,
                    "relative_path": os.path.relpath(path, output_dir),
                    "size_bytes": os.path.getsize(path),
                }
            )
    return files


def run_kicad_cli_with_output_dir(
    args: list[str],
    output_dir: str,
    cwd: str | None = None,
) -> CliResult:
    """Run kicad-cli writing output to a directory."""
    kicad_cli = resolve_kicad_cli()
    if not os.path.isfile(kicad_cli):
        return CliResult(
            stdout="",
            stderr=f"KiCad CLI not found at: {kicad_cli}",
            returncode=127,
        )

    os.makedirs(output_dir, exist_ok=True)

    if not args:
        return CliResult(stdout="", stderr="No CLI arguments provided.", returncode=2)

    input_file = args[-1]
    cmd = [kicad_cli, *args[:-1], "--output", output_dir, input_file]
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
        output_path=output_dir,
    )


def read_text_file(path: str, max_chars: int | None = None) -> str:
    if not path or not os.path.isfile(path):
        return ""
    with open(path, encoding="utf-8") as handle:
        content = handle.read()
    if max_chars is not None:
        return content[:max_chars]
    return content


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
