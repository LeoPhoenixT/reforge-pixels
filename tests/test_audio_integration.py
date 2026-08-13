from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from reforge_pixels.audio import resolve_audio_actions
from reforge_pixels.media import inspect_media
from reforge_pixels.paths import find_tool
from reforge_pixels.video import audio_encoder_available, mux_final_output, preflight_audio_actions


def run(command: list[str]) -> None:
    completed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert completed.returncode == 0, completed.stderr


@pytest.fixture()
def audio_fixture(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    ffmpeg = (
        Path(os.environ["REFORGE_PIXELS_TEST_FFMPEG"])
        if os.environ.get("REFORGE_PIXELS_TEST_FFMPEG") else find_tool("ffmpeg")
    )
    ffprobe = (
        Path(os.environ["REFORGE_PIXELS_TEST_FFPROBE"])
        if os.environ.get("REFORGE_PIXELS_TEST_FFPROBE") else find_tool("ffprobe")
    )
    if not ffmpeg or not ffprobe:
        pytest.skip("FFmpeg runtime is not available")
    if not audio_encoder_available(ffmpeg, "libopus"):
        pytest.skip("The pinned FFmpeg runtime has no libopus encoder")

    source = tmp_path / "opus-source.mkv"
    joined = tmp_path / "joined-video.mkv"
    run([
        str(ffmpeg), "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "testsrc2=size=64x64:rate=10:duration=1",
        "-f", "lavfi", "-i", "sine=frequency=880:sample_rate=48000:duration=1",
        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=1",
        "-map", "0:v:0", "-map", "1:a:0", "-map", "2:a:0",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a:0", "libopus", "-b:a:0", "96k", "-c:a:1", "flac",
        "-metadata:s:a:0", "language=eng", "-metadata:s:a:0", "title=Main audio",
        "-metadata:s:a:1", "language=jpn", "-metadata:s:a:1", "title=Commentary",
        "-disposition:a:0", "default", "-disposition:a:1", "0", str(source),
    ])
    run([
        str(ffmpeg), "-hide_banner", "-loglevel", "error", "-y", "-i", str(source),
        "-map", "0:v:0", "-c:v", "copy", "-an", str(joined),
    ])
    return Path(ffmpeg), Path(ffprobe), source, joined


@pytest.mark.parametrize(
    ("suffix", "expected_codec"),
    ((".mkv", "opus"), (".mp4", "aac")),
)
def test_real_opus_copy_or_conversion_by_container(
    audio_fixture: tuple[Path, Path, Path, Path], tmp_path: Path,
    suffix: str, expected_codec: str,
) -> None:
    ffmpeg, ffprobe, source, joined = audio_fixture
    media = inspect_media(source, ffprobe)
    output = tmp_path / f"result{suffix}"
    actions = resolve_audio_actions(media, suffix, "automatic")
    preflight_audio_actions(ffmpeg, media, suffix, actions, tmp_path)
    mux_final_output(ffmpeg, ffprobe, joined, media, output, actions)
    verified = inspect_media(output, ffprobe)
    expected_codecs = ("opus", "flac") if expected_codec == "opus" else ("aac", "aac")
    assert verified.audio_codecs == expected_codecs
    assert tuple(stream.channels for stream in verified.audio_details) == (1, 1)
    assert tuple(stream.language for stream in verified.audio_details) == ("eng", "jpn")
    assert tuple(stream.title for stream in verified.audio_details) == ("Main audio", "Commentary")
    assert "default" in verified.audio_details[0].dispositions
    assert abs((verified.duration_seconds or 0) - (media.duration_seconds or 0)) <= 0.25


def test_real_explicit_audio_removal(
    audio_fixture: tuple[Path, Path, Path, Path], tmp_path: Path,
) -> None:
    ffmpeg, ffprobe, source, joined = audio_fixture
    media = inspect_media(source, ffprobe)
    output = tmp_path / "silent.mkv"
    actions = resolve_audio_actions(media, ".mkv", "remove")
    mux_final_output(ffmpeg, ffprobe, joined, media, output, actions)
    assert inspect_media(output, ffprobe).audio_streams == 0


def test_real_explicit_opus_conversion(
    audio_fixture: tuple[Path, Path, Path, Path], tmp_path: Path,
) -> None:
    ffmpeg, ffprobe, source, joined = audio_fixture
    media = inspect_media(source, ffprobe)
    output = tmp_path / "all-opus.mkv"
    actions = resolve_audio_actions(media, ".mkv", "opus")
    mux_final_output(ffmpeg, ffprobe, joined, media, output, actions)
    assert inspect_media(output, ffprobe).audio_codecs == ("opus", "opus")


def test_short_audio_does_not_truncate_video(
    audio_fixture: tuple[Path, Path, Path, Path], tmp_path: Path,
) -> None:
    ffmpeg, ffprobe, _, joined = audio_fixture
    source = tmp_path / "short-audio.mkv"
    run([
        str(ffmpeg), "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "testsrc2=size=64x64:rate=10:duration=1",
        "-f", "lavfi", "-i", "sine=frequency=660:sample_rate=48000:duration=0.5",
        "-map", "0:v:0", "-map", "1:a:0", "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "libopus", str(source),
    ])
    media = inspect_media(source, ffprobe)
    output = tmp_path / "short-audio-result.mkv"
    actions = resolve_audio_actions(media, ".mkv", "automatic")
    mux_final_output(ffmpeg, ffprobe, joined, media, output, actions)
    verified = inspect_media(output, ffprobe)
    assert (verified.duration_seconds or 0) >= 0.9
    assert verified.audio_streams == 1
