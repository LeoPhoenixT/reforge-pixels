import os
import subprocess
from pathlib import Path

import pytest

from reforge_pixels.hdr import hdr_filter, verify_sdr_output
from reforge_pixels.media import inspect_media
from reforge_pixels.paths import find_tool


def _tool(env_name: str, tool_name: str) -> Path:
    configured = os.environ.get(env_name)
    candidate = Path(configured) if configured else find_tool(tool_name)
    if not candidate or not candidate.is_file():
        pytest.skip(f"{tool_name} is unavailable")
    return candidate


def _run(command: list[str]) -> None:
    completed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert completed.returncode == 0, completed.stderr


@pytest.mark.parametrize(
    ("transfer", "expected_kind"),
    [("arib-std-b67", "hlg"), ("smpte2084", "pq")],
)
def test_real_hdr_to_sdr_metadata_round_trip(
    tmp_path: Path, transfer: str, expected_kind: str,
) -> None:
    ffmpeg = _tool("REFORGE_PIXELS_TEST_FFMPEG", "ffmpeg")
    ffprobe = _tool("REFORGE_PIXELS_TEST_FFPROBE", "ffprobe")
    source = tmp_path / f"source-{expected_kind}.mp4"
    output = tmp_path / f"output-{expected_kind}.mp4"
    _run([
        str(ffmpeg), "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "testsrc2=size=96x64:rate=5:duration=1",
        "-vf", "format=yuv420p10le", "-c:v", "libx265", "-preset", "ultrafast",
        "-x265-params", f"log-level=error:colorprim=bt2020:transfer={transfer}:colormatrix=bt2020nc:range=limited",
        str(source),
    ])
    media = inspect_media(source, ffprobe)
    assert media.hdr_kind == expected_kind
    conversion_filter = hdr_filter(media, "convert-sdr")
    assert conversion_filter

    _run([
        str(ffmpeg), "-hide_banner", "-loglevel", "error", "-y", "-i", str(source),
        "-map", "0:v:0", "-vf", conversion_filter, "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
        "-color_range", "tv", "-an", str(output),
    ])
    verified = inspect_media(output, ffprobe)
    verify_sdr_output(verified)
