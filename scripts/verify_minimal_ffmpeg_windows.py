"""Verify the pinned, self-built Windows FFmpeg release inputs."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import tempfile
from pathlib import Path


def run(command: list[str]) -> str:
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(f"Command failed ({completed.returncode}): {' '.join(command)}\n{detail}")
    return completed.stdout


def require(text: str, values: tuple[str, ...], label: str) -> None:
    missing = [value for value in values if value not in text]
    if missing:
        raise RuntimeError(f"{label} is missing: {', '.join(missing)}")


def probe(ffprobe: Path, media: Path) -> dict[str, object]:
    return json.loads(run([
        str(ffprobe), "-v", "error", "-show_streams", "-show_format",
        "-of", "json", str(media),
    ]))


def verify_imports(binary: Path, builder_image: str) -> tuple[str, ...]:
    output = run([
        "docker", "run", "--rm", "--entrypoint", "x86_64-w64-mingw32-objdump",
        "--mount", f"type=bind,source={binary.parent},target=/scan,readonly",
        builder_image, "-p", f"/scan/{binary.name}",
    ])
    imports = tuple(sorted(set(re.findall(r"DLL Name:\s+(\S+)", output)), key=str.casefold))
    forbidden = {
        "libgcc_s_seh-1.dll", "libstdc++-6.dll", "libwinpthread-1.dll",
        "libopus-0.dll", "libx264-164.dll", "libzimg-2.dll",
    }
    unexpected = sorted(set(name.casefold() for name in imports) & forbidden)
    if unexpected:
        raise RuntimeError(f"{binary.name} has unbundled runtime imports: {', '.join(unexpected)}")
    return imports


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bin-directory", type=Path, required=True)
    parser.add_argument(
        "--builder-image",
        default="reforge-pixels-ffmpeg-builder:ubuntu24.04-20260801",
    )
    parser.add_argument("--require-nvenc", action="store_true")
    args = parser.parse_args()

    bin_directory = args.bin_directory.resolve()
    ffmpeg = bin_directory / "ffmpeg.exe"
    ffprobe = bin_directory / "ffprobe.exe"
    for binary in (ffmpeg, ffprobe):
        if not binary.is_file():
            raise RuntimeError(f"Required binary is missing: {binary}")

    version = run([str(ffmpeg), "-hide_banner", "-version"])
    require(
        version,
        (
            "ffmpeg version 7.1.1", "--enable-gpl", "--enable-version3",
            "--enable-libx264", "--enable-libopus", "--enable-libzimg",
            "--enable-ffnvcodec", "--enable-nvenc", "--enable-zlib", "--disable-network",
        ),
        "FFmpeg configuration",
    )
    if "--enable-nonfree" in version:
        raise RuntimeError("FFmpeg configuration unexpectedly enables nonfree components")
    require(
        run([str(ffmpeg), "-hide_banner", "-filters"]),
        (" zscale ", " tonemap ", " scale ", " setparams "),
        "FFmpeg filters",
    )
    require(
        run([str(ffmpeg), "-hide_banner", "-encoders"]),
        (" libx264 ", " h264_nvenc ", " aac ", " libopus ", " ffv1 ", " png "),
        "FFmpeg encoders",
    )

    with tempfile.TemporaryDirectory(prefix="reforge-ffmpeg-verify-") as temporary:
        root = Path(temporary)
        png_frame = root / "frame.png"
        run([
            str(ffmpeg), "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "testsrc2=size=32x32:rate=1:duration=1",
            "-frames:v", "1", str(png_frame),
        ])
        if not png_frame.is_file() or png_frame.stat().st_size == 0:
            raise RuntimeError("PNG frame smoke test did not produce an image")

        audio_video = root / "audio-video.mkv"
        run([
            str(ffmpeg), "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "testsrc2=size=96x64:rate=5:duration=1",
            "-f", "lavfi", "-i", "sine=frequency=880:sample_rate=48000:duration=1",
            "-map", "0:v:0", "-map", "1:a:0", "-c:v", "libx264",
            "-pix_fmt", "yuv420p", "-c:a", "libopus", str(audio_video),
        ])
        streams = probe(ffprobe, audio_video)["streams"]
        codecs = [stream["codec_name"] for stream in streams]
        if codecs != ["h264", "opus"]:
            raise RuntimeError(f"Unexpected audio/video smoke-test codecs: {codecs}")

        hdr_source = root / "hdr-source.mkv"
        hdr_output = root / "hdr-output.mp4"
        run([
            str(ffmpeg), "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "testsrc2=size=96x64:rate=5:duration=1",
            "-vf", "setparams=color_primaries=bt2020:color_trc=arib-std-b67:colorspace=bt2020nc:range=limited,format=yuv420p10le",
            "-c:v", "ffv1", "-level", "3", str(hdr_source),
        ])
        hdr_stream = probe(ffprobe, hdr_source)["streams"][0]
        expected_hdr = {
            "pix_fmt": "yuv420p10le", "color_space": "bt2020nc",
            "color_transfer": "arib-std-b67", "color_primaries": "bt2020",
        }
        for field, expected in expected_hdr.items():
            if hdr_stream.get(field) != expected:
                raise RuntimeError(f"HDR fixture {field} is {hdr_stream.get(field)!r}, expected {expected!r}")
        run([
            str(ffmpeg), "-hide_banner", "-loglevel", "error", "-y", "-i", str(hdr_source),
            "-vf", "zscale=t=linear:npl=100,format=gbrpf32le,tonemap=mobius:param=0.3:desat=2,zscale=p=bt709:t=bt709:m=bt709:r=tv:d=error_diffusion,format=yuv420p",
            "-c:v", "libx264", "-colorspace", "bt709", "-color_primaries", "bt709",
            "-color_trc", "bt709", "-color_range", "tv", str(hdr_output),
        ])
        sdr_stream = probe(ffprobe, hdr_output)["streams"][0]
        if sdr_stream.get("pix_fmt") != "yuv420p" or sdr_stream.get("color_transfer") != "bt709":
            raise RuntimeError(f"Unexpected HDR-to-SDR smoke-test output: {sdr_stream}")

        if args.require_nvenc:
            nvenc_output = root / "nvenc.mp4"
            run([
                str(ffmpeg), "-hide_banner", "-loglevel", "error", "-y",
                "-f", "lavfi", "-i", "testsrc2=size=256x256:rate=5:duration=1",
                "-c:v", "h264_nvenc", "-preset", "p4", "-cq", "19",
                "-pix_fmt", "yuv420p", str(nvenc_output),
            ])
            if probe(ffprobe, nvenc_output)["streams"][0].get("codec_name") != "h264":
                raise RuntimeError("NVENC smoke test did not produce H.264")

    imports = {binary.name: verify_imports(binary, args.builder_image) for binary in (ffmpeg, ffprobe)}
    print("Minimal FFmpeg verification passed.")
    for binary, names in imports.items():
        print(f"{binary} imports: {', '.join(names)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
