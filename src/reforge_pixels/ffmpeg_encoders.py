"""FFmpeg encoder discovery shared during one video processing request."""

from __future__ import annotations

import subprocess
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path


_encoder_cache: ContextVar[dict[Path, frozenset[str]] | None] = ContextVar(
    "ffmpeg_encoder_cache", default=None,
)


@contextmanager
def encoder_query_scope():
    token = _encoder_cache.set({})
    try:
        yield
    finally:
        _encoder_cache.reset(token)


def available_encoders(ffmpeg_path: str | Path) -> frozenset[str]:
    executable = Path(ffmpeg_path)
    cache = _encoder_cache.get()
    if cache is not None and executable in cache:
        return cache[executable]
    try:
        completed = subprocess.run(
            [str(executable), "-hide_banner", "-encoders"],
            check=False, capture_output=True, text=True, encoding="utf-8", errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except OSError:
        result = frozenset()
    else:
        result = frozenset(
            parts[1] for line in completed.stdout.splitlines()
            if completed.returncode == 0 and len(parts := line.split()) >= 2
            and len(parts[0]) == 6 and parts[0][0] in {"V", "A", "S"}
        )
    if cache is not None:
        cache[executable] = result
    return result
