"""Audio mux command and output verification."""

from __future__ import annotations

from pathlib import Path

from reforge_pixels.audio import AudioAction, audio_blocking_reasons
from reforge_pixels.media import MediaInfo


class VideoProcessingError(RuntimeError):
    pass


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
        "-protocol_whitelist", "file,pipe", "-i", str(joined_video.resolve()),
        "-protocol_whitelist", "file,pipe", "-i", str(source_media.path.resolve()),
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
        if action.kind == "transcode" and action.expected_sample_rate is not None:
            command += [f"-ar:a:{output_index}", str(action.expected_sample_rate)]

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
        if action.expected_sample_rate is not None and actual.sample_rate != action.expected_sample_rate:
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
