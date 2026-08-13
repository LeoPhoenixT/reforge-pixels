from pathlib import Path

from reforge_pixels import self_test


def test_self_test_reports_missing_engine(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(self_test, "find_tool", lambda name: tmp_path / name)
    monkeypatch.setattr(self_test, "locate_engine", lambda model=None: None)
    report = tmp_path / "report.json"
    assert not self_test.run_self_test(report)
    assert '"success": false' in report.read_text(encoding="utf-8")
    assert "engine/model directory was not found" in report.read_text(encoding="utf-8")
