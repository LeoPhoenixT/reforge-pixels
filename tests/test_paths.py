from reforge_pixels.paths import application_root, platform_name
from reforge_pixels.paths import find_tool
import sys
import pytest
from pathlib import Path


def test_development_application_root_is_repository() -> None:
    assert (application_root() / "pyproject.toml").is_file()


def test_platform_name_is_supported() -> None:
    assert platform_name() in {"windows", "linux"}


@pytest.mark.parametrize("marker", ["frozen", "__compiled__"])
def test_portable_missing_tool_never_falls_back_to_path(monkeypatch, tmp_path: Path, marker: str) -> None:
    import reforge_pixels.paths as paths
    if marker == "frozen":
        monkeypatch.setattr(sys, "frozen", True, raising=False)
    else:
        monkeypatch.setattr(paths, "__compiled__", object(), raising=False)
    monkeypatch.setattr(paths, "application_root", lambda: tmp_path)
    def unexpected_lookup(_name):
        pytest.fail("A portable application must not search PATH")
    monkeypatch.setattr(paths.shutil, "which", unexpected_lookup)
    assert find_tool("ffmpeg") is None
    bundled = tmp_path / "runtime" / "tools" / platform_name() / ("ffmpeg.exe" if sys.platform == "win32" else "ffmpeg")
    bundled.parent.mkdir(parents=True)
    bundled.touch()
    assert find_tool("ffmpeg") == bundled
