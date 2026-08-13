"""Offline FFmpeg → native NCNN model → FFmpeg video pipeline."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Callable

from reforge_pixels.audio import AudioAction, AudioMode, audio_blocking_reasons, resolve_audio_actions
from reforge_pixels.engine import EngineError, EnginePaths, ProcessingCancelled, run_directory_upscale
from reforge_pixels.hdr import HdrMode, hdr_blocking_reasons, hdr_filter, verify_sdr_output
from reforge_pixels.media import MediaInfo, MediaInspectionError, inspect_media
from reforge_pixels.models import ModelDefinition, ScaleRecipe
from reforge_pixels.paths import find_tool


class VideoProcessingError(RuntimeError):
    pass


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
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    while process.poll() is None:
        if cancelled and cancelled():
            process.terminate()
            process.wait(timeout=5)
            raise ProcessingCancelled("Processing was cancelled")
        time.sleep(0.1)
    _, stderr = process.communicate()
    if process.returncode != 0:
        detail = "\n".join(stderr.splitlines()[-12:])
        raise VideoProcessingError(f"{stage} failed with exit code {process.returncode}.\n{detail}")


def nvenc_available(ffmpeg_path: str | Path | None = None) -> bool:
    executable = Path(ffmpeg_path) if ffmpeg_path else find_tool("ffmpeg")
    if not executable:
        return False
    try:
        completed = subprocess.run(
            [str(executable), "-hide_banner", "-encoders"],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except OSError:
        return False
    return completed.returncode == 0 and "h264_nvenc" in completed.stdout


def audio_encoder_available(ffmpeg_path: str | Path, encoder: str) -> bool:
    try:
        completed = subprocess.run(
            [str(ffmpeg_path), "-hide_banner", "-encoders"],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except OSError:
        return False
    return completed.returncode == 0 and any(
        line.split()[1:2] == [encoder] for line in completed.stdout.splitlines()
    )


def build_final_mux_command(
    ffmpeg_path: str | Path,
    joined_video: Path,
    source_media: MediaInfo,
    output_path: Path,
    actions: tuple[AudioAction, ...],
) -> list[str]:
    if audio_blocking_reasons(actions):
        raise VideoProcessingError("Audio cannot be processed:\n- " + "\n- ".join(audio_blocking_reasons(actions)))

    included = tuple(action for action in actions if action.kind not in {"remove", "block"})
    command = [
        str(ffmpeg_path), "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(joined_video), "-i", str(source_media.path),
        "-map", "0:v:0",
    ]
    for action in included:
        command += ["-map", f"1:{action.stream.index}"]
    command += ["-map_metadata", "1", "-map_chapters", "1", "-c:v", "copy"]

    for output_index, action in enumerate(included):
        if action.kind == "copy":
            command += [f"-c:a:{output_index}", "copy"]
        elif action.target_codec == "aac":
            command += [f"-c:a:{output_index}", "aac", f"-b:a:{output_index}", f"{action.bitrate_kbps or 192}k"]
        elif action.target_codec == "opus":
            command += [f"-c:a:{output_index}", "libopus", f"-b:a:{output_index}", f"{action.bitrate_kbps or 160}k"]
        else:
            raise VideoProcessingError(f"No encoder is defined for audio target: {action.target_codec}")

        if action.stream.language:
            command += [f"-metadata:s:a:{output_index}", f"language={action.stream.language}"]
        if action.stream.title:
            title_key = "handler_name" if output_path.suffix.lower() == ".mp4" else "title"
            command += [f"-metadata:s:a:{output_index}", f"{title_key}={action.stream.title}"]
        disposition = "+".join(action.stream.dispositions) if action.stream.dispositions else "0"
        command += [f"-disposition:a:{output_index}", disposition]

    if source_media.duration_seconds:
        command += ["-t", f"{source_media.duration_seconds:.12g}"]
    command.append(str(output_path))
    return command


def verify_muxed_audio(source: MediaInfo, output: MediaInfo, actions: tuple[AudioAction, ...]) -> None:
    expected = tuple(action for action in actions if action.kind not in {"remove", "block"})
    if output.audio_streams != len(expected):
        raise VideoProcessingError(
            f"Audio verification failed: expected {len(expected)} stream(s), found {output.audio_streams}"
        )
    if len(output.audio_details) != len(expected):
        raise VideoProcessingError("Audio verification failed: output stream metadata is incomplete")

    for output_index, (action, actual) in enumerate(zip(expected, output.audio_details, strict=True)):
        expected_codec = action.output_codec
        if actual.codec != expected_codec:
            raise VideoProcessingError(
                f"Audio verification failed for stream {output_index + 1}: expected {expected_codec}, found {actual.codec}"
            )
        if action.stream.channels is not None and actual.channels != action.stream.channels:
            raise VideoProcessingError(
                f"Audio verification failed for stream {output_index + 1}: channel count changed"
            )
        if action.stream.channel_layout and actual.channel_layout != action.stream.channel_layout:
            raise VideoProcessingError(
                f"Audio verification failed for stream {output_index + 1}: channel layout changed"
            )
        if action.stream.sample_rate is not None and actual.sample_rate != action.stream.sample_rate:
            raise VideoProcessingError(
                f"Audio verification failed for stream {output_index + 1}: sample rate changed"
            )
        language_changed = actual.language != action.stream.language
        undefined_language_normalized = (
            action.stream.language in {None, "und"} and actual.language in {None, "und"}
        )
        if language_changed and not undefined_language_normalized:
            raise VideoProcessingError(
                f"Audio verification failed for stream {output_index + 1}: language metadata changed"
            )
        if action.stream.title and actual.title != action.stream.title:
            raise VideoProcessingError(
                f"Audio verification failed for stream {output_index + 1}: title metadata changed"
            )
        expected_dispositions = set(action.stream.dispositions)
        actual_dispositions = set(actual.dispositions)
        default_was_inferred = (
            output_index == 0
            and "default" not in expected_dispositions
            and not any("default" in item.stream.dispositions for item in expected)
            and actual_dispositions == expected_dispositions | {"default"}
        )
        if actual_dispositions != expected_dispositions and not default_was_inferred:
            raise VideoProcessingError(
                f"Audio verification failed for stream {output_index + 1}: disposition metadata changed"
            )
        if action.stream.start_time is not None and actual.start_time is not None:
            if abs(action.stream.start_time - actual.start_time) > 0.1:
                raise VideoProcessingError(
                    f"Audio verification failed for stream {output_index + 1}: start timing changed"
                )
        if action.stream.duration_seconds is not None and actual.duration_seconds is not None:
            if abs(action.stream.duration_seconds - actual.duration_seconds) > 0.25:
                raise VideoProcessingError(
                    f"Audio verification failed for stream {output_index + 1}: duration changed"
                )

    if source.duration_seconds and output.duration_seconds:
        tolerance = max(0.25, 2 / source.frame_rate) if source.frame_rate else 0.25
        if abs(source.duration_seconds - output.duration_seconds) > tolerance:
            raise VideoProcessingError(
                "Audio verification failed: output duration differs from the source beyond tolerance"
            )


def mux_final_output(
    ffmpeg_path: str | Path,
    ffprobe_path: str | Path,
    joined_video: Path,
    source_media: MediaInfo,
    output_path: Path,
    actions: tuple[AudioAction, ...],
    cancelled: Callable[[], bool] | None = None,
) -> None:
    required_encoders: set[str] = set()
    for action in actions:
        if action.kind != "transcode":
            continue
        encoder = "aac" if action.target_codec == "aac" else "libopus" if action.target_codec == "opus" else ""
        if not encoder:
            raise VideoProcessingError(f"Required FFmpeg audio encoder is unavailable: {encoder or action.target_codec}")
        required_encoders.add(encoder)
    for encoder in required_encoders:
        if not audio_encoder_available(ffmpeg_path, encoder):
            raise VideoProcessingError(f"Required FFmpeg audio encoder is unavailable: {encoder}")
    command = build_final_mux_command(ffmpeg_path, joined_video, source_media, output_path, actions)
    try:
        _run(command, "Final muxing", cancelled)
    except Exception:
        output_path.unlink(missing_ok=True)
        raise
    try:
        verified = inspect_media(output_path, ffprobe_path)
    except Exception as error:
        output_path.unlink(missing_ok=True)
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

    required_encoders = {
        "aac" if action.target_codec == "aac" else "libopus"
        for action in actions if action.kind == "transcode"
    }
    for encoder in required_encoders:
        if not audio_encoder_available(ffmpeg_path, encoder):
            raise VideoProcessingError(f"Required FFmpeg audio encoder is unavailable: {encoder}")

    muxer = "mp4" if output_suffix.lower() == ".mp4" else "matroska"
    for action_index, action in enumerate(actions):
        if action.kind != "copy":
            continue
        probe_output = probe_directory / f"audio-copy-{action_index}{output_suffix.lower()}"
        try:
            _run([
                str(ffmpeg_path), "-hide_banner", "-loglevel", "error", "-y",
                "-i", str(source_media.path), "-map", f"0:{action.stream.index}",
                "-frames:a", "1", "-c:a", "copy", "-vn", "-sn", "-dn",
                "-map_metadata", "-1", "-f", muxer, str(probe_output),
            ], f"Audio compatibility check for {action.stream.codec.upper()}", cancelled)
        except VideoProcessingError as error:
            raise VideoProcessingError(
                f"{action.stream.codec.upper()} audio cannot be copied to {output_suffix[1:].upper()} by the bundled FFmpeg build.\n{error}"
            ) from error
        finally:
            probe_output.unlink(missing_ok=True)


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
                "-i", str(media.path), "-map", "0:v:0", "-frames:v", "1",
                "-vf", conversion_filter, "-f", "null", "-",
            ], "HDR-to-SDR compatibility check", cancelled)
        except VideoProcessingError as error:
            raise VideoProcessingError(
                "The bundled FFmpeg build could not decode and tone-map this HDR base layer.\n" + str(error)
            ) from error

    selected_recipe = recipe or model.recipe_for(scale)
    if selected_recipe.final_scale != scale:
        raise VideoProcessingError("Scale recipe does not match the requested final scale")
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
                "-i", str(media.path), "-ss", f"{start_seconds:.12g}",
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
                verify_sdr_output(inspect_media(temporary_output, ffprobe_executable))
            except (ValueError, MediaInspectionError, OSError) as error:
                temporary_output.unlink(missing_ok=True)
                raise VideoProcessingError(str(error)) from error
        temporary_output.replace(output_path)
        if progress:
            progress("Complete", 100)
