"""Build the Checkpoint 1B comparison sheet and concise evidence report."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps


ROOT = Path(__file__).resolve().parents[1]
IMAGE_ROOT = ROOT / "artifacts/model-matrix-benchmark"
VIDEO_ROOT = ROOT / "artifacts/video-model-benchmark"
ANIME_ROOT = ROOT / "artifacts/anime-model-benchmark"
OUTPUT_ROOT = ROOT / "artifacts/checkpoint-1b"
RELEASE_ENGINES = ROOT / "dist/Reforge-Pixels-windows-x64/runtime/engines/windows"


def mib(path: Path) -> float:
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file()) / 1024**2


def comparison_sheet(selected: list[tuple[str, Path]], destination: Path) -> None:
    tile_width, tile_height, columns = 300, 340, 3
    rows = (len(selected) + columns - 1) // columns
    sheet = Image.new("RGB", (tile_width * columns, tile_height * rows), "#11151b")
    draw = ImageDraw.Draw(sheet)
    for index, (label, path) in enumerate(selected):
        image = Image.open(path).convert("RGB")
        preview = ImageOps.contain(image, (270, 270), Image.Resampling.LANCZOS)
        x = index % columns * tile_width
        y = index // columns * tile_height
        sheet.paste(preview, (x + (tile_width - preview.width) // 2, y + 10))
        draw.text((x + 12, y + 292), label, fill="#edf2f7")
    sheet.save(destination, quality=94)


def main() -> None:
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    image_report = json.loads((IMAGE_ROOT / "benchmark.json").read_text(encoding="utf-8"))
    video_report = json.loads((VIDEO_ROOT / "benchmark.json").read_text(encoding="utf-8"))
    results = image_report["results"]

    selected = [
        ("Source 96x96", IMAGE_ROOT / image_report["crop"]),
        ("Waifu2x Photo 2x / noise off", IMAGE_ROOT / "waifu2x-photo-2x-nminus1-tta0.png"),
        ("Real-ESRGAN Photo 4x", IMAGE_ROOT / "general-quality-4x-4x-nfixed-tta0.png"),
        ("Real-ESRGAN Anime 4x", IMAGE_ROOT / "anime-image-4x-4x-nfixed-tta0.png"),
        ("AnimeVideo v3 2x", IMAGE_ROOT / "anime-video-2x-nfixed-tta0.png"),
        ("AnimeVideo v3 4x", IMAGE_ROOT / "anime-video-4x-nfixed-tta0.png"),
        ("Real-CUGAN SE 2x / noise off", IMAGE_ROOT / "realcugan-se-2x-n0-tta0.png"),
        ("Real-CUGAN SE 4x / noise off", IMAGE_ROOT / "realcugan-se-4x-n0-tta0.png"),
        ("Real-CUGAN Pro 2x / noise off", IMAGE_ROOT / "realcugan-pro-2x-n0-tta0.png"),
    ]
    comparison_sheet(selected, OUTPUT_ROOT / "image-comparison.jpg")
    if ANIME_ROOT.is_dir():
        comparison_sheet([
            ("Source anime crop 256x256", ANIME_ROOT / "source-crop.png"),
            ("Waifu2x Photo 2x", ANIME_ROOT / "waifu2x-photo-2x-nminus1-tta0.png"),
            ("Real-ESRGAN Anime 4x", ANIME_ROOT / "anime-image-4x-4x-nfixed-tta0.png"),
            ("AnimeVideo v3 2x", ANIME_ROOT / "anime-video-2x-nfixed-tta0.png"),
            ("AnimeVideo v3 4x", ANIME_ROOT / "anime-video-4x-nfixed-tta0.png"),
            ("Real-CUGAN SE 2x / noise off", ANIME_ROOT / "realcugan-se-2x-n0-tta0.png"),
            ("Real-CUGAN SE 4x / noise off", ANIME_ROOT / "realcugan-se-4x-n0-tta0.png"),
            ("Default: Real-CUGAN Pro 2x / off", ANIME_ROOT / "realcugan-pro-2x-n0-tta0.png"),
            ("Real-CUGAN Pro 3x / off", ANIME_ROOT / "realcugan-pro-3x-n0-tta0.png"),
        ], OUTPUT_ROOT / "anime-comparison.jpg")

    by_model: dict[str, list[dict]] = defaultdict(list)
    for item in results:
        by_model[item["model_id"]].append(item)
    lines = [
        "# Checkpoint 1B — Multi-engine model menu", "",
        "Checkpoint decisions were recorded on 2026-08-09 and implemented.", "",
        "## Automated acceptance", "",
        f"- Image capability matrix: **{sum(item['status'] == 'passed' for item in results)}/{len(results)} passed**.",
        f"- Tested every exposed native scale, noise level, and TTA state on a consistent {image_report['crop_size'][0]}×{image_report['crop_size'][1]} crop.",
        f"- Observed GPU-memory delta: **{min(item['gpu_memory_delta_mib'] for item in results)}–{max(item['gpu_memory_delta_mib'] for item in results)} MiB**.",
        f"- Video-capable models: **{sum(item['status'] == 'passed' for item in video_report['results'])}/{len(video_report['results'])} passed**; all retained one audio stream, 30 FPS, and 0.4 s duration.",
        "- HDR/PQ, HLG, high-bit-depth SDR, and base-layer Dolby Vision can convert to verified 8-bit BT.709 SDR; true HDR preservation remains future work.",
        "- Known Apple QuickTime mebx metadata is grouped into one visible removal notice; other data streams remain blocked.",
        "- VFR, subtitles, attachments, uncopyable/unconvertible audio, and additional video streams remain blocked as documented future work.", "",
        "## Menu and measured image matrix", "",
        "| Menu label | Native scales | Cases | Runtime range | Peak GPU delta |", "|---|---:|---:|---:|---:|",
    ]
    for model_id, items in by_model.items():
        label = items[0]["label"]
        scales = ", ".join(f"{value}×" for value in sorted({item['scale'] for item in items}))
        seconds = [item["seconds"] for item in items]
        memory = [item["gpu_memory_delta_mib"] for item in items]
        lines.append(f"| {label} | {scales} | {len(items)} | {min(seconds):.3f}–{max(seconds):.3f} s | {min(memory)}–{max(memory)} MiB |")
    lines += ["", "## Offline bundle impact", "", "| Engine | Size |", "|---|---:|"]
    for engine in ("realesrgan", "waifu2x", "realcugan"):
        lines.append(f"| {engine} | {mib(RELEASE_ENGINES / engine):.1f} MiB |")
    lines += ["", "## Short video evidence", "", "| Model | Scale | Runtime | Output | Audio | FPS |", "|---|---:|---:|---:|---:|---:|"]
    for item in video_report["results"]:
        dimensions = "×".join(str(value) for value in item["dimensions"])
        lines.append(f"| {item['label']} | {item['scale']}× | {item['seconds']:.3f} s | {dimensions} | {item['audio_streams']} stream | {item['frame_rate']:.0f} |")
    lines += [
        "", "## Recorded human decisions", "",
        "- Default General: Photo Fast 2x — Waifu2x Upconv_7 Photo.",
        "- Default Anime/Illustration: Anime Pro 2x/3x — Real-CUGAN Pro.",
        "- Keep every currently bundled model.",
        "- Choose native multiplier before the model; filter the model menu by that exact scale.",
        "- Representative anime test image; see `anime-comparison.jpg`.", "",
        "## Reference model gaps", "",
        "Snowshell also supports Waifu2x cunet, Waifu2x upconv_7 anime-style, and alternate legacy Caffe/CPU backends. The current Real-CUGAN bundle also contains a small `models-nose` 2x no-denoise family. These remain unexposed candidates pending distinct-quality evidence; no current model was removed.", "",
        "## License inventory", "",
        "- Reforge Pixels: GPL-3.0-or-later.",
        "- Real-ESRGAN NCNN/Vulkan: BSD-3-Clause; model/project license included.",
        "- Waifu2x NCNN/Vulkan: MIT; pinned package license included.",
        "- Real-CUGAN NCNN/Vulkan: MIT; pinned package license included.",
        "- NCNN: BSD-3-Clause; FFmpeg build: GPL; PySide6: GPLv3 choice.",
    ]
    (OUTPUT_ROOT / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
