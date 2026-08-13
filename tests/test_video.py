from dataclasses import replace
from pathlib import Path

import pytest

from reforge_pixels.engine import EnginePaths
from reforge_pixels.audio import resolve_audio_actions
from reforge_pixels.media import AudioStreamInfo, MediaInfo
from reforge_pixels.models import load_models
from reforge_pixels.resolution import Resolution
from reforge_pixels.video import (
    VideoProcessingError, build_final_mux_command, estimate_chunk_temp_bytes,
    mux_final_output, nvenc_available, process_cfr_video, reconcile_decoded_frame_count,
    verify_muxed_audio,
)


def test_missing_ffmpeg_has_no_nvenc() -> None:
    assert not nvenc_available("definitely-missing-ffmpeg-executable")


def _media() -> MediaInfo:
    return MediaInfo(
        path=Path("video.mp4"), media_type="video", resolution=Resolution(1920, 1080),
        raw_width=1920, raw_height=1080, rotation=0, duration_seconds=10.0,
        frame_rate=30.0, nominal_frame_rate=30.0, video_codec="h264", pixel_format="yuv420p",
        audio_streams=1, subtitle_streams=0, audio_codecs=("aac",), color_transfer="bt709",
        color_primaries="bt709", is_hdr=False, unsupported_streams=(), is_variable_frame_rate=False,
    )


def test_chunk_space_estimate_uses_exact_native_scale() -> None:
    model = next(item for item in load_models() if item.id == "waifu2x-photo")
    assert estimate_chunk_temp_bytes(_media(), model, 2, 10) == 518_400_000


def test_short_final_chunk_uses_actual_decoded_frame_count() -> None:
    assert reconcile_decoded_frame_count(25, 18, 0, 25, 1) == (18, 18, True)
    assert reconcile_decoded_frame_count(120, 60, 120, 300, 2) == (60, 180, True)
    assert reconcile_decoded_frame_count(120, 120, 0, 300, 1) == (120, 300, False)
    with pytest.raises(VideoProcessingError, match="chunk 1"):
        reconcile_decoded_frame_count(10, 0, 0, 25, 1)


def test_chunk_space_estimate_includes_downscale_ai_intermediate() -> None:
    model = next(item for item in load_models() if item.id == "general-quality-4x")
    assert estimate_chunk_temp_bytes(_media(), model, 2, 10) == 1_762_560_000


def test_chunk_space_estimate_includes_every_repeated_pass() -> None:
    model = next(item for item in load_models() if item.id == "waifu2x-photo")
    assert estimate_chunk_temp_bytes(_media(), model, 4, 10) == 2_177_280_000


def test_low_disk_is_rejected_before_processing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    ffmpeg = tmp_path / "ffmpeg.exe"
    ffmpeg.write_bytes(b"")
    monkeypatch.setattr("reforge_pixels.video.find_tool", lambda name: tmp_path / name)
    model = next(item for item in load_models() if item.id == "waifu2x-photo")
    monkeypatch.setattr("reforge_pixels.video.shutil.disk_usage", lambda path: type("Usage", (), {"free": 1})())
    with pytest.raises(VideoProcessingError, match="Not enough temporary disk space"):
        process_cfr_video(
            _media(), EnginePaths(tmp_path / "engine.exe", tmp_path, "waifu2x"), model, 2,
            tmp_path / "output.mp4", ffmpeg_path=ffmpeg,
        )


def test_final_mux_command_maps_stream_and_transcodes_opus_for_mp4() -> None:
    stream = AudioStreamInfo(
        index=3, codec="opus", channels=2, channel_layout="stereo", sample_rate=48000,
        bit_rate=128000, language="eng", title="Main", dispositions=("default",),
        start_time=0.0, duration_seconds=10.0, metadata=(("language", "eng"),),
    )
    media = replace(_media(), audio_streams=1, audio_codecs=("opus",), audio_details=(stream,))
    command = build_final_mux_command(
        "ffmpeg", Path("joined.mkv"), media, Path("result.mp4"),
        resolve_audio_actions(media, ".mp4"),
    )
    map_positions = [index for index, value in enumerate(command) if value == "-map"]
    assert command[map_positions[1] + 1] == "1:3"
    codec_index = command.index("-c:a:0")
    bitrate_index = command.index("-b:a:0")
    assert command[codec_index:codec_index + 2] == ["-c:a:0", "aac"]
    assert command[bitrate_index:bitrate_index + 2] == ["-b:a:0", "192k"]
    assert "language=eng" in command
    assert "handler_name=Main" in command
    assert "-c" not in command
    assert "-shortest" not in command
    assert command[command.index("-t") + 1] == "10"


def test_audio_verification_allows_inferred_default_on_first_stream() -> None:
    source_stream = AudioStreamInfo(
        index=1, codec="opus", channels=2, channel_layout="stereo", sample_rate=48000,
        bit_rate=128000, language="eng", title="Main", dispositions=(),
        start_time=0.0, duration_seconds=10.0, metadata=(),
    )
    output_stream = replace(source_stream, dispositions=("default",))
    source = replace(_media(), audio_streams=1, audio_codecs=("opus",), audio_details=(source_stream,))
    output = replace(source, audio_details=(output_stream,))

    verify_muxed_audio(source, output, resolve_audio_actions(source, ".mkv"))


def test_audio_verification_allows_undefined_language_to_be_omitted() -> None:
    source_stream = AudioStreamInfo(
        index=1, codec="aac", channels=1, channel_layout="mono", sample_rate=48000,
        bit_rate=128000, language="und", title=None, dispositions=("default",),
        start_time=0.0, duration_seconds=10.0, metadata=(),
    )
    output_stream = replace(source_stream, language=None)
    source = replace(_media(), audio_streams=1, audio_codecs=("aac",), audio_details=(source_stream,))
    output = replace(source, audio_details=(output_stream,))

    verify_muxed_audio(source, output, resolve_audio_actions(source, ".mkv"))


def test_final_mux_failure_removes_partial_output(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    media = replace(_media(), audio_streams=1, audio_codecs=("aac",))
    output = tmp_path / "partial.mp4"

    def fail_after_writing(command: list[str], stage: str, cancelled=None) -> None:
        Path(command[-1]).write_bytes(b"partial")
        raise VideoProcessingError(f"{stage} failed")

    monkeypatch.setattr("reforge_pixels.video._run", fail_after_writing)
    with pytest.raises(VideoProcessingError, match="Final muxing failed"):
        mux_final_output(
            "ffmpeg", "ffprobe", tmp_path / "joined.mkv", media, output,
            resolve_audio_actions(media, ".mp4"),
        )
    assert not output.exists()
