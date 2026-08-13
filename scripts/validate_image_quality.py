"""Create forced-tiling, seam, dimension, and cancellation evidence for Checkpoint 3."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageOps, ImageStat
from pillow_heif import register_heif_opener

from reforge_pixels.engine import ProcessingCancelled, locate_engine
from reforge_pixels.image import run_safe_image_upscale
from reforge_pixels.models import load_models


def crop(source: Path, destination: Path, size: int = 256) -> None:
    register_heif_opener()
    with Image.open(source) as opened:
        image = ImageOps.exif_transpose(opened).convert("RGB")
        edge = min(image.size)
        left = (image.width - edge) // 2
        top = (image.height - edge) // 2
        image.crop((left, top, left + edge, top + edge)).resize((size, size), Image.Resampling.LANCZOS).save(destination)


def sheet(items: list[tuple[str, Path]], destination: Path) -> None:
    canvas = Image.new("RGB", (320 * len(items), 350), "#11151b")
    draw = ImageDraw.Draw(canvas)
    for index, (label, path) in enumerate(items):
        with Image.open(path) as opened:
            preview = ImageOps.contain(opened.convert("RGB"), (300, 300), Image.Resampling.LANCZOS)
        canvas.paste(preview, (index * 320 + 10, 10))
        draw.text((index * 320 + 10, 318), label, fill="white")
    canvas.save(destination, quality=94)


def validate_case(source: Path, model_id: str, scale: int, noise: int | None, root: Path) -> dict[str, object]:
    models = load_models()
    model = next(item for item in models if item.id == model_id)
    engine = locate_engine(model)
    if engine is None:
        raise RuntimeError(f"Missing engine for {model_id}")
    prepared = root / f"{model_id}-source.png"
    reference = root / f"{model_id}-single-tile.png"
    forced = root / f"{model_id}-forced-tiles.png"
    difference = root / f"{model_id}-difference.png"
    crop(source, prepared)
    run_safe_image_upscale(engine, model, prepared, reference, scale, noise_level=noise, tile_size=2048)
    run_safe_image_upscale(engine, model, prepared, forced, scale, noise_level=noise, tile_size=96, overlap=24)
    with Image.open(reference) as expected, Image.open(forced) as actual:
        diff = ImageChops.difference(expected.convert("RGB"), actual.convert("RGB"))
        stats = ImageStat.Stat(diff)
        mean_absolute_error = sum(stats.mean) / len(stats.mean)
        extrema = diff.getextrema()
        max_error = max(channel[1] for channel in extrema)
        diff.point(lambda value: min(255, value * 6)).save(difference)
        dimensions = list(actual.size)
    cancelled_output = root / f"{model_id}-cancelled.png"
    cancelled = False
    try:
        run_safe_image_upscale(
            engine, model, prepared, cancelled_output, scale,
            cancelled=lambda: True, noise_level=noise, tile_size=96, overlap=24,
        )
    except ProcessingCancelled:
        cancelled = True
    partial = cancelled_output.with_name(cancelled_output.stem + ".partial" + cancelled_output.suffix)
    cleanup_passed = cancelled and not cancelled_output.exists() and not partial.exists()
    sheet([
        ("Source", prepared), ("Single tile", reference),
        ("Forced 3x3 tiles", forced), ("Difference x6", difference),
    ], root / f"{model_id}-tiling-comparison.jpg")
    return {
        "model_id": model_id, "scale": scale, "noise": noise, "dimensions": dimensions,
        "mean_absolute_channel_error": round(mean_absolute_error, 4),
        "maximum_channel_error": max_error, "cancellation_cleanup_passed": cleanup_passed,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("photo", type=Path)
    parser.add_argument("anime", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    results = [
        validate_case(args.photo, "waifu2x-photo", 2, -1, args.output),
        validate_case(args.anime, "realcugan-pro", 2, 0, args.output),
    ]
    (args.output / "report.json").write_text(json.dumps({"results": results}, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
