import hashlib
from dataclasses import FrozenInstanceError
from pathlib import Path
from types import SimpleNamespace

import pytest

from reforge_pixels.engine import EngineError, EnginePaths, ProcessingCancelled, model_verification_scope, run_image_upscale, verify_model
from reforge_pixels.ffmpeg_encoders import encoder_query_scope
from reforge_pixels.media import AudioStreamInfo, MediaInfo
from reforge_pixels.models import ModelDefinition, ModelFile, ScaleRecipe
from reforge_pixels.resolution import Resolution
from reforge_pixels.video import audio_encoder_available, nvenc_available
from reforge_pixels.workers import ProcessingRequest, UpscaleThread


def _model(asset: ModelFile | None = None) -> ModelDefinition:
    return ModelDefinition(
        id="test", display_name="Test", engine_name="test", media_types=("video",),
        description="test", native_scales=(2,), model_files=(asset,) if asset else (), status="validated",
    )


def test_model_hash_is_reused_only_within_one_request_and_public_entry_checks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    asset_path = tmp_path / "model.bin"
    asset_path.write_bytes(b"valid")
    asset = ModelFile("model.bin", hashlib.sha256(b"valid").hexdigest())
    model = _model(asset)
    import reforge_pixels.engine as engine
    original = engine._sha256
    calls = []

    def counted(path: Path) -> str:
        calls.append(path)
        return original(path)

    monkeypatch.setattr(engine, "_sha256", counted)
    with model_verification_scope():
        verify_model(model, tmp_path)
        verify_model(model, tmp_path)
    assert len(calls) == 1
    asset_path.write_bytes(b"changed")
    with pytest.raises(EngineError, match="checksum"):
        run_image_upscale(
            EnginePaths(tmp_path / "engine.exe", tmp_path), model,
            tmp_path / "source.png", tmp_path / "output.png", 2,
        )
    assert len(calls) == 2


def test_ffmpeg_encoder_query_is_shared_within_video_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    import reforge_pixels.ffmpeg_encoders as encoders
    calls = []

    def fake_run(*args: object, **kwargs: object) -> SimpleNamespace:
        calls.append(args)
        return SimpleNamespace(returncode=0, stdout=" V..... h264_nvenc NVIDIA\n A..... aac AAC\n")

    monkeypatch.setattr(encoders.subprocess, "run", fake_run)
    with encoder_query_scope():
        assert nvenc_available("ffmpeg")
        assert audio_encoder_available("ffmpeg", "aac")
        assert not audio_encoder_available("ffmpeg", "libopus")
    assert len(calls) == 1
    assert nvenc_available("ffmpeg")
    assert len(calls) == 2


def test_worker_uses_explicit_cancellation_signal(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    media = MediaInfo(
        path=tmp_path / "input.mp4", media_type="video", resolution=Resolution(8, 8),
        raw_width=8, raw_height=8, rotation=0, duration_seconds=1, frame_rate=30,
        nominal_frame_rate=30, video_codec="h264", pixel_format="yuv420p", audio_streams=0,
        subtitle_streams=0, audio_codecs=(), color_transfer="bt709", color_primaries="bt709",
        is_hdr=False, unsupported_streams=(), is_variable_frame_rate=False,
    )
    request = ProcessingRequest(
        media, _model(), ScaleRecipe(2, 2, 1, "native"), tmp_path / "output.mp4",
        None, False, 92, True, "automatic", "block",
    )
    with pytest.raises(FrozenInstanceError):
        request.output = tmp_path / "other.mp4"  # type: ignore[misc]
    monkeypatch.setattr("reforge_pixels.workers.locate_engine", lambda _: object())
    monkeypatch.setattr(
        "reforge_pixels.workers.process_cfr_video",
        lambda *args, **kwargs: (_ for _ in ()).throw(ProcessingCancelled("different message")),
    )
    worker = UpscaleThread(request)
    cancelled = []
    failed = []
    worker.cancelled.connect(lambda: cancelled.append(True))
    worker.failed.connect(failed.append)
    worker.run()
    assert cancelled == [True]
    assert failed == []


def test_audio_details_control_legacy_summary_fields(tmp_path: Path) -> None:
    stream = AudioStreamInfo(
        index=2, codec="opus", channels=2, channel_layout="stereo", sample_rate=48_000,
        bit_rate=None, language=None, title=None, dispositions=(), start_time=None,
        duration_seconds=None, metadata=(),
    )
    media = MediaInfo(
        path=tmp_path / "input.mp4", media_type="video", resolution=Resolution(8, 8),
        raw_width=8, raw_height=8, rotation=0, duration_seconds=1, frame_rate=30,
        nominal_frame_rate=30, video_codec="h264", pixel_format="yuv420p", audio_streams=0,
        subtitle_streams=0, audio_codecs=(), color_transfer="bt709", color_primaries="bt709",
        is_hdr=False, unsupported_streams=(), is_variable_frame_rate=False,
        audio_details=(stream,),
    )
    assert media.audio_streams == 1
    assert media.audio_codecs == ("opus",)
