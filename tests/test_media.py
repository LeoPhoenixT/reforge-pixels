from reforge_pixels.media import (
    _audio_stream_info, _discarded_stream_descriptions, _dolby_vision_base_layer, _hdr_kind, _is_hdr_stream,
    _is_variable_frame_rate, _unsupported_stream_descriptions,
)


def test_detects_pq_hdr() -> None:
    assert _is_hdr_stream({"pix_fmt": "yuv420p10le", "color_transfer": "smpte2084", "color_primaries": "bt2020"})


def test_detects_high_bit_depth_even_without_hdr_tags() -> None:
    assert _is_hdr_stream({"pix_fmt": "yuv420p10le"})


def test_classifies_hlg_and_high_bit_depth_separately() -> None:
    assert _hdr_kind({"pix_fmt": "yuv420p10le", "color_transfer": "arib-std-b67"}) == "hlg"
    assert _hdr_kind({"pix_fmt": "yuv420p10le", "color_transfer": "bt709"}) == "high-bit-depth"


def test_dolby_vision_detection_has_priority_and_records_base_layer() -> None:
    stream = {
        "pix_fmt": "yuv420p10le", "color_transfer": "arib-std-b67",
        "side_data_list": [{
            "side_data_type": "DOVI configuration record", "bl_present_flag": 1,
            "dv_bl_signal_compatibility_id": 4,
        }],
    }
    assert _hdr_kind(stream) == "dolby-vision"
    assert _dolby_vision_base_layer(stream)


def test_dolby_vision_incompatible_layer_is_not_accepted_as_a_base() -> None:
    stream = {"side_data_list": [{
        "side_data_type": "DOVI configuration record", "bl_present_flag": 1,
        "dv_bl_signal_compatibility_id": 0,
    }]}
    assert not _dolby_vision_base_layer(stream)


def test_sdr_eight_bit_is_not_hdr() -> None:
    assert not _is_hdr_stream({"pix_fmt": "yuv420p", "color_transfer": "bt709", "color_primaries": "bt709"})


def test_detects_variable_frame_rate_from_rate_difference() -> None:
    assert _is_variable_frame_rate({"avg_frame_rate": "24000/1001", "r_frame_rate": "30/1"})


def test_accepts_matching_constant_frame_rates() -> None:
    assert not _is_variable_frame_rate({"avg_frame_rate": "30000/1001", "r_frame_rate": "30000/1001"})


def test_blocks_unsupported_non_audio_streams_but_defers_audio_to_output_policy() -> None:
    video = {"codec_type": "video", "codec_name": "h264"}
    streams = [
        video,
        {"codec_type": "audio", "codec_name": "aac"},
        {"codec_type": "audio", "codec_name": "vorbis"},
        {"codec_type": "subtitle", "codec_name": "ass"},
        {"codec_type": "data", "codec_name": "bin_data"},
        *({"codec_type": "data", "codec_tag_string": "mebx"} for _ in range(5)),
    ]
    reasons = _unsupported_stream_descriptions(streams, video)
    assert len(reasons) == 2
    assert not any("vorbis" in reason for reason in reasons)
    assert any("Subtitle" in reason for reason in reasons)
    assert any("Data" in reason for reason in reasons)
    assert not any("mebx" in reason for reason in reasons)
    notices = _discarded_stream_descriptions(streams, video)
    assert notices == ("5 Apple QuickTime metadata streams ('mebx') will be removed from output",)


def test_records_audio_stream_metadata_and_timing() -> None:
    stream = _audio_stream_info({
        "index": 4, "codec_name": "opus", "channels": 6, "channel_layout": "5.1",
        "sample_rate": "48000", "bit_rate": "256000", "start_time": "0.021",
        "duration": "10.5", "tags": {"language": "jpn", "title": "Surround"},
        "disposition": {"default": 1, "forced": 0, "comment": 1},
    })
    assert stream.index == 4
    assert stream.codec == "opus"
    assert (stream.channels, stream.channel_layout, stream.sample_rate) == (6, "5.1", 48000)
    assert (stream.language, stream.title) == ("jpn", "Surround")
    assert stream.dispositions == ("comment", "default")
    assert (stream.start_time, stream.duration_seconds) == (0.021, 10.5)
