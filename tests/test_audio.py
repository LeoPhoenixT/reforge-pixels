from pathlib import Path

from reforge_pixels.audio import audio_blocking_reasons, resolve_audio_actions
from reforge_pixels.media import AudioStreamInfo, MediaInfo
from reforge_pixels.resolution import Resolution


def audio_stream(codec: str = "opus", index: int = 2) -> AudioStreamInfo:
    return AudioStreamInfo(
        index=index, codec=codec, channels=2, channel_layout="stereo", sample_rate=48000,
        bit_rate=128000, language="eng", title="Main audio", dispositions=("default",),
        start_time=0.0, duration_seconds=1.0,
        metadata=(("language", "eng"), ("title", "Main audio")),
    )


def video_media(*streams: AudioStreamInfo) -> MediaInfo:
    return MediaInfo(
        path=Path("source.mkv"), media_type="video", resolution=Resolution(640, 360),
        raw_width=640, raw_height=360, rotation=0, duration_seconds=1.0,
        frame_rate=30.0, nominal_frame_rate=30.0, video_codec="h264", pixel_format="yuv420p",
        audio_streams=len(streams), subtitle_streams=0,
        audio_codecs=tuple(stream.codec for stream in streams), color_transfer="bt709",
        color_primaries="bt709", is_hdr=False, unsupported_streams=(),
        is_variable_frame_rate=False, audio_details=streams,
    )


def test_automatic_opus_is_copied_to_mkv() -> None:
    action = resolve_audio_actions(video_media(audio_stream()), ".mkv")[0]
    assert action.kind == "copy"
    assert action.output_codec == "opus"
    assert "copied" in action.display()


def test_automatic_opus_is_converted_to_aac_for_mp4() -> None:
    action = resolve_audio_actions(video_media(audio_stream()), ".mp4")[0]
    assert action.kind == "transcode"
    assert action.target_codec == "aac"
    assert action.bitrate_kbps == 192
    assert "OPUS → AAC 192 kbps" in action.display()


def test_preserve_mode_blocks_incompatible_mp4_audio() -> None:
    actions = resolve_audio_actions(video_media(audio_stream()), ".mp4", "preserve")
    assert actions[0].kind == "block"
    assert "cannot be copied" in audio_blocking_reasons(actions)[0]


def test_explicit_conversion_and_removal_modes() -> None:
    source = video_media(audio_stream("flac"))
    aac = resolve_audio_actions(source, ".mkv", "aac")[0]
    opus = resolve_audio_actions(source, ".mkv", "opus")[0]
    removed = resolve_audio_actions(source, ".mp4", "remove")[0]
    assert (aac.kind, aac.target_codec) == ("transcode", "aac")
    assert (opus.kind, opus.target_codec) == ("transcode", "opus")
    assert removed.kind == "remove"


def test_opus_output_mode_is_blocked_for_mp4() -> None:
    actions = resolve_audio_actions(video_media(audio_stream("aac")), ".mp4", "opus")
    assert actions[0].kind == "block"
    assert audio_blocking_reasons(actions) == ("Opus output is currently supported only in MKV",)
