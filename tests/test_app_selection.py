import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from reforge_pixels.app import MainWindow
from reforge_pixels.media import MediaInfo
from reforge_pixels.resolution import Resolution


def _image_media() -> MediaInfo:
    return MediaInfo(
        path=Path("fixture.png"), media_type="image", resolution=Resolution(100, 50),
        raw_width=100, raw_height=50, rotation=0, duration_seconds=None,
        frame_rate=None, nominal_frame_rate=None, video_codec="png", pixel_format="rgb24",
        audio_streams=0, subtitle_streams=0, audio_codecs=(), color_transfer=None,
        color_primaries=None, is_hdr=False, unsupported_streams=(), is_variable_frame_rate=False,
    )


def _video_media(audio_codec: str = "aac", *, hdr: bool = False, mebx: int = 0) -> MediaInfo:
    return MediaInfo(
        path=Path("fixture.mp4"), media_type="video", resolution=Resolution(1920, 1080),
        raw_width=1920, raw_height=1080, rotation=0, duration_seconds=1.0,
        frame_rate=30.0, nominal_frame_rate=30.0, video_codec="h264", pixel_format="yuv420p",
        audio_streams=1, subtitle_streams=0, audio_codecs=(audio_codec,), color_transfer="bt709",
        color_primaries="bt2020" if hdr else "bt709", is_hdr=hdr,
        unsupported_streams=(), is_variable_frame_rate=False,
        color_space="bt2020nc" if hdr else "bt709", color_range="tv",
        hdr_kind="hlg" if hdr else "none",
        discarded_streams=(
            f"{mebx} Apple QuickTime metadata streams ('mebx') will be removed from output",
        ) if mebx else (),
    )


def test_model_first_selection_and_human_approved_defaults() -> None:
    application = QApplication.instance() or QApplication([])
    window = MainWindow()
    assert not window.windowIcon().isNull()
    assert window.model_combo.currentData().id == "waifu2x-photo"
    assert window.scale_combo.currentData().final_scale == 2
    assert window.scale_combo.currentText() == "2x (Native)"
    window._inspection_succeeded(_image_media())
    assert window.scale_combo.currentData().final_scale == 2
    assert window.model_combo.currentData().id == "waifu2x-photo"
    assert window.model_combo.count() == 7

    window.content_combo.setCurrentIndex(1)
    assert window.model_combo.currentData().id == "realcugan-pro"
    assert [window.scale_combo.itemData(index).final_scale for index in range(window.scale_combo.count())] == [2, 3, 4]
    assert window.scale_combo.itemText(2) == "4x (Repeated 2x AI)"
    window.close()
    del application


def test_inspection_forces_input_type_and_output_formats() -> None:
    application = QApplication.instance() or QApplication([])
    window = MainWindow()
    window._inspection_succeeded(_video_media())
    assert window.input_type_combo.currentData() == "video"
    assert [window.output_format_combo.itemData(index)[0] for index in range(window.output_format_combo.count())] == [".mp4", ".mkv"]
    assert all("video" in window.model_combo.itemData(index).media_types for index in range(window.model_combo.count()))
    assert window.quality_label.isHidden()
    assert window.quality_spin.isHidden()
    assert [window.audio_handling_combo.itemData(index) for index in range(window.audio_handling_combo.count())] == [
        "automatic", "preserve", "aac", "opus", "remove",
    ]
    assert "AAC copied" in window.audio_policy_label.text()

    window.input_type_combo.setCurrentIndex(0)
    assert window._media is None
    assert window.file_label.text() == "No file selected"
    assert [window.output_format_combo.itemData(index)[0] for index in range(window.output_format_combo.count())] == [".png", ".jpg", ".webp"]
    assert window.quality_label.isHidden()
    window.output_format_combo.setCurrentIndex(1)
    assert not window.quality_label.isHidden()
    assert not window.quality_spin.isHidden()
    window.output_format_combo.setCurrentIndex(2)
    assert window.quality_label.isHidden()
    window.webp_lossless_checkbox.setChecked(False)
    assert not window.quality_label.isHidden()
    window.close()
    del application


def test_audio_policy_recomputes_for_output_container_and_mode() -> None:
    application = QApplication.instance() or QApplication([])
    window = MainWindow()
    window._inspection_succeeded(_video_media("opus"))
    assert "OPUS → AAC 192 kbps" in window.audio_policy_label.text()
    window.output_format_combo.setCurrentIndex(1)
    assert "OPUS copied" in window.audio_policy_label.text()
    window.output_format_combo.setCurrentIndex(0)
    window.audio_handling_combo.setCurrentIndex(1)
    assert "blocked" in window.audio_policy_label.text()
    assert "cannot be copied safely" in window.status_label.text()
    window.audio_handling_combo.setCurrentIndex(4)
    assert "removed by user selection" in window.audio_policy_label.text()
    window.close()
    del application


def test_hdr_policy_is_visible_and_output_aware() -> None:
    application = QApplication.instance() or QApplication([])
    window = MainWindow()
    window._inspection_succeeded(_video_media(hdr=True))
    assert window.hdr_handling_combo.isEnabled()
    assert window.hdr_handling_combo.currentData() == "convert-sdr"
    assert "HLG → 8-bit SDR" in window.hdr_policy_label.text()
    assert not any("HDR" in reason for reason in window._compatibility_blocking_reasons())
    window.hdr_handling_combo.setCurrentIndex(1)
    assert any("HLG input is blocked" in reason for reason in window._compatibility_blocking_reasons())
    window.close()
    del application


def test_known_apple_metadata_is_one_notice_and_does_not_block(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("reforge_pixels.app.locate_engine", lambda _model: object())
    application = QApplication.instance() or QApplication([])
    window = MainWindow()
    window._inspection_succeeded(_video_media(hdr=True, mebx=5))
    assert not window._compatibility_blocking_reasons()
    assert "5 Apple QuickTime metadata streams" in window.status_label.text()
    assert window.status_label.text().count("mebx") == 1
    window.close()
    del application
