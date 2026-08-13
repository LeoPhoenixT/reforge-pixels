"""Generate repeatable capability and RTX benchmark evidence for the human model checkpoint."""

from __future__ import annotations

import argparse
import json
import subprocess
import threading
import time
from pathlib import Path

from PIL import Image, ImageOps
from pillow_heif import register_heif_opener

from reforge_pixels.engine import locate_engine, run_image_upscale
from reforge_pixels.models import load_models


def gpu_used_mib() -> int | None:
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            check=False, capture_output=True, text=True, timeout=5,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return sum(int(line.strip()) for line in result.stdout.splitlines() if line.strip()) if result.returncode == 0 else None
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


def prepare_crop(source: Path, destination: Path, size: int) -> None:
    register_heif_opener()
    with Image.open(source) as image:
        prepared = ImageOps.exif_transpose(image).convert("RGB")
        width, height = prepared.size
        edge = min(width, height)
        left = (width - edge) // 2
        top = (height - edge) // 2
        prepared.crop((left, top, left + edge, top + edge)).resize((size, size), Image.Resampling.LANCZOS).save(destination)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--size", type=int, default=96)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    crop = args.output / "source-crop.png"
    prepare_crop(args.input, crop, args.size)

    results: list[dict[str, object]] = []
    for model in load_models():
        paths = locate_engine(model)
        if paths is None:
            raise RuntimeError(f"Missing engine for {model.id}")
        for scale in model.native_scales:
            noise_values: list[int | None] = [option.value for option in model.noise_options_for(scale)] or [None]
            for noise in noise_values:
                for tta in (False, True) if model.supports_tta else (False,):
                    noise_name = "fixed" if noise is None else str(noise).replace("-", "minus")
                    destination = args.output / f"{model.id}-{scale}x-n{noise_name}-tta{int(tta)}.png"
                    baseline = gpu_used_mib()
                    peak = baseline
                    stop = threading.Event()

                    def sample_gpu() -> None:
                        nonlocal peak
                        while not stop.wait(0.05):
                            used = gpu_used_mib()
                            if used is not None and (peak is None or used > peak):
                                peak = used

                    sampler = threading.Thread(target=sample_gpu, daemon=True)
                    sampler.start()
                    started = time.perf_counter()
                    status = "passed"
                    error = None
                    try:
                        run_image_upscale(paths, model, crop, destination, scale, noise_level=noise, tta=tta)
                        with Image.open(destination) as result:
                            dimensions = list(result.size)
                    except Exception as exception:
                        status = "failed"
                        error = f"{type(exception).__name__}: {exception}"
                        dimensions = None
                    elapsed = time.perf_counter() - started
                    stop.set()
                    sampler.join(timeout=2)
                    results.append({
                        "model_id": model.id, "label": model.display_name, "engine": model.engine_id,
                        "scale": scale, "noise": noise, "tta": tta, "status": status,
                        "seconds": round(elapsed, 3), "dimensions": dimensions,
                        "gpu_memory_baseline_mib": baseline, "gpu_memory_peak_mib": peak,
                        "gpu_memory_delta_mib": None if baseline is None or peak is None else peak - baseline,
                        "output": destination.name if destination.exists() else None, "error": error,
                    })
                    print(f"{model.id} {scale}x noise={noise} tta={tta}: {status} {elapsed:.3f}s", flush=True)

    report = {"source": str(args.input.resolve()), "crop": crop.name, "crop_size": [args.size, args.size], "results": results}
    (args.output / "benchmark.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return 1 if any(item["status"] != "passed" for item in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
