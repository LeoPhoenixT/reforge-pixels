"""Container-aware audio stream decisions for video output."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from reforge_pixels.media import AudioStreamInfo, MediaInfo


AudioMode = Literal["automatic", "preserve", "aac", "opus", "remove"]
AudioActionKind = Literal["copy", "transcode", "remove", "block"]

SUPPORTED_AUDIO_MODES: tuple[AudioMode, ...] = ("automatic", "preserve", "aac", "opus", "remove")
MP4_COPY_CODECS = frozenset({"aac", "mp3", "ac3", "eac3", "alac"})
MKV_COPY_CODECS = frozenset({
    "aac", "ac3", "alac", "dts", "eac3", "flac", "mp2", "mp3", "opus", "truehd", "vorbis",
})


@dataclass(frozen=True, slots=True)
class AudioAction:
    stream: AudioStreamInfo
    kind: AudioActionKind
    target_codec: str | None
    bitrate_kbps: int | None
    reason: str

    @property
    def blocks_processing(self) -> bool:
        return self.kind == "block"

    @property
    def output_codec(self) -> str | None:
        if self.kind == "copy":
            return self.stream.codec
        if self.kind == "transcode":
            return self.target_codec
        return None

    def display(self) -> str:
        prefix = f"Audio {self.stream.index}: {self.stream.codec.upper()}"
        if self.kind == "copy":
            return f"{prefix} copied"
        if self.kind == "transcode":
            bitrate = f" {self.bitrate_kbps} kbps" if self.bitrate_kbps else ""
            return f"{prefix} → {str(self.target_codec).upper()}{bitrate}"
        if self.kind == "remove":
            return f"{prefix} removed by user selection"
        return f"{prefix} blocked — {self.reason}"


def media_audio_streams(media: MediaInfo) -> tuple[AudioStreamInfo, ...]:
    """Return authoritative details, with a compatibility fallback for older callers/tests."""
    if media.audio_details:
        return media.audio_details
    return tuple(
        AudioStreamInfo(
            index=index + 1,
            codec=codec.lower(),
            channels=None,
            channel_layout=None,
            sample_rate=None,
            bit_rate=None,
            language=None,
            title=None,
            dispositions=(),
            start_time=None,
            duration_seconds=None,
            metadata=(),
        )
        for index, codec in enumerate(media.audio_codecs)
    )


def _container_accepts_copy(container: str, codec: str) -> bool:
    codec = codec.lower()
    if container == ".mp4":
        return codec in MP4_COPY_CODECS
    if container == ".mkv":
        return codec in MKV_COPY_CODECS or codec.startswith("pcm_")
    return False


def resolve_audio_actions(media: MediaInfo, output_suffix: str, mode: AudioMode = "automatic") -> tuple[AudioAction, ...]:
    container = output_suffix.lower()
    if container not in {".mp4", ".mkv"}:
        raise ValueError(f"Audio policy is not defined for output container: {container or '(none)'}")
    if mode not in SUPPORTED_AUDIO_MODES:
        raise ValueError(f"Unsupported audio handling mode: {mode}")

    actions: list[AudioAction] = []
    for stream in media_audio_streams(media):
        compatible = _container_accepts_copy(container, stream.codec)
        if mode == "remove":
            actions.append(AudioAction(stream, "remove", None, None, "Audio removal was explicitly selected"))
        elif mode == "preserve":
            if compatible:
                actions.append(AudioAction(stream, "copy", stream.codec, None, "Codec is compatible with the container"))
            else:
                actions.append(AudioAction(
                    stream, "block", None, None,
                    f"{stream.codec.upper()} cannot be copied safely to {container[1:].upper()}",
                ))
        elif mode == "aac":
            kind: AudioActionKind = "copy" if stream.codec == "aac" else "transcode"
            actions.append(AudioAction(stream, kind, "aac", None if kind == "copy" else 192, "AAC output selected"))
        elif mode == "opus":
            if container != ".mkv":
                actions.append(AudioAction(stream, "block", None, None, "Opus output is currently supported only in MKV"))
            else:
                kind = "copy" if stream.codec == "opus" else "transcode"
                actions.append(AudioAction(stream, kind, "opus", None if kind == "copy" else 160, "Opus output selected"))
        elif compatible:
            actions.append(AudioAction(stream, "copy", stream.codec, None, "Codec is compatible with the container"))
        else:
            actions.append(AudioAction(
                stream, "transcode", "aac", 192,
                f"{stream.codec.upper()} is converted for {container[1:].upper()} compatibility",
            ))
    return tuple(actions)


def audio_blocking_reasons(actions: tuple[AudioAction, ...]) -> tuple[str, ...]:
    return tuple(action.reason for action in actions if action.blocks_processing)
