"""KiCad CLI path resolution.

Author: Henry Dang
Email: phuongminh.dang@gmail.com
"""

import os
import platform
import shutil
from pathlib import Path


def resolve_kicad_cli() -> str:
    """Resolve the kicad-cli executable from env, install paths, or PATH."""
    env_path = os.environ.get("KICAD_CLI")
    if env_path and Path(env_path).is_file():
        return env_path

    system = platform.system()
    if system == "Windows":
        candidates = [
            r"C:\Program Files\KiCad\10.0\bin\kicad-cli.exe",
            r"C:\Program Files\KiCad\9.0\bin\kicad-cli.exe",
            r"C:\Program Files\KiCad\8.0\bin\kicad-cli.exe",
        ]
    elif system == "Darwin":
        candidates = [
            "/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli",
        ]
    else:
        candidates = [
            "/usr/bin/kicad-cli",
            "/usr/local/bin/kicad-cli",
        ]

    for candidate in candidates:
        if Path(candidate).is_file():
            return candidate

    found = shutil.which("kicad-cli")
    if found:
        return found

    return candidates[0] if candidates else "kicad-cli"
