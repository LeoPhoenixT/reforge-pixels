from pathlib import Path

import pytest

from reforge_pixels.engine import EngineError, EnginePaths, build_image_command, default_output_path, inference_scale_for
from reforge_pixels.models import load_models


def _model(model_id: str):
    return next(model for model in load_models() if model.id == model_id)


def test_default_output_path() -> None:
    assert default_output_path(Path("photo.jpg"), 4) == Path("photo_upscaled_4x.png")


def test_realesrgan_command_uses_structured_arguments() -> None:
    model = _model("general-quality-4x")
    paths = EnginePaths(Path("engine.exe"), Path("model folder"), "realesrgan")
    command = build_image_command(paths, model, Path("input file.jpg"), Path("output file.png"), 4)
    assert command[0] == "engine.exe"
    assert command[command.index("-i") + 1] == "input file.jpg"
    assert command[command.index("-s") + 1] == "4"
    assert command[command.index("-n") + 1] == model.engine_name


def test_waifu2x_command_uses_noise_and_tta() -> None:
    model = _model("waifu2x-photo")
    paths = EnginePaths(Path("waifu2x.exe"), Path("models"), "waifu2x")
    command = build_image_command(paths, model, Path("in.png"), Path("out.png"), 2, noise_level=2, tta=True)
    assert command[command.index("-n") + 1] == "2"
    assert command[-1] == "-x"


def test_cunet_native_restore_uses_one_x_noise_model() -> None:
    model = _model("waifu2x-cunet")
    paths = EnginePaths(Path("waifu2x.exe"), Path("models"), "waifu2x")
    command = build_image_command(paths, model, Path("in.png"), Path("out.png"), 1, noise_level=1)
    assert command[command.index("-s") + 1] == "1"
    assert command[command.index("-n") + 1] == "1"


def test_realcugan_command_uses_native_scale_noise_and_sync_gap() -> None:
    model = _model("realcugan-se")
    paths = EnginePaths(Path("realcugan.exe"), Path("models"), "realcugan")
    command = build_image_command(paths, model, Path("in.png"), Path("out.png"), 3, noise_level=3)
    assert command[command.index("-s") + 1] == "3"
    assert command[command.index("-n") + 1] == "3"
    assert command[command.index("-c") + 1] == "3"


def test_invalid_tile_size_is_rejected() -> None:
    model = _model("general-quality-4x")
    paths = EnginePaths(Path("engine.exe"), Path("models"), "realesrgan")
    with pytest.raises(ValueError, match="Tile size"):
        build_image_command(paths, model, Path("in.png"), Path("out.png"), 4, tile_size=16)


def test_only_native_model_scales_are_accepted() -> None:
    general = _model("general-quality-4x")
    anime_video = _model("anime-video")
    with pytest.raises(EngineError, match="does not have a native 2x"):
        inference_scale_for(general, 2)
    assert inference_scale_for(anime_video, 2) == 2


def test_invalid_noise_level_is_rejected_for_scale() -> None:
    model = _model("realcugan-se")
    paths = EnginePaths(Path("realcugan.exe"), Path("models"), "realcugan")
    with pytest.raises(EngineError, match="noise level"):
        build_image_command(paths, model, Path("in.png"), Path("out.png"), 3, noise_level=2)


def test_directory_output_defaults_to_png_format() -> None:
    model = _model("waifu2x-photo")
    paths = EnginePaths(Path("waifu2x.exe"), Path("models"), "waifu2x")
    command = build_image_command(paths, model, Path("input_frames"), Path("output_frames"), 2, noise_level=-1)
    assert command[command.index("-f") + 1] == "png"
