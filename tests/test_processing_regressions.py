import struct
import subprocess
import sys
import threading
import time
import zlib
from pathlib import Path

import pytest
from PIL import Image

from reforge_pixels.engine import EnginePaths, ProcessingCancelled, run_image_upscale
from reforge_pixels.image import run_safe_image_upscale
from reforge_pixels.media import inspect_media
from reforge_pixels.models import ModelDefinition
from reforge_pixels.video import VideoProcessingError, _run


def _model() -> ModelDefinition:
    return ModelDefinition(
        id="test", display_name="Test", engine_name="test-model", media_types=("image",),
        description="test", native_scales=(2,), model_files=(), status="validated",
    )


def _paths(tmp_path: Path) -> EnginePaths:
    directory = tmp_path / "models"
    directory.mkdir()
    return EnginePaths(Path(sys.executable), directory)


def _png_chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))


def _rgb16_png(path: Path) -> None:
    ihdr = struct.pack(">IIBBBBB", 1, 1, 16, 2, 0, 0, 0)
    pixels = b"\x00" + struct.pack(">HHH", 1000, 32000, 65535)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + _png_chunk(b"IHDR", ihdr)
                     + _png_chunk(b"IDAT", zlib.compress(pixels)) + _png_chunk(b"IEND", b""))


def test_high_depth_png_and_tiff_block_inspection_and_processing(tmp_path: Path) -> None:
    rgb = tmp_path / "rgb16.png"
    gray = tmp_path / "gray16.png"
    tiff = tmp_path / "gray16.tiff"
    ordinary = tmp_path / "gray8.png"
    _rgb16_png(rgb)
    Image.new("I;16", (1, 1), 32000).save(gray)
    Image.new("I;16", (1, 1), 32000).save(tiff)
    Image.new("L", (1, 1), 128).save(ordinary)
    with Image.open(rgb) as opened:
        assert opened.mode == "RGB"  # Pillow hides source depth here.
    for path in (rgb, gray, tiff):
        media = inspect_media(path)
        assert media.is_hdr and media.blocking_reasons
        with pytest.raises(Exception, match="high-bit-depth"):
            run_safe_image_upscale(EnginePaths(tmp_path / "engine", tmp_path), _model(),
                                   path, tmp_path / "out.png", 2)
        assert not (tmp_path / "out.png").exists()
    assert not inspect_media(ordinary).blocking_reasons


def test_silent_engine_cancel_does_not_publish_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    paths = _paths(tmp_path)
    output = tmp_path / "output.png"
    real_popen = subprocess.Popen
    marker = tmp_path / "started"

    def child(command: list[str], **kwargs: object) -> subprocess.Popen[str]:
        code = ("import pathlib,sys,time; "
                "pathlib.Path(sys.argv[1]).write_text('started'); "
                "pathlib.Path(sys.argv[2]).write_bytes(b'partial'); time.sleep(30)")
        return real_popen([sys.executable, "-c", code, str(marker), command[command.index("-o") + 1]],
                          **kwargs)  # type: ignore[arg-type,return-value]

    monkeypatch.setattr("reforge_pixels.engine.subprocess.Popen", child)
    watchdog = threading.Event()
    timer = threading.Timer(8, watchdog.set)
    timer.start()
    start = time.monotonic()
    try:
        with pytest.raises(ProcessingCancelled):
            run_image_upscale(paths, _model(), tmp_path / "input.png", output, 2,
                              cancelled=lambda: marker.exists() or watchdog.is_set())
    finally:
        timer.cancel()
    assert time.monotonic() - start < 10
    assert marker.exists()
    assert not output.exists()
    assert not (tmp_path / "output.partial.png").exists()


def test_image_engine_cancellation_just_before_publish(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    paths = _paths(tmp_path)
    output = tmp_path / "output.png"
    calls = 0

    def cancelled() -> bool:
        nonlocal calls
        calls += 1
        return calls >= 3

    def fake_drain(_process, _cancelled, _on_line):
        (tmp_path / "output.partial.png").write_bytes(b"ready")
        return 0, (), False

    monkeypatch.setattr("reforge_pixels.engine.subprocess.Popen", lambda *_args, **_kwargs: object())
    monkeypatch.setattr("reforge_pixels.engine.drain_process", fake_drain)
    with pytest.raises(ProcessingCancelled):
        run_image_upscale(paths, _model(), tmp_path / "input.png", output, 2,
                          cancelled=cancelled)
    assert not output.exists()
    assert not (tmp_path / "output.partial.png").exists()


def test_video_runner_drains_verbose_stderr_and_bounds_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    code = "import sys; sys.stderr.write('x'*1048576+'\\nTAIL\\n'); sys.exit(7)"
    real_popen = subprocess.Popen
    children: list[subprocess.Popen[str]] = []

    def tracked_child(command: list[str], **kwargs: object) -> subprocess.Popen[str]:
        child = real_popen(command, **kwargs)  # type: ignore[arg-type]
        children.append(child)
        return child  # type: ignore[return-value]

    monkeypatch.setattr("reforge_pixels.video.subprocess.Popen", tracked_child)

    def watchdog() -> None:
        for child in children:
            if child.poll() is None:
                child.kill()

    timer = threading.Timer(5, watchdog)
    timer.start()
    try:
        with pytest.raises(VideoProcessingError, match="TAIL") as error:
            _run([sys.executable, "-c", code], "Synthetic failure")
    finally:
        timer.cancel()
    assert len(str(error.value)) < 500


def test_runner_callback_failure_ends_child_and_reader() -> None:
    from reforge_pixels.subprocess_runner import drain_process

    before = {thread.ident for thread in threading.enumerate() if thread.name == "subprocess-output-reader"}
    child = subprocess.Popen(
        [sys.executable, "-c", "import sys,time; [print('x'*1000, flush=True) for _ in range(1000)]; time.sleep(30)"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    with pytest.raises(RuntimeError, match="callback"):
        drain_process(child, on_line=lambda _: (_ for _ in ()).throw(RuntimeError("callback")))
    assert child.poll() is not None
    assert not any(thread.name == "subprocess-output-reader" and thread.ident not in before
                   for thread in threading.enumerate())
