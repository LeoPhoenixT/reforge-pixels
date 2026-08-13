"""Capability-driven NCNN/Vulkan engine discovery, validation, and execution."""

from __future__ import annotations

import hashlib
import os
import queue
import re
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from reforge_pixels.models import ModelDefinition
from reforge_pixels.paths import application_root, find_tool, platform_name
from reforge_pixels.resolution import VALID_SCALES


class EngineError(RuntimeError):
    pass


class ProcessingCancelled(EngineError):
    pass


@dataclass(frozen=True, slots=True)
class EnginePaths:
    executable: Path
    models_directory: Path
    engine_id: str = "realesrgan"


def locate_engine(model: ModelDefinition | str | None = None) -> EnginePaths | None:
    engine_id = model.engine_id if isinstance(model, ModelDefinition) else (model or "realesrgan")
    model_directory = model.model_directory if isinstance(model, ModelDefinition) else "models"
    candidates: list[Path] = []
    configured = os.environ.get(f"REFORGE_PIXELS_{engine_id.upper()}_ENGINE_DIR")
    if not configured and engine_id == "realesrgan":
        configured = os.environ.get("REFORGE_PIXELS_ENGINE_DIR")
    if configured:
        candidates.append(Path(configured))

    project_root = application_root()
    executable_base = {
        "realesrgan": "realesrgan-ncnn-vulkan",
        "waifu2x": "waifu2x-ncnn-vulkan",
        "realcugan": "realcugan-ncnn-vulkan",
    }.get(engine_id)
    if not executable_base:
        return None
    executable_name = executable_base + (".exe" if os.name == "nt" else "")
    runtime_root = project_root / "runtime" / "engines" / platform_name()
    candidates.append(runtime_root / engine_id)
    if engine_id == "realesrgan":
        candidates.extend([runtime_root, project_root / "artifacts" / "realesrgan"])
    elif engine_id == "waifu2x":
        candidates.append(project_root / "artifacts" / "waifu2x-20250915" / "waifu2x-ncnn-vulkan-20250915-windows")
    elif engine_id == "realcugan":
        candidates.append(project_root / "artifacts" / "realcugan-20220728" / "realcugan-ncnn-vulkan-20220728-windows")

    for directory in candidates:
        executable = directory / executable_name
        models_directory = directory / model_directory
        if executable.is_file() and models_directory.is_dir():
            return EnginePaths(executable.resolve(), models_directory.resolve(), engine_id)
    return None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_model(model: ModelDefinition, models_directory: Path) -> None:
    for asset in model.model_files:
        path = models_directory / asset.name
        if not path.is_file():
            raise EngineError(f"Required model file is missing: {asset.name}")
        if _sha256(path) != asset.sha256:
            raise EngineError(f"Model file checksum does not match: {asset.name}")


def default_output_path(input_path: Path, scale: int, extension: str = ".png") -> Path:
    return input_path.with_name(f"{input_path.stem}_upscaled_{scale}x{extension}")


def inference_scale_for(model: ModelDefinition, requested_scale: int) -> int:
    """Accept only a scale natively declared by the exact model."""
    if requested_scale not in VALID_SCALES:
        raise ValueError(f"Scale must be one of {VALID_SCALES}")
    if requested_scale in model.native_scales:
        return requested_scale
    native = ", ".join(f"{scale}x" for scale in model.native_scales)
    raise EngineError(f"{model.display_name} does not have a native {requested_scale}x asset (native: {native})")


def build_image_command(
    paths: EnginePaths,
    model: ModelDefinition,
    input_path: Path,
    output_path: Path,
    scale: int,
    *,
    gpu_id: int = 0,
    tile_size: int = 0,
    noise_level: int | None = None,
    tta: bool = False,
) -> list[str]:
    inference_scale = inference_scale_for(model, scale)
    if tile_size != 0 and tile_size < 32:
        raise ValueError("Tile size must be zero (automatic) or at least 32")
    if paths.engine_id != model.engine_id:
        raise EngineError(f"Model {model.id} requires the {model.engine_id} engine")
    command = [
        str(paths.executable),
        "-i",
        str(input_path),
        "-o",
        str(output_path),
        "-s",
        str(inference_scale),
        "-t",
        str(tile_size),
        "-m",
        str(paths.models_directory),
    ]
    if model.engine_id == "realesrgan":
        command += ["-n", model.engine_name]
    else:
        options = model.noise_options_for(scale)
        selected_noise = options[0].value if noise_level is None and options else noise_level
        if selected_noise is None or all(option.value != selected_noise for option in options):
            raise EngineError(f"Selected noise level is not supported by {model.display_name} at {scale}x")
        command += ["-n", str(selected_noise)]
        if model.engine_id == "realcugan":
            command += ["-c", "3"]
    output_format = output_path.suffix.lstrip(".").lower() or "png"
    command += ["-g", str(gpu_id), "-f", output_format]
    if tta:
        if not model.supports_tta:
            raise EngineError(f"{model.display_name} does not support TTA")
        command.append("-x")
    return command


def run_image_upscale(
    paths: EnginePaths,
    model: ModelDefinition,
    input_path: Path,
    output_path: Path,
    scale: int,
    progress: Callable[[int], None] | None = None,
    ffmpeg_path: str | Path | None = None,
    cancelled: Callable[[], bool] | None = None,
    noise_level: int | None = None,
    tta: bool = False,
) -> None:
    verify_model(model, paths.models_directory)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        raise EngineError(f"Output already exists: {output_path}")
    temporary = output_path.with_name(output_path.stem + ".partial" + output_path.suffix)
    temporary.unlink(missing_ok=True)
    command = build_image_command(
        paths, model, input_path, temporary, scale,
        noise_level=noise_level, tta=tta,
    )

    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    output_lines: list[str] = []
    assert process.stdout is not None
    for line in process.stdout:
        if cancelled and cancelled():
            process.terminate()
            process.wait(timeout=5)
            temporary.unlink(missing_ok=True)
            raise ProcessingCancelled("Processing was cancelled")
        output_lines.append(line.rstrip())
        match = re.search(r"(\d+(?:\.\d+)?)%", line)
        if match and progress:
            progress(min(100, round(float(match.group(1)))))
    return_code = process.wait()

    if return_code != 0 or not temporary.is_file():
        temporary.unlink(missing_ok=True)
        details = "\n".join(output_lines[-10:])
        raise EngineError(f"Upscaling failed with exit code {return_code}.\n{details}".strip())
    temporary.replace(output_path)
    if progress:
        progress(100)


def run_directory_upscale(
    paths: EnginePaths,
    model: ModelDefinition,
    input_directory: Path,
    output_directory: Path,
    scale: int,
    progress: Callable[[int], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
    noise_level: int | None = None,
    tta: bool = False,
) -> None:
    """Upscale every supported image in a directory for the video pipeline."""
    verify_model(model, paths.models_directory)
    output_directory.mkdir(parents=True, exist_ok=False)
    command = build_image_command(
        paths, model, input_directory, output_directory, scale,
        noise_level=noise_level, tta=tta,
    )
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    output_queue: queue.Queue[str | None] = queue.Queue()

    def consume_output() -> None:
        assert process.stdout is not None
        try:
            for line in process.stdout:
                output_queue.put(line.rstrip())
        finally:
            output_queue.put(None)

    reader = threading.Thread(target=consume_output, name="ncnn-output-reader", daemon=True)
    reader.start()
    output_lines: list[str] = []
    input_count = sum(1 for _ in input_directory.glob("*.png"))
    last_output_count = -1
    while process.poll() is None:
        while True:
            try:
                line = output_queue.get_nowait()
            except queue.Empty:
                break
            if line is not None:
                output_lines.append(line)
                if len(output_lines) > 50:
                    del output_lines[:-50]
        if progress and input_count:
            output_count = sum(1 for _ in output_directory.glob("*.png"))
            if output_count != last_output_count:
                progress(min(99, round(output_count / input_count * 100)))
                last_output_count = output_count
        if cancelled and cancelled():
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            raise ProcessingCancelled("Processing was cancelled")
        time.sleep(0.1)
    reader.join(timeout=2)
    while True:
        try:
            line = output_queue.get_nowait()
        except queue.Empty:
            break
        if line is not None:
            output_lines.append(line)
    if process.returncode != 0:
        raise EngineError(
            f"Frame upscaling failed with exit code {process.returncode}.\n"
            + "\n".join(output_lines[-10:])
        )
    if not any(output_directory.glob("*.png")):
        raise EngineError("Frame upscaling produced no output images")
    if progress:
        progress(100)
