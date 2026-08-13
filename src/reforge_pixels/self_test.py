"""Offline packaged-runtime self-test."""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from PIL import Image
from pillow_heif import register_heif_opener

from reforge_pixels.audio import resolve_audio_actions
from reforge_pixels.engine import locate_engine, verify_model
from reforge_pixels.hdr import hdr_filter, verify_sdr_output
from reforge_pixels.image import run_safe_image_upscale
from reforge_pixels.media import inspect_media
from reforge_pixels.models import load_models
from reforge_pixels.paths import find_tool
from reforge_pixels.video import mux_final_output, preflight_audio_actions


def run_self_test(report_path: Path) -> bool:
    report: dict[str, Any] = {"success": False, "checks": {}}
    try:
        ffmpeg = find_tool("ffmpeg")
        ffprobe = find_tool("ffprobe")
        if not ffmpeg or not ffprobe:
            raise RuntimeError("Bundled FFmpeg tools were not found")
        report["checks"]["ffmpeg"] = str(ffmpeg)
        report["checks"]["ffprobe"] = str(ffprobe)

        models = load_models()
        engines: dict[str, str] = {}
        for model in models:
            engine = locate_engine(model)
            if not engine:
                raise RuntimeError(f"Bundled {model.engine_id} engine/model directory was not found for {model.id}")
            verify_model(model, engine.models_directory)
            engines[model.engine_id] = str(engine.executable)
        report["checks"]["engines"] = engines
        report["checks"]["models"] = [model.id for model in models]

        with tempfile.TemporaryDirectory(prefix="reforge-pixels-self-test-") as temporary:
            root = Path(temporary)
            generated_source = root / "source.png"
            source = root / "source.heic"
            output = root / "output.png"
            generated = subprocess.run(
                [
                    str(ffmpeg), "-hide_banner", "-loglevel", "error", "-y",
                    "-f", "lavfi", "-i", "testsrc2=size=32x32:rate=1:duration=1",
                    "-frames:v", "1", str(generated_source),
                ],
                check=False,
                capture_output=True,
                text=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if generated.returncode != 0:
                raise RuntimeError("FFmpeg self-test image generation failed: " + generated.stderr.strip())
            register_heif_opener()
            with Image.open(generated_source) as image:
                image.save(source, format="HEIF", quality=90)
            heic = inspect_media(source, ffprobe)
            if (heic.resolution.width, heic.resolution.height) != (32, 32):
                raise RuntimeError(f"Unexpected HEIC self-test resolution: {heic.resolution.display()}")
            report["checks"]["heic_input"] = heic.resolution.display()
            model = next(item for item in models if item.id == "anime-image-4x")
            engine = locate_engine(model)
            assert engine is not None
            run_safe_image_upscale(engine, model, source, output, 4)
            result = inspect_media(output, ffprobe)
            if (result.resolution.width, result.resolution.height) != (128, 128):
                raise RuntimeError(f"Unexpected self-test resolution: {result.resolution.display()}")
            report["checks"]["gpu_output"] = result.resolution.display()

            native_checks: dict[str, str] = {}
            for model_id, native_scale, noise in (
                ("waifu2x-photo", 2, -1),
                ("realcugan-se", 2, 0),
            ):
                candidate = next(item for item in models if item.id == model_id)
                candidate_engine = locate_engine(candidate)
                assert candidate_engine is not None
                candidate_output = root / f"{model_id}.png"
                run_safe_image_upscale(
                    candidate_engine, candidate, source, candidate_output,
                    native_scale, noise_level=noise,
                )
                candidate_result = inspect_media(candidate_output, ffprobe)
                expected = 32 * native_scale
                if (candidate_result.resolution.width, candidate_result.resolution.height) != (expected, expected):
                    raise RuntimeError(
                        f"Unexpected {model_id} self-test resolution: {candidate_result.resolution.display()}"
                    )
                native_checks[model_id] = candidate_result.resolution.display()
            report["checks"]["native_engine_outputs"] = native_checks

            audio_source = root / "audio-source.mkv"
            joined_video = root / "joined-video.mkv"
            generated_audio = subprocess.run(
                [
                    str(ffmpeg), "-hide_banner", "-loglevel", "error", "-y",
                    "-f", "lavfi", "-i", "testsrc2=size=32x32:rate=10:duration=1",
                    "-f", "lavfi", "-i", "sine=frequency=880:sample_rate=48000:duration=1",
                    "-map", "0:v:0", "-map", "1:a:0", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-c:a", "libopus", "-metadata:s:a:0", "language=eng",
                    "-metadata:s:a:0", "title=Self-test audio", str(audio_source),
                ],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if generated_audio.returncode != 0:
                raise RuntimeError("FFmpeg Opus self-test generation failed: " + generated_audio.stderr.strip())
            extracted_video = subprocess.run(
                [
                    str(ffmpeg), "-hide_banner", "-loglevel", "error", "-y", "-i", str(audio_source),
                    "-map", "0:v:0", "-c:v", "copy", "-an", str(joined_video),
                ],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if extracted_video.returncode != 0:
                raise RuntimeError("FFmpeg audio self-test video extraction failed: " + extracted_video.stderr.strip())

            audio_media = inspect_media(audio_source, ffprobe)
            audio_outputs: dict[str, str] = {}
            for suffix, expected_codec in ((".mkv", "opus"), (".mp4", "aac")):
                actions = resolve_audio_actions(audio_media, suffix, "automatic")
                preflight_audio_actions(ffmpeg, audio_media, suffix, actions, root)
                audio_output = root / f"audio-output{suffix}"
                mux_final_output(ffmpeg, ffprobe, joined_video, audio_media, audio_output, actions)
                audio_result = inspect_media(audio_output, ffprobe)
                if audio_result.audio_codecs != (expected_codec,):
                    raise RuntimeError(
                        f"Unexpected {suffix} self-test audio codec: {audio_result.audio_codecs}"
                    )
                audio_outputs[suffix] = expected_codec
            report["checks"]["audio_outputs"] = audio_outputs

            hdr_source = root / "hdr-source.mkv"
            hdr_output = root / "hdr-output.mp4"
            generated_hdr = subprocess.run(
                [
                    str(ffmpeg), "-hide_banner", "-loglevel", "error", "-y",
                    "-f", "lavfi", "-i", "testsrc2=size=32x32:rate=1:duration=1",
                    "-vf", "setparams=color_primaries=bt2020:color_trc=arib-std-b67:colorspace=bt2020nc:range=limited,format=yuv420p10le",
                    "-c:v", "ffv1", "-level", "3",
                    str(hdr_source),
                ],
                check=False, capture_output=True, text=True, encoding="utf-8", errors="replace",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if generated_hdr.returncode != 0:
                raise RuntimeError("FFmpeg HLG self-test generation failed: " + generated_hdr.stderr.strip())
            hdr_media = inspect_media(hdr_source, ffprobe)
            conversion_filter = hdr_filter(hdr_media, "convert-sdr")
            if hdr_media.hdr_kind != "hlg" or not conversion_filter:
                raise RuntimeError(f"Unexpected HDR self-test classification: {hdr_media.hdr_kind}")
            converted_hdr = subprocess.run(
                [
                    str(ffmpeg), "-hide_banner", "-loglevel", "error", "-y", "-i", str(hdr_source),
                    "-map", "0:v:0", "-vf", conversion_filter, "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
                    "-color_range", "tv", "-an", str(hdr_output),
                ],
                check=False, capture_output=True, text=True, encoding="utf-8", errors="replace",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if converted_hdr.returncode != 0:
                raise RuntimeError("FFmpeg HDR-to-SDR self-test failed: " + converted_hdr.stderr.strip())
            verify_sdr_output(inspect_media(hdr_output, ffprobe))
            report["checks"]["hdr_output"] = "HLG → 8-bit BT.709 SDR"

        report["success"] = True
    except Exception as error:
        report["error"] = f"{type(error).__name__}: {error}"

    report_path = report_path.resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return bool(report["success"])
