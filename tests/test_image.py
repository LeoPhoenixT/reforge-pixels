from pathlib import Path

import pytest
from PIL import Image

from reforge_pixels.engine import EngineError, EnginePaths, ProcessingCancelled
from reforge_pixels.image import run_safe_image_upscale, tile_boxes, validate_output_size, validate_recipe_size
from reforge_pixels.models import ModelDefinition, ModelFile, ScaleRecipe


def test_output_size_accepts_supplied_heic_at_two_x() -> None:
    assert validate_output_size(4284, 5712, 2) == (8568, 11424)


def test_output_size_blocks_supplied_heic_at_three_x() -> None:
    with pytest.raises(EngineError, match="maximum dimension"):
        validate_output_size(4284, 5712, 3)


def test_downscale_recipe_checks_larger_ai_intermediate() -> None:
    recipe = ScaleRecipe(final_scale=2, inference_scale=4, passes=1, mode="downscale")
    with pytest.raises(EngineError, match="maximum dimension"):
        validate_recipe_size(4200, 2000, recipe)


def test_tiles_cover_source_core_exactly() -> None:
    boxes = list(tile_boxes(2050, 1030, tile_size=1024, overlap=16))
    assert len(boxes) == 6
    assert boxes[0] == ((0, 0, 1040, 1030), (0, 0, 1024, 1024))
    assert boxes[-1] == ((2032, 1008, 2050, 1030), (2048, 1024, 2050, 1030))


def _fixture_model() -> ModelDefinition:
    return ModelDefinition(
        id="fixture", display_name="Fixture", engine_name="fixture", media_types=("image",),
        description="fixture", native_scales=(2,), model_files=(ModelFile("model.bin", "0" * 64),),
        status="validated", scale_recipes=(ScaleRecipe(2, 2, 1, "native"),),
    )


def test_corrupt_image_fails_before_gpu_work(tmp_path: Path) -> None:
    source = tmp_path / "corrupt.png"
    source.write_bytes(b"not an image")
    with pytest.raises(EngineError, match="Unable to decode input image"):
        run_safe_image_upscale(EnginePaths(tmp_path / "engine", tmp_path), _fixture_model(), source, tmp_path / "out.png", 2)


def test_unicode_path_and_image_formats(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    source = tmp_path / "測試 🖼️ source.png"
    Image.new("RGBA", (8, 6), (20, 40, 60, 128)).save(source)

    def fake_upscale(paths, model, input_path, output_path, scale, **kwargs):
        with Image.open(input_path) as image:
            image.resize((image.width * scale, image.height * scale)).save(output_path)

    monkeypatch.setattr("reforge_pixels.image.run_image_upscale", fake_upscale)
    paths = EnginePaths(tmp_path / "engine", tmp_path)
    model = _fixture_model()
    for suffix, expected_format in ((".png", "PNG"), (".jpg", "JPEG"), (".webp", "WEBP")):
        output = tmp_path / f"結果 🖼️{suffix}"
        run_safe_image_upscale(paths, model, source, output, 2, output_quality=81, webp_lossless=False)
        with Image.open(output) as result:
            assert result.size == (16, 12)
            assert result.format == expected_format


def test_cancelled_image_leaves_no_output_or_partial(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    output = tmp_path / "output.png"
    Image.new("RGB", (8, 8)).save(source)
    with pytest.raises(ProcessingCancelled):
        run_safe_image_upscale(
            EnginePaths(tmp_path / "engine", tmp_path), _fixture_model(), source, output, 2,
            cancelled=lambda: True,
        )
    assert not output.exists()
    assert not (tmp_path / "output.partial.png").exists()
