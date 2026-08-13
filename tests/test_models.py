import json
from pathlib import Path

import pytest

from reforge_pixels.models import ScaleRecipe, compatible_models, load_models


def test_manifest_loads_expected_media_models() -> None:
    models = load_models()
    image_ids = {model.id for model in compatible_models(models, "image", validated_only=False)}
    video_ids = {model.id for model in compatible_models(models, "video", validated_only=False)}
    assert "anime-image-4x" in image_ids and "anime-image-4x" not in video_ids
    assert "anime-video" in video_ids and "anime-video" not in image_ids


def test_all_validated_models_are_exposed_for_compatible_media() -> None:
    assert {model.id for model in compatible_models(load_models(), "image")} == {
        "waifu2x-photo", "waifu2x-cunet", "waifu2x-anime-style", "general-quality-4x",
        "anime-image-4x", "realcugan-se", "realcugan-pro",
    }


def test_scale_specific_noise_capabilities() -> None:
    model = next(model for model in load_models() if model.id == "realcugan-se")
    assert [option.value for option in model.noise_options_for(2)] == [-1, 0, 1, 2, 3]
    assert [option.value for option in model.noise_options_for(3)] == [-1, 0, 3]


def test_human_approved_defaults_are_unique() -> None:
    models = load_models()
    assert [model.id for model in models if "General" in model.default_for] == ["waifu2x-photo"]
    assert [model.id for model in models if "Anime" in model.default_for] == ["realcugan-pro"]


def test_recipe_labels_disclose_native_and_post_resize_processing() -> None:
    assert ScaleRecipe(2, 2, 1, "native").label == "2x (Native)"
    assert ScaleRecipe(2, 4, 1, "downscale").label == "2x (4x AI → Downscale)"
    assert ScaleRecipe(3, 2, 2, "repeated_downscale").label == "3x (Repeated 2x AI → Downscale)"
    assert ScaleRecipe(4, 2, 2, "repeated").label == "4x (Repeated 2x AI)"


def test_duplicate_model_ids_are_rejected(tmp_path: Path) -> None:
    model = {"id":"duplicate","display_name":"Duplicate","engine_name":"duplicate","media_types":["image"],"description":"fixture","native_scales":[4],"scale_recipes":[{"final_scale":4,"inference_scale":4,"passes":1,"mode":"native"}],"model_files":[{"name":"model.bin","sha256":"0" * 64}],"status":"pending-validation"}
    manifest = tmp_path / "models.json"
    manifest.write_text(json.dumps({"schema_version": 3, "models": [model, model]}), encoding="utf-8")
    with pytest.raises(ValueError, match="Duplicate model id"):
        load_models(manifest)
