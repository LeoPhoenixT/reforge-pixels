"""Exercise every video-capable model through the chunked pipeline with audio."""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path

from reforge_pixels.engine import locate_engine
from reforge_pixels.media import inspect_media
from reforge_pixels.models import compatible_models, load_models
from reforge_pixels.paths import find_tool
from reforge_pixels.video import process_cfr_video


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    ffmpeg = find_tool("ffmpeg")
    ffprobe = find_tool("ffprobe")
    if not ffmpeg or not ffprobe:
        raise RuntimeError("FFmpeg tools were not found")
    source = args.output / "source-320x180-12frames.mp4"
    generated = subprocess.run([
        str(ffmpeg), "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=30:duration=0.4",
        "-f", "lavfi", "-i", "sine=frequency=1000:sample_rate=48000:duration=0.4",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(source),
    ], check=False, capture_output=True, text=True)
    if generated.returncode:
        raise RuntimeError(generated.stderr)
    media = inspect_media(source, ffprobe)
    results: list[dict[str, object]] = []
    for model in compatible_models(load_models(), "video"):
        scale = min(model.native_scales)
        noise_options = model.noise_options_for(scale)
        noise = noise_options[0].value if noise_options else None
        destination = args.output / f"{model.id}-{scale}x.mp4"
        paths = locate_engine(model)
        if paths is None:
            raise RuntimeError(f"Missing engine for {model.id}")
        started = time.perf_counter()
        status = "passed"
        error = None
        try:
            process_cfr_video(media, paths, model, scale, destination, ffmpeg_path=ffmpeg, chunk_frames=6, noise_level=noise)
            inspected = inspect_media(destination, ffprobe)
            dimensions = [inspected.resolution.width, inspected.resolution.height]
            audio_streams = inspected.audio_streams
            frame_rate = inspected.frame_rate
            duration = inspected.duration_seconds
        except Exception as exception:
            status = "failed"
            error = f"{type(exception).__name__}: {exception}"
            dimensions = audio_streams = frame_rate = duration = None
        elapsed = time.perf_counter() - started
        results.append({
            "model_id": model.id, "label": model.display_name, "scale": scale, "noise": noise,
            "status": status, "seconds": round(elapsed, 3), "dimensions": dimensions,
            "audio_streams": audio_streams, "frame_rate": frame_rate, "duration_seconds": duration,
            "output": destination.name if destination.exists() else None, "error": error,
        })
        print(f"{model.id} {scale}x: {status} {elapsed:.3f}s", flush=True)
    payload = {"source": source.name, "source_audio_streams": media.audio_streams, "results": results}
    (args.output / "benchmark.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return 1 if any(item["status"] != "passed" or item["audio_streams"] != 1 for item in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
