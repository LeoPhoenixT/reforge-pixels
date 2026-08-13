"""PySide6 desktop interface for Reforge Pixels."""

from __future__ import annotations

import sys
import time
import argparse
from importlib.resources import files
from pathlib import Path

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QCheckBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from reforge_pixels.audio import AudioMode, audio_blocking_reasons, resolve_audio_actions
from reforge_pixels.hdr import HdrMode, hdr_blocking_reasons, hdr_label
from reforge_pixels.media import MediaInfo, MediaInspectionError, inspect_media
from reforge_pixels.engine import EngineError, ProcessingCancelled, default_output_path, locate_engine
from reforge_pixels.image import run_safe_image_upscale, validate_recipe_size
from reforge_pixels.models import ModelDefinition, ScaleRecipe, compatible_models, load_models
from reforge_pixels.resolution import resolution_summary
from reforge_pixels.video import VideoProcessingError, process_cfr_video
from reforge_pixels.self_test import run_self_test


def application_icon() -> QIcon:
    return QIcon(str(files("reforge_pixels").joinpath("resources/app-icon.png")))


class InspectionThread(QThread):
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, path: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.path = path

    def run(self) -> None:
        try:
            self.succeeded.emit(inspect_media(self.path))
        except MediaInspectionError as error:
            self.failed.emit(str(error))


class UpscaleThread(QThread):
    progressed = Signal(int)
    stage_changed = Signal(str)
    completed = Signal(str)
    failed = Signal(str)

    def __init__(self, media: MediaInfo, model: ModelDefinition, recipe: ScaleRecipe, output: Path,
                 noise_level: int | None, tta: bool, output_quality: int, webp_lossless: bool,
                 audio_mode: AudioMode, hdr_mode: HdrMode,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.media = media
        self.model = model
        self.recipe = recipe
        self.output = output
        self.noise_level = noise_level
        self.tta = tta
        self.output_quality = output_quality
        self.webp_lossless = webp_lossless
        self.audio_mode = audio_mode
        self.hdr_mode = hdr_mode
        self._cancel_requested = False

    def cancel(self) -> None:
        self._cancel_requested = True

    def run(self) -> None:
        paths = locate_engine(self.model)
        if not paths:
            self.failed.emit(f"The bundled {self.model.engine_id} engine or model directory was not found.")
            return
        try:
            if self.media.media_type == "image":
                run_safe_image_upscale(
                    paths, self.model, self.media.path, self.output, self.recipe.final_scale,
                    self.progressed.emit, cancelled=lambda: self._cancel_requested,
                    noise_level=self.noise_level, tta=self.tta,
                    recipe=self.recipe, output_quality=self.output_quality,
                    webp_lossless=self.webp_lossless,
                )
            else:
                process_cfr_video(
                    self.media,
                    paths,
                    self.model,
                    self.recipe.final_scale,
                    self.output,
                    progress=lambda stage, value: (self.stage_changed.emit(stage), self.progressed.emit(value)),
                    cancelled=lambda: self._cancel_requested,
                    noise_level=self.noise_level,
                    tta=self.tta,
                    recipe=self.recipe,
                    audio_mode=self.audio_mode,
                    hdr_mode=self.hdr_mode,
                )
            self.completed.emit(str(self.output))
        except (EngineError, VideoProcessingError, OSError, ValueError) as error:
            self.failed.emit(str(error))


class DropPanel(QFrame):
    file_dropped = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setAcceptDrops(True)
        self.setObjectName("dropPanel")
        self.setMinimumHeight(190)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title = QLabel("Drop an image or video here")
        title.setObjectName("dropTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint = QLabel("or choose a file from your computer")
        hint.setObjectName("muted")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        layout.addWidget(hint)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        urls = event.mimeData().urls()
        if len(urls) == 1 and urls[0].isLocalFile():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        urls = event.mimeData().urls()
        if len(urls) == 1 and urls[0].isLocalFile():
            self.file_dropped.emit(urls[0].toLocalFile())
            event.acceptProposedAction()


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Reforge Pixels")
        self.setWindowIcon(application_icon())
        self.resize(760, 600)
        self._media: MediaInfo | None = None
        self._inspection: InspectionThread | None = None
        self._upscale: UpscaleThread | None = None
        self._models = load_models()
        self._progress_started = 0.0
        self._current_stage = ""

        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(16)

        heading = QLabel("Reforge Pixels")
        heading.setObjectName("heading")
        subheading = QLabel("Offline image and video enhancement for NVIDIA RTX")
        subheading.setObjectName("muted")
        layout.addWidget(heading)
        layout.addWidget(subheading)

        self.drop_panel = DropPanel()
        self.drop_panel.file_dropped.connect(self.load_file)
        layout.addWidget(self.drop_panel)

        choose = QPushButton("Choose File")
        choose.clicked.connect(self.choose_file)
        layout.addWidget(choose)

        self.file_label = QLabel("No file selected")
        self.file_label.setWordWrap(True)
        self.file_label.setObjectName("fileInfo")
        layout.addWidget(self.file_label)

        controls = QHBoxLayout()
        input_column = QVBoxLayout()
        input_column.addWidget(QLabel("Input type"))
        self.input_type_combo = QComboBox()
        self.input_type_combo.addItem("Image", "image")
        self.input_type_combo.addItem("Video", "video")
        self.input_type_combo.currentIndexChanged.connect(self._input_type_changed)
        input_column.addWidget(self.input_type_combo)
        controls.addLayout(input_column, 1)

        content_column = QVBoxLayout()
        content_column.addWidget(QLabel("Content suggestion"))
        self.content_combo = QComboBox()
        self.content_combo.addItem("General", "General")
        self.content_combo.addItem("Anime / Illustration", "Anime")
        self.content_combo.currentIndexChanged.connect(self._content_changed)
        content_column.addWidget(self.content_combo)
        controls.addLayout(content_column, 1)

        model_column = QVBoxLayout()
        model_column.addWidget(QLabel("Model"))
        self.model_combo = QComboBox()
        self.model_combo.currentIndexChanged.connect(self._model_changed)
        model_column.addWidget(self.model_combo)
        controls.addLayout(model_column, 3)

        scale_column = QVBoxLayout()
        scale_column.addWidget(QLabel("Upscale"))
        self.scale_combo = QComboBox()
        self.scale_combo.currentIndexChanged.connect(self._scale_changed)
        scale_column.addWidget(self.scale_combo)
        controls.addLayout(scale_column, 2)
        layout.addLayout(controls)

        output_controls = QHBoxLayout()
        format_column = QVBoxLayout()
        format_column.addWidget(QLabel("Output format"))
        self.output_format_combo = QComboBox()
        self.output_format_combo.currentIndexChanged.connect(self._output_format_changed)
        format_column.addWidget(self.output_format_combo)
        output_controls.addLayout(format_column, 3)
        quality_column = QVBoxLayout()
        self.quality_label = QLabel("Quality")
        quality_column.addWidget(self.quality_label)
        self.quality_spin = QSpinBox()
        self.quality_spin.setRange(1, 100)
        self.quality_spin.setValue(92)
        quality_column.addWidget(self.quality_spin)
        output_controls.addLayout(quality_column, 1)
        self.webp_lossless_checkbox = QCheckBox("Lossless WebP")
        self.webp_lossless_checkbox.setChecked(True)
        self.webp_lossless_checkbox.toggled.connect(self._output_format_changed)
        output_controls.addWidget(self.webp_lossless_checkbox)
        audio_column = QVBoxLayout()
        self.audio_handling_label = QLabel("Audio handling")
        audio_column.addWidget(self.audio_handling_label)
        self.audio_handling_combo = QComboBox()
        self.audio_handling_combo.addItem("Automatic", "automatic")
        self.audio_handling_combo.addItem("Preserve when compatible", "preserve")
        self.audio_handling_combo.addItem("Convert to AAC", "aac")
        self.audio_handling_combo.addItem("Convert to Opus", "opus")
        self.audio_handling_combo.addItem("Remove audio", "remove")
        self.audio_handling_combo.currentIndexChanged.connect(self._audio_handling_changed)
        audio_column.addWidget(self.audio_handling_combo)
        output_controls.addLayout(audio_column, 2)
        layout.addLayout(output_controls)

        self.audio_policy_label = QLabel("Audio: choose a video to inspect streams.")
        self.audio_policy_label.setWordWrap(True)
        self.audio_policy_label.setObjectName("muted")
        layout.addWidget(self.audio_policy_label)

        hdr_controls = QHBoxLayout()
        hdr_column = QVBoxLayout()
        self.hdr_handling_label = QLabel("HDR handling")
        hdr_column.addWidget(self.hdr_handling_label)
        self.hdr_handling_combo = QComboBox()
        self.hdr_handling_combo.addItem("Convert HDR to SDR (BT.709)", "convert-sdr")
        self.hdr_handling_combo.addItem("Block HDR input", "block")
        self.hdr_handling_combo.currentIndexChanged.connect(self._hdr_handling_changed)
        hdr_column.addWidget(self.hdr_handling_combo)
        hdr_controls.addLayout(hdr_column, 1)
        layout.addLayout(hdr_controls)
        self.hdr_policy_label = QLabel("HDR: choose a video to inspect its colour format.")
        self.hdr_policy_label.setWordWrap(True)
        self.hdr_policy_label.setObjectName("muted")
        layout.addWidget(self.hdr_policy_label)

        enhancement_controls = QHBoxLayout()
        noise_column = QVBoxLayout()
        noise_column.addWidget(QLabel("Noise reduction"))
        self.noise_combo = QComboBox()
        self.noise_combo.setEnabled(False)
        noise_column.addWidget(self.noise_combo)
        enhancement_controls.addLayout(noise_column, 3)
        tta_column = QVBoxLayout()
        tta_column.addWidget(QLabel("Advanced quality"))
        self.tta_checkbox = QCheckBox("TTA — slower")
        self.tta_checkbox.setEnabled(False)
        tta_column.addWidget(self.tta_checkbox)
        enhancement_controls.addLayout(tta_column, 1)
        layout.addLayout(enhancement_controls)

        self.model_details = QLabel("Select a file to see compatible models.")
        self.model_details.setWordWrap(True)
        self.model_details.setObjectName("muted")
        layout.addWidget(self.model_details)

        self.resolution_label = QLabel("Input: —  →  Output: —")
        self.resolution_label.setObjectName("resolution")
        layout.addWidget(self.resolution_label)

        self.upscale_button = QPushButton("Upscale")
        self.upscale_button.setEnabled(False)
        self.upscale_button.clicked.connect(self.start_upscale)
        layout.addWidget(self.upscale_button)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setVisible(False)
        self.cancel_button.clicked.connect(self.cancel_upscale)
        layout.addWidget(self.cancel_button)

        self.status_label = QLabel("Ready")
        self.status_label.setObjectName("muted")
        layout.addWidget(self.status_label)

        self.setStyleSheet(
            """
            QMainWindow, QWidget { background: #11151b; color: #edf2f7; font-size: 14px; }
            QLabel#heading { font-size: 28px; font-weight: 700; }
            QLabel#dropTitle { font-size: 18px; font-weight: 600; }
            QLabel#muted { color: #9aa7b5; }
            QLabel#fileInfo, QLabel#resolution { background: #1a222c; padding: 12px; border-radius: 6px; }
            QFrame#dropPanel { border: 2px dashed #526274; border-radius: 10px; background: #161d25; }
            QPushButton { background: #3b82f6; border: 0; border-radius: 6px; padding: 10px 16px; font-weight: 600; }
            QPushButton:hover { background: #5593f7; }
            QPushButton:disabled { background: #334155; color: #7d8997; }
            QComboBox { background: #1a222c; border: 1px solid #3a4655; border-radius: 5px; padding: 8px; }
            """
        )
        self._populate_models("image")
        self._populate_output_formats("image")

    def choose_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Choose an image or video",
            "",
            "Media files (*.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff *.heic *.heif *.avif *.mp4 *.mkv *.mov *.webm);;All files (*)",
        )
        if path:
            self.load_file(path)

    def load_file(self, path: str) -> None:
        if self._inspection and self._inspection.isRunning():
            return
        self._set_loading(True)
        self.file_label.setText(Path(path).name)
        self.status_label.setText("Inspecting media…")
        self._inspection = InspectionThread(Path(path), self)
        self._inspection.succeeded.connect(self._inspection_succeeded)
        self._inspection.failed.connect(self._inspection_failed)
        self._inspection.finished.connect(lambda: self._set_loading(False))
        self._inspection.start()

    def _set_loading(self, loading: bool) -> None:
        self.drop_panel.setEnabled(not loading)

    def _inspection_succeeded(self, media: MediaInfo) -> None:
        self._media = media
        self.input_type_combo.blockSignals(True)
        self.input_type_combo.setCurrentIndex(0 if media.media_type == "image" else 1)
        self.input_type_combo.blockSignals(False)
        details = [media.media_type.title(), media.resolution.display(), media.video_codec]
        if media.is_hdr:
            details.append(hdr_label(media))
        if media.duration_seconds is not None:
            details.append(f"{media.duration_seconds:.1f} s")
        if media.frame_rate is not None:
            details.append(f"{media.frame_rate:.3g} FPS")
        self.file_label.setText(f"{media.path.name}\n" + "  •  ".join(details))
        self.status_label.setText("Media inspected successfully")
        self._populate_models(media.media_type)
        self._populate_output_formats(media.media_type)
        self._update_resolution()

    def _inspection_failed(self, message: str) -> None:
        self._media = None
        self.resolution_label.setText("Input: —  →  Output: —")
        self.status_label.setText("Unable to inspect file")
        self.upscale_button.setEnabled(False)
        QMessageBox.warning(self, "Unsupported media", message)

    def _populate_models(self, media_type: str) -> None:
        models = compatible_models(self._models, media_type, validated_only=False)  # type: ignore[arg-type]
        category = self.content_combo.currentData()
        previous = self.model_combo.currentData()
        previous_id = previous.id if isinstance(previous, ModelDefinition) else None
        selected_id = previous_id if any(model.id == previous_id for model in models) else None
        preferred = next((model for model in models if category in model.default_for), None)
        if preferred is not None:
            selected_id = preferred.id
        elif selected_id is None:
            suggested = next((model for model in models if model.recommendation == category), None)
            selected_id = (suggested or (models[0] if models else None)).id if models else None
        self.model_combo.blockSignals(True)
        self.model_combo.clear()
        for model in models:
            suffix = "" if model.available else " — validation pending"
            self.model_combo.addItem(model.display_name + suffix, model)
        if selected_id is not None:
            index = next((index for index, model in enumerate(models) if model.id == selected_id), 0)
            self.model_combo.setCurrentIndex(index)
        self.model_combo.setEnabled(bool(models))
        self.model_combo.blockSignals(False)
        self._model_changed()

    def _content_changed(self) -> None:
        self._populate_models(str(self.input_type_combo.currentData()))

    def _input_type_changed(self) -> None:
        media_type = str(self.input_type_combo.currentData())
        if self._media and self._media.media_type != media_type:
            self._media = None
            self.file_label.setText("No file selected")
            self.resolution_label.setText("Input: —  →  Output: —")
            self.upscale_button.setEnabled(False)
            self.status_label.setText("Input type changed; choose a matching file")
        self._populate_models(media_type)
        self._populate_output_formats(media_type)

    def _populate_output_formats(self, media_type: str) -> None:
        self.output_format_combo.blockSignals(True)
        self.output_format_combo.clear()
        if media_type == "video":
            self.output_format_combo.addItem("MP4", (".mp4", "MP4 video (*.mp4)"))
            self.output_format_combo.addItem("MKV", (".mkv", "Matroska video (*.mkv)"))
        else:
            self.output_format_combo.addItem("PNG", (".png", "PNG image (*.png)"))
            self.output_format_combo.addItem("JPEG", (".jpg", "JPEG image (*.jpg *.jpeg)"))
            self.output_format_combo.addItem("WebP", (".webp", "WebP image (*.webp)"))
        self.output_format_combo.blockSignals(False)
        self._output_format_changed()

    def _output_format_changed(self) -> None:
        data = self.output_format_combo.currentData()
        extension = data[0] if isinstance(data, tuple) else ""
        is_webp = extension == ".webp"
        show_quality = extension == ".jpg" or (is_webp and not self.webp_lossless_checkbox.isChecked())
        self.webp_lossless_checkbox.setVisible(is_webp)
        self.quality_label.setVisible(show_quality)
        self.quality_spin.setVisible(show_quality)
        self.quality_spin.setEnabled(show_quality)
        is_video = extension in {".mp4", ".mkv"}
        self.audio_handling_label.setVisible(is_video)
        self.audio_handling_combo.setVisible(is_video)
        self.audio_policy_label.setVisible(is_video)
        self.hdr_handling_label.setVisible(is_video)
        self.hdr_handling_combo.setVisible(is_video)
        self.hdr_policy_label.setVisible(is_video)
        self._refresh_audio_policy()
        self._refresh_hdr_policy()
        self._update_resolution()

    def _selected_audio_mode(self) -> AudioMode:
        value = str(self.audio_handling_combo.currentData() or "automatic")
        if value not in {"automatic", "preserve", "aac", "opus", "remove"}:
            return "automatic"
        return value  # type: ignore[return-value]

    def _audio_handling_changed(self) -> None:
        self._refresh_audio_policy()
        self._update_resolution()

    def _selected_hdr_mode(self) -> HdrMode:
        value = str(self.hdr_handling_combo.currentData() or "convert-sdr")
        return "block" if value == "block" else "convert-sdr"

    def _hdr_handling_changed(self) -> None:
        self._refresh_hdr_policy()
        self._update_resolution()

    def _refresh_hdr_policy(self) -> None:
        if not self._media or self._media.media_type != "video":
            self.hdr_policy_label.setText("HDR: choose a video to inspect its colour format.")
            self.hdr_handling_combo.setEnabled(False)
            return
        if not self._media.is_hdr:
            self.hdr_policy_label.setText("HDR: SDR input; no tone mapping will be applied.")
            self.hdr_handling_combo.setEnabled(False)
            return
        self.hdr_handling_combo.setEnabled(True)
        kind = hdr_label(self._media)
        if self._selected_hdr_mode() == "convert-sdr":
            detail = "decodable base layer required" if self._media.hdr_kind == "dolby-vision" else "BT.709 output"
            self.hdr_policy_label.setText(f"HDR: {kind} → 8-bit SDR ({detail}); HDR metadata will be removed.")
        else:
            self.hdr_policy_label.setText(f"HDR: {kind} will be blocked.")

    def _current_audio_actions(self):
        if not self._media or self._media.media_type != "video":
            return ()
        data = self.output_format_combo.currentData()
        if not isinstance(data, tuple):
            return ()
        if str(data[0]) not in {".mp4", ".mkv"}:
            return ()
        return resolve_audio_actions(self._media, str(data[0]), self._selected_audio_mode())

    def _refresh_audio_policy(self) -> None:
        if not self._media or self._media.media_type != "video":
            self.audio_policy_label.setText("Audio: choose a video to inspect streams.")
            return
        actions = self._current_audio_actions()
        if not actions:
            self.audio_policy_label.setText("Audio: no streams")
            return
        self.audio_policy_label.setText("  •  ".join(action.display() for action in actions))

    def _compatibility_blocking_reasons(self) -> tuple[str, ...]:
        if not self._media:
            return ()
        return (
            self._media.blocking_reasons
            + hdr_blocking_reasons(self._media, self._selected_hdr_mode())
            + audio_blocking_reasons(self._current_audio_actions())
        )

    def _processing_notices(self) -> tuple[str, ...]:
        return self._media.discarded_streams if self._media else ()

    def _model_changed(self) -> None:
        model = self.model_combo.currentData()
        previous_scale = self.scale_combo.currentData()
        self.scale_combo.blockSignals(True)
        self.scale_combo.clear()
        if isinstance(model, ModelDefinition):
            for recipe in model.scale_recipes:
                self.scale_combo.addItem(recipe.label, recipe)
            selected = next(
                (index for index, recipe in enumerate(model.scale_recipes)
                 if isinstance(previous_scale, ScaleRecipe) and recipe.final_scale == previous_scale.final_scale),
                0,
            )
            self.scale_combo.setCurrentIndex(selected)
        self.scale_combo.setEnabled(isinstance(model, ModelDefinition))
        self.scale_combo.blockSignals(False)
        self._update_model_details()

    def _scale_changed(self) -> None:
        self._update_noise_options()
        self._update_resolution()

    def _update_model_details(self) -> None:
        model = self.model_combo.currentData()
        if isinstance(model, ModelDefinition):
            native = ", ".join(f"{scale}x" for scale in model.native_scales)
            self.model_details.setText(
                f"{model.description} Engine: {model.engine_id}. Native scale: {native}. "
                f"Speed: {model.speed_class}. Recommendation only: {model.recommendation}."
            )
            self._update_noise_options()
            self.tta_checkbox.setChecked(False)
            self.tta_checkbox.setEnabled(model.supports_tta)
            self._update_resolution()
        else:
            self.model_details.setText("No compatible model available.")

    def _update_noise_options(self) -> None:
        model = self.model_combo.currentData()
        recipe = self.scale_combo.currentData()
        self.noise_combo.clear()
        if not isinstance(model, ModelDefinition) or not isinstance(recipe, ScaleRecipe):
            self.noise_combo.addItem("Not adjustable", None)
            self.noise_combo.setEnabled(False)
            return
        options = model.noise_options_for(recipe.inference_scale)
        if not options:
            self.noise_combo.addItem("Not adjustable", None)
            self.noise_combo.setEnabled(False)
            return
        for option in options:
            self.noise_combo.addItem(option.label, option.value)
        self.noise_combo.setEnabled(True)

    def _update_resolution(self) -> None:
        if not self._media:
            self.resolution_label.setText("Input: —  →  Output: —")
            self.upscale_button.setEnabled(False)
            return
        recipe = self.scale_combo.currentData()
        if not isinstance(recipe, ScaleRecipe):
            return
        scale = recipe.final_scale
        self.resolution_label.setText(resolution_summary(self._media.resolution, scale))
        try:
            validate_recipe_size(self._media.resolution.width, self._media.resolution.height, recipe)
        except EngineError as error:
            self.upscale_button.setEnabled(False)
            self.upscale_button.setToolTip(str(error))
            self.status_label.setText(str(error))
        else:
            model = self.model_combo.currentData()
            reasons = self._compatibility_blocking_reasons()
            if not reasons and isinstance(model, ModelDefinition) and locate_engine(model) is not None:
                self.upscale_button.setEnabled(True)
                self.upscale_button.setToolTip("")
                notices = self._processing_notices()
                status = "Ready to upscale"
                if notices:
                    status += "\n• " + "\n• ".join(notices)
                self.status_label.setText(status)
            elif reasons:
                self.upscale_button.setEnabled(False)
                self.upscale_button.setToolTip("This file is blocked by the current compatibility policy.")
                self.status_label.setText("Cannot process this video:\n• " + "\n• ".join(reasons))
            else:
                self.upscale_button.setEnabled(False)
                self.upscale_button.setToolTip("The selected bundled engine or model directory was not found.")

    def start_upscale(self) -> None:
        model = self.model_combo.currentData()
        recipe = self.scale_combo.currentData()
        if not self._media or not isinstance(model, ModelDefinition) or not isinstance(recipe, ScaleRecipe):
            return
        scale = recipe.final_scale
        noise_level = self.noise_combo.currentData()
        if noise_level is not None:
            noise_level = int(noise_level)
        format_data = self.output_format_combo.currentData()
        if not isinstance(format_data, tuple):
            return
        extension, file_filter = format_data
        suggested = default_output_path(self._media.path, scale, extension)
        output, _ = QFileDialog.getSaveFileName(
            self,
            "Save upscaled video" if self._media.media_type == "video" else "Save upscaled image",
            str(suggested),
            file_filter,
        )
        if not output:
            return
        output_path = Path(output)
        if output_path.suffix.lower() != extension:
            output_path = output_path.with_suffix(extension)
        if output_path.resolve() == self._media.path.resolve():
            QMessageBox.warning(self, "Invalid output", "The output cannot overwrite the input file.")
            return
        self.upscale_button.setEnabled(False)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(True)
        self.status_label.setText(f"Upscaling {self._media.media_type} on the GPU…")
        self._upscale = UpscaleThread(
            self._media, model, recipe, output_path, noise_level,
            self.tta_checkbox.isChecked(), self.quality_spin.value(),
            self.webp_lossless_checkbox.isChecked(), self._selected_audio_mode(),
            self._selected_hdr_mode(), self,
        )
        self._progress_started = time.monotonic()
        self._current_stage = "Upscaling"
        self._upscale.progressed.connect(self._on_progress)
        self._upscale.stage_changed.connect(self._on_stage_changed)
        self._upscale.completed.connect(self._upscale_completed)
        self._upscale.failed.connect(self._upscale_failed)
        self._upscale.start()

        self.cancel_button.setVisible(True)

    def _on_stage_changed(self, stage: str) -> None:
        self._current_stage = stage

    def _on_progress(self, value: int) -> None:
        self.progress_bar.setValue(value)
        elapsed = max(0.0, time.monotonic() - self._progress_started)
        details = [self._current_stage, f"{value}%", f"elapsed {self._format_duration(elapsed)}"]
        if value > 0 and value < 100:
            remaining = elapsed * (100 - value) / value
            details.append(f"about {self._format_duration(remaining)} remaining")
        if self._media and self._media.media_type == "video" and self._media.duration_seconds and self._media.frame_rate:
            total_frames = self._media.frame_count or max(
                1, round(self._media.duration_seconds * self._media.frame_rate)
            )
            processed_frames = min(total_frames, round(min(value, 85) / 85 * total_frames))
            if processed_frames and elapsed:
                details.append(f"{processed_frames}/{total_frames} frames")
                details.append(f"{processed_frames / elapsed:.2f} FPS")
        self.status_label.setText("  •  ".join(details))

    @staticmethod
    def _format_duration(seconds: float) -> str:
        seconds = max(0, round(seconds))
        minutes, seconds = divmod(seconds, 60)
        hours, minutes = divmod(minutes, 60)
        if hours:
            return f"{hours:d}:{minutes:02d}:{seconds:02d}"
        return f"{minutes:d}:{seconds:02d}"

    def cancel_upscale(self) -> None:
        if self._upscale and self._upscale.isRunning():
            self._upscale.cancel()
            self.cancel_button.setEnabled(False)
            self.status_label.setText("Cancelling…")

    def _upscale_completed(self, output: str) -> None:
        self.progress_bar.setValue(100)
        self.cancel_button.setVisible(False)
        self.cancel_button.setEnabled(True)
        self.status_label.setText(f"Completed: {output}")
        self._update_resolution()
        QMessageBox.information(self, "Upscale complete", f"Saved to:\n{output}")

    def _upscale_failed(self, message: str) -> None:
        self.cancel_button.setVisible(False)
        self.cancel_button.setEnabled(True)
        if message == "Processing was cancelled":
            self.progress_bar.setVisible(False)
            self.status_label.setText("Cancelled")
        else:
            self.status_label.setText("Upscaling failed")
            QMessageBox.critical(self, "Upscaling failed", message)
        self._update_resolution()


def main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--self-test-report", type=Path)
    arguments, _ = parser.parse_known_args()
    if arguments.self_test_report:
        return 0 if run_self_test(arguments.self_test_report) else 1
    application = QApplication(sys.argv)
    application.setApplicationName("Reforge Pixels")
    application.setWindowIcon(application_icon())
    window = MainWindow()
    window.show()
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
