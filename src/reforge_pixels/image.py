"""Safe, orientation-aware and bounded-memory image upscaling."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Callable, Iterator

from PIL import Image, ImageOps
from pillow_heif import register_heif_opener

from reforge_pixels.engine import EngineError, EnginePaths, ProcessingCancelled, run_image_upscale
from reforge_pixels.models import ModelDefinition, ScaleRecipe


MAX_OUTPUT_DIMENSION = 16_384
MAX_OUTPUT_PIXELS = 150_000_000
DEFAULT_TILE_SIZE = 2_048
DEFAULT_OVERLAP = 16


def validate_output_size(width: int, height: int, scale: int) -> tuple[int, int]:
    output_width = width * scale
    output_height = height * scale
    if output_width > MAX_OUTPUT_DIMENSION or output_height > MAX_OUTPUT_DIMENSION:
        raise EngineError(
            f"Requested output {output_width:,} × {output_height:,} exceeds the supported maximum dimension of {MAX_OUTPUT_DIMENSION:,} pixels"
        )
    if output_width * output_height > MAX_OUTPUT_PIXELS:
        raise EngineError(
            f"Requested output {output_width:,} × {output_height:,} exceeds the supported {MAX_OUTPUT_PIXELS:,}-pixel safety limit"
        )
    return output_width, output_height


def validate_recipe_size(width: int, height: int, recipe: ScaleRecipe) -> tuple[tuple[int, int], tuple[int, int]]:
    """Validate both the largest AI intermediate and requested final canvas."""
    intermediate = validate_output_size(width, height, recipe.ai_scale)
    final = validate_output_size(width, height, recipe.final_scale)
    return intermediate, final


def tile_boxes(width: int, height: int, tile_size: int = DEFAULT_TILE_SIZE, overlap: int = DEFAULT_OVERLAP) -> Iterator[tuple[tuple[int, int, int, int], tuple[int, int, int, int]]]:
    """Yield (expanded crop, core crop) boxes in source coordinates."""
    for top in range(0, height, tile_size):
        for left in range(0, width, tile_size):
            right = min(width, left + tile_size)
            bottom = min(height, top + tile_size)
            expanded = (
                max(0, left - overlap),
                max(0, top - overlap),
                min(width, right + overlap),
                min(height, bottom + overlap),
            )
            yield expanded, (left, top, right, bottom)


def run_safe_image_upscale(
    paths: EnginePaths,
    model: ModelDefinition,
    input_path: Path,
    output_path: Path,
    scale: int,
    progress: Callable[[int], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
    noise_level: int | None = None,
    tta: bool = False,
    recipe: ScaleRecipe | None = None,
    output_quality: int = 92,
    webp_lossless: bool = True,
    *,
    tile_size: int = DEFAULT_TILE_SIZE,
    overlap: int = DEFAULT_OVERLAP,
) -> None:
    register_heif_opener()
    output_path = output_path.resolve()
    if output_path.exists():
        raise EngineError(f"Output already exists: {output_path}")
    try:
        with Image.open(input_path) as opened:
            icc_profile = opened.info.get("icc_profile")
            source = ImageOps.exif_transpose(opened).convert("RGBA" if opened.has_transparency_data else "RGB")
    except Exception as error:
        raise EngineError(f"Unable to decode input image: {error}") from error

    ai_result: Image.Image | None = None
    result: Image.Image | None = None
    partial = output_path.with_name(output_path.stem + ".partial" + output_path.suffix)

    try:
        selected_recipe = recipe or model.recipe_for(scale)
        if selected_recipe.final_scale != scale:
            raise EngineError("Scale recipe does not match the requested final scale")
        (intermediate_width, intermediate_height), (output_width, output_height) = validate_recipe_size(
            source.width, source.height, selected_recipe,
        )
        boxes = list(tile_boxes(source.width, source.height, tile_size, overlap))
        ai_result = Image.new(source.mode, (intermediate_width, intermediate_height))
        output_path.parent.mkdir(parents=True, exist_ok=True)
        partial.unlink(missing_ok=True)
        with tempfile.TemporaryDirectory(prefix="reforge-pixels-image-") as temporary:
            root = Path(temporary)
            for index, (expanded, core) in enumerate(boxes):
                if cancelled and cancelled():
                    raise ProcessingCancelled("Processing was cancelled")
                tile_input = root / "tile-input.png"
                tile_output = root / "tile-output.png"
                source.crop(expanded).save(tile_input, format="PNG")
                pass_input = tile_input
                for pass_index in range(selected_recipe.passes):
                    tile_output = root / f"tile-output-{pass_index}.png"
                    tile_output.unlink(missing_ok=True)

                    def tile_progress(value: int, current_pass: int = pass_index) -> None:
                        if progress:
                            completed = index + (current_pass + value / 100) / selected_recipe.passes
                            progress(round(completed / len(boxes) * 100))

                    run_image_upscale(
                        paths, model, pass_input, tile_output, selected_recipe.inference_scale,
                        progress=tile_progress, cancelled=cancelled,
                        noise_level=noise_level, tta=tta,
                    )
                    pass_input = tile_output
                with Image.open(tile_output) as enhanced:
                    left_trim = (core[0] - expanded[0]) * selected_recipe.ai_scale
                    top_trim = (core[1] - expanded[1]) * selected_recipe.ai_scale
                    core_width = (core[2] - core[0]) * selected_recipe.ai_scale
                    core_height = (core[3] - core[1]) * selected_recipe.ai_scale
                    core_image = enhanced.crop(
                        (left_trim, top_trim, left_trim + core_width, top_trim + core_height)
                    )
                    ai_result.paste(
                        core_image,
                        (core[0] * selected_recipe.ai_scale, core[1] * selected_recipe.ai_scale),
                    )

        result = ai_result if selected_recipe.ai_scale == selected_recipe.final_scale else ai_result.resize(
            (output_width, output_height), Image.Resampling.LANCZOS,
        )

        save_options: dict[str, object] = {}
        if icc_profile:
            save_options["icc_profile"] = icc_profile
        suffix = output_path.suffix.lower()
        if suffix in {".jpg", ".jpeg"} and result.mode == "RGBA":
            background = Image.new("RGB", result.size, "white")
            background.paste(result, mask=result.getchannel("A"))
            result = background
        if suffix in {".jpg", ".jpeg"}:
            save_options["quality"] = output_quality
            save_options["subsampling"] = 0
        elif suffix == ".webp":
            save_options["lossless"] = webp_lossless
            if not webp_lossless:
                save_options["quality"] = output_quality
        result.save(partial, **save_options)
        partial.replace(output_path)
        if progress:
            progress(100)
    except Exception:
        partial.unlink(missing_ok=True)
        raise
    finally:
        source.close()
        if ai_result is not None:
            ai_result.close()
        if result is not None and result is not ai_result:
            result.close()
