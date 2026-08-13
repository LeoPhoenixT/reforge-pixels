import os
import subprocess
from pathlib import Path

import pytest

from reforge_pixels.engine import locate_engine
from reforge_pixels.hdr import verify_sdr_output
from reforge_pixels.media import inspect_media
from reforge_pixels.models import load_models
from reforge_pixels.paths import find_tool
from reforge_pixels.video import process_cfr_video


@pytest.mark.skipif(
    os.environ.get("REFORGE_PIXELS_RUN_GPU_TESTS") != "1",
    reason="set REFORGE_PIXELS_RUN_GPU_TESTS=1 to run the RTX HDR pipeline",
)
def test_real_rtx_hdr_to_sdr_pipeline(tmp_path: Path) -> None:
    ffmpeg = find_tool("ffmpeg")
    ffprobe = find_tool("ffprobe")
    if not ffmpeg or not ffprobe:
        pytest.skip("bundled FFmpeg tools are unavailable")
    source = tmp_path / "tiny-hlg.mp4"
    output = tmp_path / "tiny-hlg-upscaled.mkv"
    completed = subprocess.run([
        str(ffmpeg), "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "testsrc2=size=96x64:rate=5:duration=1",
        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=1",
        "-map", "0:v:0", "-map", "1:a:0", "-vf", "format=yuv420p10le",
        "-c:v", "libx265", "-preset", "ultrafast",
        "-x265-params", "log-level=error:colorprim=bt2020:transfer=arib-std-b67:colormatrix=bt2020nc:range=limited",
        "-c:a", "aac", str(source),
    ], capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert completed.returncode == 0, completed.stderr

    media = inspect_media(source, ffprobe)
    assert media.hdr_kind == "hlg"
    model = next(item for item in load_models() if item.id == "waifu2x-photo")
    engine = locate_engine(model)
    if not engine:
        pytest.skip("bundled Waifu2x engine is unavailable")
    process_cfr_video(
        media, engine, model, 2, output, ffmpeg_path=ffmpeg, chunk_frames=5,
        hdr_mode="convert-sdr",
    )

    verified = inspect_media(output, ffprobe)
    assert (verified.resolution.width, verified.resolution.height) == (192, 128)
    assert verified.audio_codecs == ("aac",)
    verify_sdr_output(verified)
