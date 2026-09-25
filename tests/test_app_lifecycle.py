import os
import subprocess
import sys
from pathlib import Path

import pytest


def test_offscreen_close_waits_for_inspection_and_upscale_threads() -> None:
    root = Path(__file__).resolve().parents[1]
    code = r'''
import gc, sys, time
from pathlib import Path
from PySide6.QtCore import QThread
from PySide6.QtWidgets import QApplication
import reforge_pixels.app as module

app = QApplication([])
window = module.MainWindow()
window.show()
def slow_inspect(path, cancelled=None):
    time.sleep(0.3)
    raise module.MediaInspectionError("finished")
module.inspect_media = slow_inspect
window.load_file("fixture.png")
start = time.monotonic()
window.close()
assert time.monotonic() - start < 0.2
assert window._closing and window._inspection is not None
while window._inspection is not None:
    app.processEvents()
    time.sleep(0.01)
app.processEvents()
assert not window.isVisible()
del window
gc.collect()

class SlowUpscale(QThread):
    def __init__(self, parent):
        super().__init__(parent)
        self.cancelled = False
    def cancel(self):
        self.cancelled = True
    def run(self):
        while not self.cancelled:
            time.sleep(0.01)

window = module.MainWindow()
window.show()
thread = SlowUpscale(window)
window._upscale = thread
thread.finished.connect(window._upscale_finished)
thread.start()
window.close()
assert window._closing and thread.cancelled
while window._upscale is not None:
    app.processEvents()
    time.sleep(0.01)
app.processEvents()
del window, thread
gc.collect()
print("lifecycle passed")
'''
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONPATH"] = str(root / "src")
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                            env=env, timeout=10)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "lifecycle passed" in result.stdout


def test_busy_state_blocks_reentry_and_clears_stale_media(monkeypatch: pytest.MonkeyPatch) -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    import reforge_pixels.app as module
    from reforge_pixels.media import MediaInfo
    from reforge_pixels.resolution import Resolution

    app = QApplication.instance() or QApplication([])
    window = module.MainWindow()
    old = MediaInfo(
        path=Path("old.png"), media_type="image", resolution=Resolution(8, 8),
        raw_width=8, raw_height=8, rotation=0, duration_seconds=None, frame_rate=None,
        nominal_frame_rate=None, video_codec="png", pixel_format="RGB", audio_streams=0,
        subtitle_streams=0, audio_codecs=(), color_transfer=None, color_primaries=None,
        is_hdr=False, unsupported_streams=(), is_variable_frame_rate=False,
    )
    monkeypatch.setattr(module, "locate_engine", lambda _: object())
    window._inspection_succeeded(old)
    assert window.upscale_button.isEnabled()
    monkeypatch.setattr(module.QFileDialog, "getSaveFileName",
                        lambda *args: pytest.fail("busy processing reopened the save dialog"))

    window._upscale = object()  # State remains busy even before a QThread event arrives.
    window.scale_combo.setCurrentIndex(1)
    assert not window.upscale_button.isEnabled()
    window.start_upscale()
    window.load_file("new.png")
    assert window._media is old
    window._upscale = None

    class SignalStub:
        def connect(self, _callback):
            pass

    class InspectionStub:
        succeeded = SignalStub()
        failed = SignalStub()
        finished = SignalStub()

        def __init__(self, path, parent):
            self.path = path

        def start(self):
            pass

    monkeypatch.setattr(module, "InspectionThread", InspectionStub)
    window.load_file("new.png")
    assert window._media is None
    assert not window.upscale_button.isEnabled()
    window.start_upscale()
    window._inspection = None
    window.close()
    del app
