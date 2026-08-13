"""Output-aware HDR detection, conversion policy, and SDR validation."""

from __future__ import annotations

import re
from typing import Literal

from reforge_pixels.media import MediaInfo


HdrMode = Literal["convert-sdr", "block"]

# The NCNN models consume 8-bit PNG frames, so HDR is normalized to linear light,
# tone-mapped, gamut-mapped, dithered, and materialized as BT.709 RGB before AI.
HDR_TO_SDR_FILTER = (
    "zscale=t=linear:npl=100,format=gbrpf32le,"
    "tonemap=mobius:param=0.3:desat=2,"
    "zscale=p=bt709:t=bt709:m=bt709:r=tv:d=error_diffusion,format=rgb24"
)
HIGH_BIT_SDR_FILTER = "zscale=p=bt709:t=bt709:m=bt709:r=tv:d=error_diffusion,format=rgb24"


def hdr_label(media: MediaInfo) -> str:
    labels = {
        "none": "SDR",
        "pq": "HDR10 / PQ",
        "hlg": "HLG",
        "high-bit-depth": "High-bit-depth video",
        "dolby-vision": "Dolby Vision",
    }
    return labels[media.hdr_kind]


def hdr_blocking_reasons(media: MediaInfo, mode: HdrMode) -> tuple[str, ...]:
    if media.media_type != "video" or not media.is_hdr:
        return ()
    if mode == "block":
        return (f"{hdr_label(media)} input is blocked by the selected HDR handling mode",)
    if media.hdr_kind == "dolby-vision" and not media.dolby_vision_base_layer:
        return ("Dolby Vision input has no decodable base layer for HDR-to-SDR conversion",)
    return ()


def hdr_filter(media: MediaInfo, mode: HdrMode) -> str | None:
    if media.media_type != "video" or not media.is_hdr or mode != "convert-sdr":
        return None
    if media.hdr_kind == "high-bit-depth" and media.color_transfer not in {"smpte2084", "arib-std-b67"}:
        return HIGH_BIT_SDR_FILTER
    return HDR_TO_SDR_FILTER


def is_high_bit_pixel_format(pixel_format: str | None) -> bool:
    return bool(re.search(r"p(?:10|12|14|16)(?:le|be)?$", str(pixel_format or "").lower()))


def verify_sdr_output(output: MediaInfo) -> None:
    failures: list[str] = []
    if output.is_hdr or output.hdr_kind != "none":
        failures.append("output is still marked as HDR")
    if is_high_bit_pixel_format(output.pixel_format):
        failures.append(f"output pixel format is high bit depth ({output.pixel_format})")
    if output.color_primaries != "bt709":
        failures.append(f"color primaries are {output.color_primaries or 'missing'}, not bt709")
    if output.color_transfer != "bt709":
        failures.append(f"color transfer is {output.color_transfer or 'missing'}, not bt709")
    if output.color_space != "bt709":
        failures.append(f"color matrix is {output.color_space or 'missing'}, not bt709")
    if output.color_range not in {"tv", "limited"}:
        failures.append(f"color range is {output.color_range or 'missing'}, not limited/tv")
    stale = tuple(
        item for item in output.hdr_side_data
        if item.lower() in {
            "dovi configuration record", "mastering display metadata", "content light level metadata",
        }
    )
    if stale:
        failures.append("stale HDR side data remains: " + ", ".join(stale))
    if failures:
        raise ValueError("HDR-to-SDR output verification failed: " + "; ".join(failures))
