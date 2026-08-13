"""Capture the Checkpoint 4 GUI states using the real application widgets."""

from __future__ import annotations

import argparse
import time
from pathlib import Path

from PySide6.QtWidgets import QApplication, QMessageBox

from reforge_pixels.app import MainWindow
from reforge_pixels.media import inspect_media


def capture(window: MainWindow, application: QApplication, destination: Path) -> None:
    window.show()
    application.processEvents()
    window.grab().save(str(destination))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("media", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    application = QApplication([])
    window = MainWindow()
    capture(window, application, args.output / "01-empty.png")

    window._inspection_succeeded(inspect_media(args.media))
    capture(window, application, args.output / "02-ready-general.png")
    window.content_combo.setCurrentIndex(window.content_combo.findData("Anime"))
    capture(window, application, args.output / "03-ready-anime.png")

    window.upscale_button.setEnabled(False)
    window.progress_bar.setVisible(True)
    window.progress_bar.setValue(43)
    window.cancel_button.setVisible(True)
    window._progress_started = time.monotonic() - 12
    window._current_stage = "Upscaling"
    window._on_progress(43)
    capture(window, application, args.output / "04-processing.png")

    QMessageBox.information = lambda *args, **kwargs: QMessageBox.StandardButton.Ok  # type: ignore[method-assign]
    QMessageBox.critical = lambda *args, **kwargs: QMessageBox.StandardButton.Ok  # type: ignore[method-assign]
    window._upscale_completed(str(args.output / "example-upscaled-2x.png"))
    capture(window, application, args.output / "05-completed.png")
    window.progress_bar.setValue(100)
    window.progress_bar.setVisible(True)
    window._upscale_failed("Demonstration error details")
    capture(window, application, args.output / "06-error.png")
    window.close()


if __name__ == "__main__":
    main()
