"""Shared helpers for integration tests that execute external tools."""

from __future__ import annotations

import subprocess


def run_command(command: list[str]) -> None:
    """Run a UTF-8 command and expose stderr when it fails."""
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert completed.returncode == 0, completed.stderr
