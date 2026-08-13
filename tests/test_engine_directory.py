import subprocess
import sys
from pathlib import Path

import pytest

from reforge_pixels.engine import EngineError, EnginePaths, run_directory_upscale
from reforge_pixels.models import ModelDefinition


def _model() -> ModelDefinition:
    return ModelDefinition(
        id="test",
        display_name="Test",
        engine_name="test-model",
        media_types=("video",),
        description="test",
        native_scales=(2,),
        model_files=(),
        status="validated",
    )


def _paths(tmp_path: Path) -> EnginePaths:
    models = tmp_path / "models"
    models.mkdir()
    return EnginePaths(Path(sys.executable), models)


def test_directory_runner_drains_large_child_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    output = tmp_path / "output"
    real_popen = subprocess.Popen
    child_code = (
        "import pathlib, sys\n"
        "for _ in range(20000): print('x' * 200, file=sys.stderr)\n"
        f"pathlib.Path({str(output / 'frame.png')!r}).write_bytes(b'png')\n"
    )

    def verbose_child(_command: list[str], **kwargs: object) -> subprocess.Popen[str]:
        return real_popen([sys.executable, "-c", child_code], **kwargs)  # type: ignore[arg-type,return-value]

    monkeypatch.setattr("reforge_pixels.engine.subprocess.Popen", verbose_child)
    source = tmp_path / "source"
    source.mkdir()

    run_directory_upscale(_paths(tmp_path), _model(), source, output, 2)

    assert (output / "frame.png").is_file()


def test_directory_runner_reports_tail_of_merged_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    real_popen = subprocess.Popen

    def failing_child(_command: list[str], **kwargs: object) -> subprocess.Popen[str]:
        return real_popen(
            [sys.executable, "-c", "import sys; print('tail marker', file=sys.stderr); raise SystemExit(7)"],
            **kwargs,  # type: ignore[arg-type]
        )  # type: ignore[return-value]

    monkeypatch.setattr("reforge_pixels.engine.subprocess.Popen", failing_child)
    source = tmp_path / "source"
    source.mkdir()

    with pytest.raises(EngineError, match="tail marker"):
        run_directory_upscale(_paths(tmp_path), _model(), source, tmp_path / "output", 2)
