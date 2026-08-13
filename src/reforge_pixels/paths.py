"""Development and frozen-application path resolution."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


def application_root() -> Path:
    if getattr(sys, "frozen", False) or "__compiled__" in globals():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def platform_name() -> str:
    return "windows" if os.name == "nt" else "linux"


def find_tool(name: str) -> Path | None:
    executable_name = name + ".exe" if os.name == "nt" and not name.endswith(".exe") else name
    bundled = application_root() / "runtime" / "tools" / platform_name() / executable_name
    if bundled.is_file():
        return bundled
    system = shutil.which(executable_name)
    return Path(system) if system else None
