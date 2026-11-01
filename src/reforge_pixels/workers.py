"""Background inspection and processing workers for the desktop UI."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QWidget

from reforge_pixels.audio import AudioMode
from reforge_pixels.engine import EngineError, ProcessingCancelled, locate_engine
from reforge_pixels.hdr import HdrMode
from reforge_pixels.image import run_safe_image_upscale
from reforge_pixels.media import MediaInfo, MediaInspectionError, inspect_media
from reforge_pixels.models import ModelDefinition, ScaleRecipe
from reforge_pixels.video import VideoProcessingError, process_cfr_video


@dataclass(frozen=True, slots=True)
class ProcessingRequest:
    media: MediaInfo
    model: ModelDefinition
    recipe: ScaleRecipe
    output: Path
    noise_level: int | None
    tta: bool
    output_quality: int
    webp_lossless: bool
    audio_mode: AudioMode
    hdr_mode: HdrMode


class InspectionThread(QThread):
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(
        self, path: Path, parent: QWidget | None = None,
        inspector: Callable[..., MediaInfo] = inspect_media,
    ) -> None:
        super().__init__(parent)
        self.path = path
        self._inspector = inspector
        self._cancel_requested = False

    def cancel(self) -> None:
        self._cancel_requested = True

    def run(self) -> None:
        try:
            media = self._inspector(self.path, cancelled=lambda: self._cancel_requested)
            if not self._cancel_requested:
                self.succeeded.emit(media)
        except MediaInspectionError as error:
            if not self._cancel_requested:
                self.failed.emit(str(error))


class UpscaleThread(QThread):
    progressed = Signal(int)
    stage_changed = Signal(str)
    completed = Signal(str)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, request: ProcessingRequest, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.request = request
        self._cancel_requested = False

    def cancel(self) -> None:
        self._cancel_requested = True

    def run(self) -> None:
        request = self.request
        if self._cancel_requested:
            self.cancelled.emit()
            return
        paths = locate_engine(request.model)
        if not paths:
            self.failed.emit(f"The bundled {request.model.engine_id} engine or model directory was not found.")
            return
        try:
            if request.media.media_type == "image":
                run_safe_image_upscale(
                    paths, request.model, request.media.path, request.output, request.recipe.final_scale,
                    self.progressed.emit, cancelled=lambda: self._cancel_requested,
                    noise_level=request.noise_level, tta=request.tta,
                    recipe=request.recipe, output_quality=request.output_quality,
                    webp_lossless=request.webp_lossless,
                )
            else:
                process_cfr_video(
                    request.media, paths, request.model, request.recipe.final_scale, request.output,
                    progress=lambda stage, value: (self.stage_changed.emit(stage), self.progressed.emit(value)),
                    cancelled=lambda: self._cancel_requested,
                    noise_level=request.noise_level, tta=request.tta, recipe=request.recipe,
                    audio_mode=request.audio_mode, hdr_mode=request.hdr_mode,
                )
            self.completed.emit(str(request.output))
        except ProcessingCancelled:
            self.cancelled.emit()
        except (EngineError, VideoProcessingError, OSError, ValueError) as error:
            self.failed.emit(str(error))
