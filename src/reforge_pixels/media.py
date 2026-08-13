"""Media detection and metadata inspection using ffprobe."""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any, Literal

from reforge_pixels.resolution import Resolution, oriented_resolution
from reforge_pixels.paths import find_tool


STILL_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff", ".heic", ".heif", ".avif"}
HdrKind = Literal["none", "pq", "hlg", "high-bit-depth", "dolby-vision"]


class MediaInspectionError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class AudioStreamInfo:
    index: int
    codec: str
    channels: int | None
    channel_layout: str | None
    sample_rate: int | None
    bit_rate: int | None
    language: str | None
    title: str | None
    dispositions: tuple[str, ...]
    start_time: float | None
    duration_seconds: float | None
    metadata: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class MediaInfo:
    path: Path
    media_type: str
    resolution: Resolution
    raw_width: int
    raw_height: int
    rotation: int
    duration_seconds: float | None
    frame_rate: float | None
    nominal_frame_rate: float | None
    video_codec: str
    pixel_format: str | None
    audio_streams: int
    subtitle_streams: int
    audio_codecs: tuple[str, ...]
    color_transfer: str | None
    color_primaries: str | None
    is_hdr: bool
    unsupported_streams: tuple[str, ...]
    is_variable_frame_rate: bool
    audio_details: tuple[AudioStreamInfo, ...] = ()
    color_space: str | None = None
    color_range: str | None = None
    hdr_kind: HdrKind = "none"
    hdr_side_data: tuple[str, ...] = ()
    dolby_vision_base_layer: bool = False
    frame_count: int | None = None
    discarded_streams: tuple[str, ...] = ()

    @property
    def blocking_reasons(self) -> tuple[str, ...]:
        reasons: list[str] = []
        if self.is_hdr and self.media_type == "image":
            reasons.append("HDR or high-bit-depth still images are not supported yet")
        if self.is_variable_frame_rate:
            reasons.append("Variable-frame-rate video is not supported in this release")
        reasons.extend(self.unsupported_streams)
        return tuple(reasons)


def _parse_fraction(value: str | None) -> float | None:
    if not value or value in ("0/0", "N/A"):
        return None
    try:
        return float(Fraction(value))
    except (ValueError, ZeroDivisionError):
        return None


def _rotation(stream: dict[str, Any]) -> int:
    tags = stream.get("tags") or {}
    if "rotate" in tags:
        try:
            return int(tags["rotate"]) % 360
        except (TypeError, ValueError):
            pass
    for side_data in stream.get("side_data_list") or []:
        if "rotation" in side_data:
            try:
                return int(side_data["rotation"]) % 360
            except (TypeError, ValueError):
                pass
    return 0


def _is_high_bit_depth(pixel_format: str | None) -> bool:
    return bool(re.search(r"p(?:10|12|14|16)(?:le|be)?$", str(pixel_format or "").lower()))


def _hdr_side_data(stream: dict[str, Any]) -> tuple[str, ...]:
    return tuple(
        str(item.get("side_data_type"))
        for item in (stream.get("side_data_list") or [])
        if item.get("side_data_type")
    )


def _dolby_vision_base_layer(stream: dict[str, Any]) -> bool:
    return any(
        str(item.get("side_data_type") or "").lower() == "dovi configuration record"
        and _optional_int(item.get("bl_present_flag")) == 1
        and (_optional_int(item.get("dv_bl_signal_compatibility_id")) or 0) > 0
        for item in (stream.get("side_data_list") or [])
    )


def _hdr_kind(stream: dict[str, Any]) -> HdrKind:
    transfer = str(stream.get("color_transfer") or "").lower()
    primaries = str(stream.get("color_primaries") or "").lower()
    if any(str(item).lower() == "dovi configuration record" for item in _hdr_side_data(stream)):
        return "dolby-vision"
    if transfer == "smpte2084":
        return "pq"
    if transfer == "arib-std-b67":
        return "hlg"
    if primaries == "bt2020" or _is_high_bit_depth(stream.get("pix_fmt")):
        return "high-bit-depth"
    return "none"


def _is_hdr_stream(stream: dict[str, Any]) -> bool:
    return _hdr_kind(stream) != "none"


def _is_variable_frame_rate(stream: dict[str, Any]) -> bool:
    average = _parse_fraction(stream.get("avg_frame_rate"))
    nominal = _parse_fraction(stream.get("r_frame_rate"))
    if not average or not nominal:
        return False
    return abs(average - nominal) / max(average, nominal) > 0.001


def _optional_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _optional_float(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _audio_stream_info(stream: dict[str, Any]) -> AudioStreamInfo:
    tags = {str(key): str(value) for key, value in (stream.get("tags") or {}).items()}
    dispositions = tuple(
        sorted(str(name) for name, enabled in (stream.get("disposition") or {}).items() if enabled)
    )
    return AudioStreamInfo(
        index=_optional_int(stream.get("index")) or 0,
        codec=str(stream.get("codec_name") or "unknown").lower(),
        channels=_optional_int(stream.get("channels")),
        channel_layout=str(stream["channel_layout"]) if stream.get("channel_layout") else None,
        sample_rate=_optional_int(stream.get("sample_rate")),
        bit_rate=_optional_int(stream.get("bit_rate")),
        language=tags.get("language"),
        title=tags.get("title") or tags.get("handler_name"),
        dispositions=dispositions,
        start_time=_optional_float(stream.get("start_time")),
        duration_seconds=_optional_float(stream.get("duration")),
        metadata=tuple(sorted(tags.items())),
    )


def _unsupported_stream_descriptions(streams: list[dict[str, Any]], primary_video: dict[str, Any]) -> tuple[str, ...]:
    unsupported: list[str] = []
    for stream in streams:
        stream_type = str(stream.get("codec_type") or "unknown")
        codec = str(stream.get("codec_name") or stream.get("codec_tag_string") or "unknown")
        if stream is primary_video:
            continue
        if stream_type == "audio":
            continue
        if stream_type == "data" and codec.lower() == "mebx":
            continue
        if stream_type == "subtitle":
            unsupported.append(f"Subtitle stream '{codec}' is not supported yet")
        elif stream_type in {"attachment", "data"}:
            unsupported.append(f"{stream_type.title()} stream '{codec}' is not supported yet")
        elif stream_type == "video":
            unsupported.append(f"Additional video stream '{codec}' is not supported yet")
        else:
            unsupported.append(f"Unknown stream type '{stream_type}' is not supported")
    return tuple(unsupported)


def _discarded_stream_descriptions(
    streams: list[dict[str, Any]], primary_video: dict[str, Any],
) -> tuple[str, ...]:
    mebx_count = sum(
        1 for stream in streams
        if stream is not primary_video
        and str(stream.get("codec_type") or "").lower() == "data"
        and str(stream.get("codec_name") or stream.get("codec_tag_string") or "").lower() == "mebx"
    )
    if not mebx_count:
        return ()
    noun = "stream" if mebx_count == 1 else "streams"
    return (f"{mebx_count} Apple QuickTime metadata {noun} ('mebx') will be removed from output",)


def inspect_media(path: Path, ffprobe_path: str | Path | None = None) -> MediaInfo:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise MediaInspectionError(f"File does not exist: {path}")

    if path.suffix.lower() in STILL_IMAGE_EXTENSIONS:
        try:
            from PIL import Image, ImageOps
            from pillow_heif import open_heif, register_heif_opener

            register_heif_opener()
            bit_depth = 8
            if path.suffix.lower() in {".heic", ".heif", ".avif"}:
                heif = open_heif(path, convert_hdr_to_8bit=False)
                bit_depth = int(heif.info.get("bit_depth", 8))
            with Image.open(path) as opened:
                oriented = ImageOps.exif_transpose(opened)
                width, height = oriented.size
                mode = opened.mode
            return MediaInfo(
                path=path,
                media_type="image",
                resolution=Resolution(width, height),
                raw_width=width,
                raw_height=height,
                rotation=0,
                duration_seconds=None,
                frame_rate=None,
                nominal_frame_rate=None,
                video_codec="heif" if path.suffix.lower() in {".heic", ".heif", ".avif"} else mode.lower(),
                pixel_format=mode,
                audio_streams=0,
                subtitle_streams=0,
                audio_codecs=(),
                color_transfer=None,
                color_primaries=None,
                is_hdr=bit_depth > 8,
                unsupported_streams=(),
                is_variable_frame_rate=False,
                audio_details=(),
                hdr_kind="high-bit-depth" if bit_depth > 8 else "none",
            )
        except Exception as error:
            raise MediaInspectionError(f"Unable to inspect image: {error}") from error

    executable = str(ffprobe_path) if ffprobe_path else find_tool("ffprobe")
    if not executable:
        raise MediaInspectionError("ffprobe was not found")

    command = [
        str(executable),
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except OSError as error:
        raise MediaInspectionError(f"Could not start ffprobe: {error}") from error

    if completed.returncode != 0:
        detail = completed.stderr.strip() or "unknown ffprobe error"
        raise MediaInspectionError(f"Unable to inspect media: {detail}")

    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise MediaInspectionError("ffprobe returned invalid metadata") from error

    streams = payload.get("streams") or []
    video_stream = next((stream for stream in streams if stream.get("codec_type") == "video"), None)
    if not video_stream:
        raise MediaInspectionError("No image or video stream was found")

    try:
        width = int(video_stream["width"])
        height = int(video_stream["height"])
    except (KeyError, TypeError, ValueError) as error:
        raise MediaInspectionError("Media has no usable dimensions") from error

    format_info = payload.get("format") or {}
    duration = None
    try:
        raw_duration = format_info.get("duration") or video_stream.get("duration")
        duration = float(raw_duration) if raw_duration is not None else None
    except (TypeError, ValueError):
        duration = None

    format_name = str(format_info.get("format_name", ""))
    number_of_frames = video_stream.get("nb_frames")
    is_still_format = any(
        token in format_name.split(",")
        for token in ("image2", "png_pipe", "jpeg_pipe", "webp_pipe", "bmp_pipe", "tiff_pipe")
    )
    media_type = "image" if is_still_format or (duration is None and number_of_frames in (None, "1")) else "video"
    rotation = _rotation(video_stream)
    audio_details = tuple(
        _audio_stream_info(stream) for stream in streams if stream.get("codec_type") == "audio"
    )
    audio_codecs = tuple(stream.codec for stream in audio_details)

    return MediaInfo(
        path=path,
        media_type=media_type,
        resolution=oriented_resolution(width, height, rotation),
        raw_width=width,
        raw_height=height,
        rotation=rotation,
        duration_seconds=duration if media_type == "video" else None,
        frame_rate=_parse_fraction(video_stream.get("avg_frame_rate")) if media_type == "video" else None,
        nominal_frame_rate=_parse_fraction(video_stream.get("r_frame_rate")) if media_type == "video" else None,
        video_codec=str(video_stream.get("codec_name", "unknown")),
        pixel_format=video_stream.get("pix_fmt"),
        audio_streams=len(audio_details),
        subtitle_streams=sum(1 for stream in streams if stream.get("codec_type") == "subtitle"),
        audio_codecs=audio_codecs,
        color_transfer=video_stream.get("color_transfer"),
        color_primaries=video_stream.get("color_primaries"),
        is_hdr=_is_hdr_stream(video_stream),
        unsupported_streams=_unsupported_stream_descriptions(streams, video_stream),
        is_variable_frame_rate=_is_variable_frame_rate(video_stream) if media_type == "video" else False,
        audio_details=audio_details,
        color_space=video_stream.get("color_space"),
        color_range=video_stream.get("color_range"),
        hdr_kind=_hdr_kind(video_stream),
        hdr_side_data=_hdr_side_data(video_stream),
        dolby_vision_base_layer=_dolby_vision_base_layer(video_stream),
        frame_count=_optional_int(video_stream.get("nb_frames")) if media_type == "video" else None,
        discarded_streams=_discarded_stream_descriptions(streams, video_stream),
    )
