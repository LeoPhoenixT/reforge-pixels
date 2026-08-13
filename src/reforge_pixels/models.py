"""Load and validate the bundled AI model manifest."""

from __future__ import annotations

import json
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import Literal


MediaType = Literal["image", "video"]
EngineId = Literal["realesrgan", "waifu2x", "realcugan"]
RecipeMode = Literal["native", "downscale", "repeated", "repeated_downscale"]


@dataclass(frozen=True, slots=True)
class ModelFile:
    name: str
    sha256: str


@dataclass(frozen=True, slots=True)
class NoiseOption:
    value: int
    label: str


@dataclass(frozen=True, slots=True)
class ScaleRecipe:
    final_scale: int
    inference_scale: int
    passes: int
    mode: RecipeMode

    @property
    def ai_scale(self) -> int:
        return self.inference_scale ** self.passes

    @property
    def label(self) -> str:
        if self.mode == "native":
            return f"{self.final_scale}x (Native)" if self.final_scale != 1 else "1x Restore (Native)"
        if self.mode == "downscale":
            return f"{self.final_scale}x ({self.ai_scale}x AI → Downscale)"
        if self.mode == "repeated":
            return f"{self.final_scale}x (Repeated {self.inference_scale}x AI)"
        return f"{self.final_scale}x (Repeated {self.inference_scale}x AI → Downscale)"


@dataclass(frozen=True, slots=True)
class ModelDefinition:
    id: str
    display_name: str
    engine_name: str
    media_types: tuple[MediaType, ...]
    description: str
    native_scales: tuple[int, ...]
    model_files: tuple[ModelFile, ...]
    status: str
    engine_id: EngineId = "realesrgan"
    model_directory: str = ""
    recommendation: str = "General"
    noise_levels_by_scale: tuple[tuple[int, tuple[int, ...]], ...] = ()
    noise_options: tuple[NoiseOption, ...] = ()
    supports_tta: bool = False
    speed_class: str = "Standard"
    default_for: tuple[str, ...] = ()
    scale_recipes: tuple[ScaleRecipe, ...] = ()

    @property
    def available(self) -> bool:
        return self.status == "validated"

    def noise_options_for(self, scale: int) -> tuple[NoiseOption, ...]:
        supported = next(
            (levels for native_scale, levels in self.noise_levels_by_scale if native_scale == scale),
            (),
        )
        return tuple(option for option in self.noise_options if option.value in supported)

    def recipe_for(self, final_scale: int) -> ScaleRecipe:
        recipe = next((item for item in self.scale_recipes if item.final_scale == final_scale), None)
        if recipe is None:
            raise ValueError(f"No validated {final_scale}x recipe for {self.id}")
        return recipe


def default_manifest_path() -> Path:
    return Path(str(files("reforge_pixels").joinpath("resources/models.json")))


def load_models(path: Path | None = None) -> tuple[ModelDefinition, ...]:
    manifest_path = path or default_manifest_path()
    with manifest_path.open("r", encoding="utf-8") as stream:
        payload = json.load(stream)

    if payload.get("schema_version") != 3:
        raise ValueError("Unsupported model manifest schema")

    models: list[ModelDefinition] = []
    seen_ids: set[str] = set()
    for raw in payload.get("models", []):
        model_id = raw["id"]
        if model_id in seen_ids:
            raise ValueError(f"Duplicate model id: {model_id}")
        seen_ids.add(model_id)

        media_types = tuple(raw["media_types"])
        if not media_types or any(item not in ("image", "video") for item in media_types):
            raise ValueError(f"Invalid media types for model: {model_id}")

        native_scales = tuple(raw["native_scales"])
        if not native_scales or any(scale not in (1, 2, 3, 4) for scale in native_scales):
            raise ValueError(f"Invalid native scales for model: {model_id}")
        scale_recipes = tuple(
            ScaleRecipe(
                final_scale=int(item["final_scale"]), inference_scale=int(item["inference_scale"]),
                passes=int(item.get("passes", 1)), mode=item["mode"],
            )
            for item in raw.get("scale_recipes", [])
        )
        if not scale_recipes or len({item.final_scale for item in scale_recipes}) != len(scale_recipes):
            raise ValueError(f"Invalid or duplicate scale recipes for model: {model_id}")
        for recipe in scale_recipes:
            if recipe.final_scale not in (1, 2, 3, 4) or recipe.inference_scale not in native_scales or recipe.passes < 1:
                raise ValueError(f"Invalid scale recipe for model: {model_id}")
            if recipe.mode == "native" and (recipe.passes != 1 or recipe.final_scale != recipe.inference_scale):
                raise ValueError(f"Invalid native recipe for model: {model_id}")
            if recipe.mode not in ("native", "downscale", "repeated", "repeated_downscale"):
                raise ValueError(f"Invalid recipe mode for model: {model_id}")
            if recipe.ai_scale < recipe.final_scale:
                raise ValueError(f"Scale recipe cannot upscale to its final size: {model_id}")

        model_files = tuple(
            ModelFile(name=item["name"], sha256=item["sha256"].lower())
            for item in raw["model_files"]
        )
        if not model_files or any(len(item.sha256) != 64 for item in model_files):
            raise ValueError(f"Invalid model file hashes for model: {model_id}")

        engine_id = raw.get("engine_id", "realesrgan")
        if engine_id not in ("realesrgan", "waifu2x", "realcugan"):
            raise ValueError(f"Invalid engine id for model: {model_id}")
        recommendation = raw.get("recommendation", "General")
        if recommendation not in ("General", "Anime"):
            raise ValueError(f"Invalid recommendation for model: {model_id}")
        default_for = tuple(str(item) for item in raw.get("default_for", []))
        if any(item not in ("General", "Anime") for item in default_for):
            raise ValueError(f"Invalid default category for model: {model_id}")
        noise_levels_by_scale = tuple(
            (int(scale), tuple(int(value) for value in levels))
            for scale, levels in raw.get("noise_levels_by_scale", {}).items()
        )
        if any(scale not in native_scales for scale, _ in noise_levels_by_scale):
            raise ValueError(f"Noise capability references a non-native scale: {model_id}")
        noise_options = tuple(
            NoiseOption(value=int(item["value"]), label=str(item["label"]))
            for item in raw.get("noise_options", [])
        )
        declared_noise_values = {option.value for option in noise_options}
        if any(value not in declared_noise_values for _, levels in noise_levels_by_scale for value in levels):
            raise ValueError(f"Noise capability has no display label: {model_id}")

        models.append(
            ModelDefinition(
                id=model_id,
                display_name=raw["display_name"],
                engine_name=raw["engine_name"],
                media_types=media_types,
                description=raw["description"],
                native_scales=native_scales,
                model_files=model_files,
                status=raw["status"],
                engine_id=engine_id,
                model_directory=raw.get("model_directory", ""),
                recommendation=recommendation,
                noise_levels_by_scale=noise_levels_by_scale,
                noise_options=noise_options,
                supports_tta=bool(raw.get("supports_tta", False)),
                speed_class=raw.get("speed_class", "Standard"),
                default_for=default_for,
                scale_recipes=scale_recipes,
            )
        )
    for category in ("General", "Anime"):
        defaults = [model.id for model in models if category in model.default_for]
        if len(defaults) > 1:
            raise ValueError(f"Multiple default models declared for {category}: {', '.join(defaults)}")
    return tuple(models)


def compatible_models(
    models: tuple[ModelDefinition, ...], media_type: MediaType, *, validated_only: bool = True
) -> tuple[ModelDefinition, ...]:
    return tuple(
        model
        for model in models
        if media_type in model.media_types and (model.available or not validated_only)
    )
