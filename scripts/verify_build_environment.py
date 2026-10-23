"""Refuse portable releases with an outdated interpreter or dependency drift."""

from __future__ import annotations

import importlib.metadata
from pathlib import Path
import sys
import tomllib


MINIMUM_PYTHON = {(3, 11): (3, 11, 17), (3, 12): (3, 12, 15)}


def verify_python(version: tuple[int, ...]) -> None:
    minimum = MINIMUM_PYTHON.get(version[:2])
    if minimum is None or version[:3] < minimum:
        raise RuntimeError("Portable builds require CPython 3.11.17+ or 3.12.15+ within those minor series")


def main() -> None:
    verify_python(sys.version_info[:3])
    root = Path(__file__).resolve().parents[1]
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    requirements = project["project"]["dependencies"] + project["build-system"]["requires"]
    for requirement in requirements:
        name, expected = requirement.split("==")
        actual = importlib.metadata.version(name)
        if actual != expected:
            raise RuntimeError(f"Build dependency mismatch for {name}: expected {expected}, installed {actual}")
    print("Portable build environment verified.")


if __name__ == "__main__":
    main()
