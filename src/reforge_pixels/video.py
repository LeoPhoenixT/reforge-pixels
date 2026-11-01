"""Offline FFmpeg → native NCNN model → FFmpeg video pipeline."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Callable

from reforge_pixels.audio import AudioAction, AudioMode, audio_blocking_reasons, resolve_audio_actions
from reforge_pixels.audio_mux import VideoProcessingError, build_final_mux_command, verify_muxed_audio
from reforge_pixels.engine import EngineError, EnginePaths, ProcessingCancelled, model_verification_scope, run_directory_upscale
from reforge_pixels.ffmpeg_encoders import available_encoders, encoder_query_scope
from reforge_pixels.hdr import HdrMode, hdr_blocking_reasons, hdr_filter, verify_sdr_output
from reforge_pixels.image import validate_recipe_size
from reforge_pixels.media import MediaInfo, MediaInspectionError, inspect_media
from reforge_pixels.models import ModelDefinition, ScaleRecipe
from reforge_pixels.paths import find_tool
from reforge_pixels.subprocess_runner import drain_process


ProgressCallback = Callable[[str, int], None]


def reconcile_decoded_frame_count(
    expected: int, decoded: int, start_frame: int, total_frames: int, chunk_index: int,
) -> tuple[int, int, bool]:
    if decoded == expected:
        return expected, total_frames, False
    if decoded < 1 or decoded > expected:
        raise VideoProcessingError(
            f"Decoded frame count mismatch in chunk {chunk_index}: expected {expected}, got {decoded}"
        )
    return decoded, start_frame + decoded, True


def estimate_chunk_temp_bytes(
    media: MediaInfo, model: ModelDefinition, scale: int, chunk_frames: int,
    recipe: ScaleRecipe | None = None,
) -> int:
    """Conservative temporary-space estimate for one decoded/upscaled chunk."""
    selected_recipe = recipe or model.recipe_for(scale)
    source_bytes = media.raw_width * media.raw_height * 4
    pass_bytes = sum(
        source_bytes * (selected_recipe.inference_scale ** pass_index) ** 2
        for pass_index in range(1, selected_recipe.passes + 1)
    )
    return int((source_bytes + pass_bytes) * chunk_frames * 1.25)


def _run(command: list[str], stage: str, cancelled: Callable[[], bool] | None = None) -> None:
    if cancelled and cancelled():
        raise ProcessingCancelled("Processing was cancelled")
    process = subprocess.Popen(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    return_code, stderr, was_cancelled = drain_process(process, cancelled)
    if was_cancelled:
        raise ProcessingCancelled("Processing was cancelled")
    if return_code != 0:
        detail = "\n".join(stderr[-12:])
        raise VideoProcessingError(f"{stage} failed with exit code {return_code}.\n{detail}")


def nvenc_available(ffmpeg_path: str | Path | None = None) -> bool:
    executable = Path(ffmpeg_path) if ffmpeg_path else find_tool("ffmpeg")
    return bool(executable and "h264_nvenc" in available_encoders(executable))


def audio_encoder_available(ffmpeg_path: str | Path, encoder: str) -> bool:
    return encoder in available_encoders(ffmpeg_path)


def _required_audio_encoders(actions: tuple[AudioAction, ...]) -> set[str]:
    required: set[str] = set()
    for action in actions:
        if action.kind != "transcode":
            continue
        encoder = {"aac": "aac", "opus": "libopus"}.get(action.target_codec)
        if not encoder:
            raise VideoProcessingError(f"No encoder is defined for audio target: {action.target_codec}")
        required.add(encoder)
    return required


def _verify_audio_encoders(ffmpeg_path: str | Path, actions: tuple[AudioAction, ...]) -> None:
    available = available_encoders(ffmpeg_path)
    for encoder in _required_audio_encoders(actions):
        if encoder not in available:
            raise VideoProcessingError(f"Required FFmpeg audio encoder is unavailable: {encoder}")


def mux_final_output(
    ffmpeg_path: str | Path,
    ffprobe_path: str | Path,
    joined_video: Path,
    source_media: MediaInfo,
    output_path: Path,
    actions: tuple[AudioAction, ...],
    cancelled: Callable[[], bool] | None = None,
) -> None:
    _verify_audio_encoders(ffmpeg_path, actions)
    command = build_final_mux_command(ffmpeg_path, joined_video, source_media, output_path, actions)
    try:
        _run(command, "Final muxing", cancelled)
    except Exception:
        output_path.unlink(missing_ok=True)
        raise
    try:
        verified = inspect_media(output_path, ffprobe_path, cancelled=cancelled)
    except Exception as error:
        output_path.unlink(missing_ok=True)
        if cancelled and cancelled():
            raise ProcessingCancelled("Processing was cancelled") from error
        raise VideoProcessingError(f"Unable to verify final audio streams: {error}") from error
    try:
        verify_muxed_audio(source_media, verified, actions)
        if verified.unsupported_streams or verified.discarded_streams:
            raise VideoProcessingError(
                "Stream verification failed: unsupported or removable metadata streams remain in the output"
            )
    except VideoProcessingError:
        output_path.unlink(missing_ok=True)
        raise


def preflight_audio_actions(
    ffmpeg_path: str | Path,
    source_media: MediaInfo,
    output_suffix: str,
    actions: tuple[AudioAction, ...],
    probe_directory: Path,
    cancelled: Callable[[], bool] | None = None,
) -> None:
    reasons = audio_blocking_reasons(actions)
    if reasons:
        raise VideoProcessingError("Audio cannot be processed:\n- " + "\n- ".join(reasons))

    _verify_audio_encoders(ffmpeg_path, actions)

    muxer = "mp4" if output_suffix.lower() == ".mp4" else "matroska"
    for action_index, action in enumerate(actions):
        if action.kind != "copy":
            continue
        probe_output = probe_directory / f"audio-copy-{action_index}{output_suffix.lower()}"
        try:
            _run([
                str(ffmpeg_path), "-hide_banner", "-loglevel", "error", "-y",
                "-protocol_whitelist", "file,pipe", "-i", str(source_media.path.resolve()), "-map", f"0:{action.stream.index}",
                "-frames:a", "1", "-c:a", "copy", "-vn", "-sn", "-dn",
                "-map_metadata", "-1", "-f", muxer, str(probe_output),
            ], f"Audio compatibility check for {action.stream.codec.upper()}", cancelled)
        except VideoProcessingError as error:
            raise VideoProcessingError(
                f"{action.stream.codec.upper()} audio cannot be copied to {output_suffix[1:].upper()} by the bundled FFmpeg build.\n{error}"
            ) from error
        finally:
            probe_output.unlink(missing_ok=True)


@encoder_query_scope()
@model_verification_scope()
def process_cfr_video(
    media: MediaInfo,
    paths: EnginePaths,
    model: ModelDefinition,
    scale: int,
    output_path: Path,
    *,
    ffmpeg_path: str | Path | None = None,
    progress: ProgressCallback | None = None,
    cancelled: Callable[[], bool] | None = None,
    chunk_frames: int = 120,
    noise_level: int | None = None,
    tta: bool = False,
    recipe: ScaleRecipe | None = None,
    audio_mode: AudioMode = "automatic",
    hdr_mode: HdrMode = "block",
) -> None:
    """Process constant-frame-rate video in bounded frame chunks."""
    if media.media_type != "video" or not media.frame_rate:
        raise VideoProcessingError("A video with a usable frame rate is required")
    if media.blocking_reasons:
        raise VideoProcessingError("Video cannot be processed:\n- " + "\n- ".join(media.blocking_reasons))
    if hdr_reasons := hdr_blocking_reasons(media, hdr_mode):
        raise VideoProcessingError("HDR video cannot be processed:\n- " + "\n- ".join(hdr_reasons))
    selected_recipe = recipe or model.recipe_for(scale)
    if selected_recipe.final_scale != scale:
        raise VideoProcessingError("Scale recipe does not match the requested final scale")
    try:
        validate_recipe_size(media.resolution.width, media.resolution.height, selected_recipe)
    except EngineError as error:
        raise VideoProcessingError(str(error)) from error
    output_path = output_path.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        raise VideoProcessingError(f"Output already exists: {output_path}")
    ffmpeg_executable = Path(ffmpeg_path) if ffmpeg_path else find_tool("ffmpeg")
    if not ffmpeg_executable or not ffmpeg_executable.is_file():
        raise VideoProcessingError("FFmpeg was not found")
    ffprobe_executable = find_tool("ffprobe")
    if not ffprobe_executable:
        raise VideoProcessingError("ffprobe was not found")
    audio_actions = resolve_audio_actions(media, output_path.suffix, audio_mode)
    if reasons := audio_blocking_reasons(audio_actions):
        raise VideoProcessingError("Audio cannot be processed:\n- " + "\n- ".join(reasons))
    if chunk_frames < 1:
        raise ValueError("chunk_frames must be positive")
    if not media.duration_seconds:
        raise VideoProcessingError("Video duration is required for chunk processing")

    conversion_filter = hdr_filter(media, hdr_mode)
    if conversion_filter:
        try:
            _run([
                str(ffmpeg_executable), "-hide_banner", "-loglevel", "error", "-y",
                "-protocol_whitelist", "file,pipe", "-i", str(media.path.resolve()), "-map", "0:v:0", "-frames:v", "1",
                "-vf", conversion_filter, "-f", "null", "-",
            ], "HDR-to-SDR compatibility check", cancelled)
        except VideoProcessingError as error:
            raise VideoProcessingError(
                "The bundled FFmpeg build could not decode and tone-map this HDR base layer.\n" + str(error)
            ) from error

    total_frames = media.frame_count or max(1, round(media.duration_seconds * media.frame_rate))
    required_space = estimate_chunk_temp_bytes(
        media, model, scale, min(chunk_frames, total_frames), selected_recipe,
    )
    free_space = shutil.disk_usage(output_path.parent).free
    safety_reserve = 256 * 1024 * 1024
    if free_space < required_space + safety_reserve:
        required_gib = (required_space + safety_reserve) / (1024**3)
        free_gib = free_space / (1024**3)
        raise VideoProcessingError(
            f"Not enough temporary disk space: approximately {required_gib:.2f} GiB required, {free_gib:.2f} GiB available"
        )

    with tempfile.TemporaryDirectory(prefix=".reforge-pixels-audio-probe-", dir=output_path.parent) as probe:
        preflight_audio_actions(
            ffmpeg_executable, media, output_path.suffix, audio_actions, Path(probe), cancelled,
        )

    with tempfile.TemporaryDirectory(prefix=".reforge-pixels-", dir=output_path.parent) as temporary:
        root = Path(temporary)
        source_frames = root / "source"
        upscaled_frames = root / "upscaled"
        segments: list[Path] = []
        encoder = "h264_nvenc" if nvenc_available(ffmpeg_executable) else "libx264"
        chunk_count = (total_frames + chunk_frames - 1) // chunk_frames

        def encode_chunk(segment: Path, selected_encoder: str) -> None:
            segment.unlink(missing_ok=True)
            video_options = ["-c:v", selected_encoder]
            video_options += ["-preset", "p4", "-cq", "19"] if selected_encoder == "h264_nvenc" else ["-preset", "medium", "-crf", "18"]
            encoding_filters: list[str] = []
            if selected_recipe.ai_scale != selected_recipe.final_scale:
                encoding_filters.append(
                    f"scale={media.resolution.width * scale}:{media.resolution.height * scale}:flags=lanczos"
                )
            encoding_filters.append(
                "setparams=range=limited:color_primaries=bt709:color_trc=bt709:colorspace=bt709"
            )
            _run([
                str(ffmpeg_executable), "-hide_banner", "-loglevel", "error", "-y",
                "-framerate", f"{media.frame_rate:.12g}",
                "-i", str(upscaled_frames / "frame_%08d.png"),
                "-map", "0:v:0",
                *video_options,
                "-vf", ",".join(encoding_filters),
                "-pix_fmt", "yuv420p", "-colorspace", "bt709", "-color_primaries", "bt709",
                "-color_trc", "bt709", "-color_range", "tv", "-an", str(segment),
            ], "Chunk encoding", cancelled)

        for chunk_index, start_frame in enumerate(range(0, total_frames, chunk_frames), start=1):
            frames_this_chunk = min(chunk_frames, total_frames - start_frame)
            shutil.rmtree(source_frames, ignore_errors=True)
            shutil.rmtree(upscaled_frames, ignore_errors=True)
            source_frames.mkdir()
            start_seconds = start_frame / media.frame_rate
            overall_start = round(start_frame / total_frames * 85)
            if progress:
                progress(f"Chunk {chunk_index}/{chunk_count}: Decoding", overall_start)
            decode_filter = ["-vf", conversion_filter] if conversion_filter else []
            _run([
                str(ffmpeg_executable), "-hide_banner", "-loglevel", "error", "-y",
                "-protocol_whitelist", "file,pipe", "-i", str(media.path.resolve()), "-ss", f"{start_seconds:.12g}",
                "-map", "0:v:0", "-frames:v", str(frames_this_chunk),
                "-fps_mode", "passthrough", *decode_filter, str(source_frames / "frame_%08d.png"),
            ], "Video decoding", cancelled)
            decoded_count = sum(1 for _ in source_frames.glob("*.png"))
            frames_this_chunk, total_frames, reached_eof = reconcile_decoded_frame_count(
                frames_this_chunk, decoded_count, start_frame, total_frames, chunk_index,
            )
            if progress:
                progress(f"Chunk {chunk_index}/{chunk_count}: Upscaling", overall_start)
            def upscale_progress(chunk_percent: int) -> None:
                if progress:
                    completed_frames = start_frame + frames_this_chunk * chunk_percent / 100
                    progress(
                        f"Chunk {chunk_index}/{chunk_count}: Upscaling",
                        round(completed_frames / total_frames * 85),
                    )
            try:
                pass_input = source_frames
                for pass_index in range(selected_recipe.passes):
                    pass_output = root / f"upscaled-pass-{pass_index + 1}"
                    shutil.rmtree(pass_output, ignore_errors=True)

                    def pass_progress(value: int, current_pass: int = pass_index) -> None:
                        upscale_progress(round((current_pass + value / 100) / selected_recipe.passes * 100))

                    run_directory_upscale(
                        paths, model, pass_input, pass_output, selected_recipe.inference_scale,
                        pass_progress, cancelled, noise_level, tta,
                    )
                    if pass_input != source_frames:
                        shutil.rmtree(pass_input, ignore_errors=True)
                    pass_input = pass_output
                upscaled_frames = pass_input
            except ProcessingCancelled:
                raise
            except EngineError as error:
                raise VideoProcessingError(str(error)) from error

            segment = root / f"segment_{chunk_index:06d}.mkv"
            try:
                encode_chunk(segment, encoder)
            except VideoProcessingError:
                if encoder != "h264_nvenc" or chunk_index != 1:
                    raise
                encoder = "libx264"
                encode_chunk(segment, encoder)
            segments.append(segment)
            if progress:
                completed = start_frame + frames_this_chunk
                progress(f"Chunk {chunk_index}/{chunk_count}: Complete", round(completed / total_frames * 85))
            if reached_eof:
                break

        shutil.rmtree(source_frames, ignore_errors=True)
        shutil.rmtree(upscaled_frames, ignore_errors=True)
        concat_file = root / "segments.txt"
        concat_file.write_text("".join(f"file '{segment.name}'\n" for segment in segments), encoding="utf-8")
        joined_video = root / "joined.mkv"
        if progress:
            progress("Joining video chunks", 90)
        _run([
            str(ffmpeg_executable), "-hide_banner", "-loglevel", "error", "-y",
            "-f", "concat", "-safe", "0", "-i", str(concat_file),
            "-c", "copy", str(joined_video),
        ], "Chunk joining", cancelled)

        temporary_output = root / ("result" + output_path.suffix)
        if progress:
            progress("Restoring audio and metadata", 95)
        mux_final_output(
            ffmpeg_executable, ffprobe_executable, joined_video, media,
            temporary_output, audio_actions, cancelled,
        )
        if conversion_filter:
            try:
                verify_sdr_output(inspect_media(temporary_output, ffprobe_executable, cancelled=cancelled))
            except (ValueError, MediaInspectionError, OSError) as error:
                temporary_output.unlink(missing_ok=True)
                if cancelled and cancelled():
                    raise ProcessingCancelled("Processing was cancelled") from error
                raise VideoProcessingError(str(error)) from error
        if cancelled and cancelled():
            raise ProcessingCancelled("Processing was cancelled")
        temporary_output.replace(output_path)
        if progress:
            progress("Complete", 100)
