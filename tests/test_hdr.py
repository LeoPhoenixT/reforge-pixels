from dataclasses import replace
from pathlib import Path

import pytest

from reforge_pixels.hdr import (
    HDR_TO_SDR_FILTER, HIGH_BIT_SDR_FILTER, hdr_blocking_reasons, hdr_filter,
    verify_sdr_output,
)
from reforge_pixels.media import MediaInfo
from reforge_pixels.resolution import Resolution


def _media(**changes) -> MediaInfo:
    base = MediaInfo(
        path=Path("hdr.mkv"), media_type="video", resolution=Resolution(1920, 1080),
        raw_width=1920, raw_height=1080, rotation=0, duration_seconds=1.0,
        frame_rate=30.0, nominal_frame_rate=30.0, video_codec="hevc", pixel_format="yuv420p10le",
        audio_streams=0, subtitle_streams=0, audio_codecs=(), color_transfer="smpte2084",
        color_primaries="bt2020", is_hdr=True, unsupported_streams=(), is_variable_frame_rate=False,
        color_space="bt2020nc", color_range="tv", hdr_kind="pq",
    )
    return replace(base, **changes)


def test_pq_and_hlg_use_pinned_tone_map_recipe() -> None:
    assert hdr_filter(_media(), "convert-sdr") == HDR_TO_SDR_FILTER
    assert hdr_filter(_media(hdr_kind="hlg", color_transfer="arib-std-b67"), "convert-sdr") == HDR_TO_SDR_FILTER


def test_high_bit_depth_sdr_uses_gamut_and_dither_without_hdr_tone_map() -> None:
    media = _media(hdr_kind="high-bit-depth", color_transfer="bt709", color_primaries="bt709")
    assert hdr_filter(media, "convert-sdr") == HIGH_BIT_SDR_FILTER


def test_dolby_vision_requires_a_base_layer() -> None:
    media = _media(hdr_kind="dolby-vision", dolby_vision_base_layer=False)
    assert "no decodable base layer" in hdr_blocking_reasons(media, "convert-sdr")[0]
    assert not hdr_blocking_reasons(replace(media, dolby_vision_base_layer=True), "convert-sdr")


def test_block_mode_rejects_hdr_but_not_sdr() -> None:
    assert hdr_blocking_reasons(_media(), "block")
    assert not hdr_blocking_reasons(
        _media(is_hdr=False, hdr_kind="none", pixel_format="yuv420p", color_transfer="bt709"), "block"
    )


def test_sdr_output_verification_requires_complete_bt709_tags() -> None:
    output = _media(
        is_hdr=False, hdr_kind="none", pixel_format="yuv420p", color_transfer="bt709",
        color_primaries="bt709", color_space="bt709", color_range="tv", hdr_side_data=(),
    )
    verify_sdr_output(output)
    with pytest.raises(ValueError, match="color transfer"):
        verify_sdr_output(replace(output, color_transfer=None))
    with pytest.raises(ValueError, match="stale HDR side data"):
        verify_sdr_output(replace(output, hdr_side_data=("DOVI configuration record",)))
