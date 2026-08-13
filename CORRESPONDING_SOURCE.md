# Portable Release Corresponding Source

The portable Windows archive redistributes GPL and LGPL components. A release is complete only when its binary archive and corresponding-source archive are published together from the same GitHub release.

## Required source bundle

Before building, prepare a directory containing these exact files:

- `qtbase-everywhere-src-6.10.3.tar.xz`
- `pyside-setup-everywhere-src-6.10.3.tar.xz`
- `pillow-12.3.0.tar.gz`
- `pillow_heif-1.1.1.tar.gz`
- `libheif-1.18.1.tar.gz`
- `libde265-1.0.15.tar.gz`
- `x265-Release_3.4.tar.gz`
- `aom-v3.6.1.tar.gz`
- `ffmpeg-7.1.1-minimal-build-corresponding-source.tar.xz`
- `SOURCE_SHA256SUMS.txt`

`SOURCE_SHA256SUMS.txt` must contain a lowercase SHA-256 and two spaces before every filename. It must cover every archive above and no unlisted file.

The FFmpeg source archive is produced by `scripts/build_minimal_ffmpeg_windows.ps1`. It contains FFmpeg 7.1.1, x264 commit `b35605ace3ddf7c1a5d67a2eb553f034aef41d55`, Opus 1.5.2, zimg 3.0.5, zlib 1.3.2, nv-codec-headers 12.2.72.0, the pinned Ubuntu/Docker build recipe, the exact toolchain package inventory, component notices, checksums, and the configure command. The upstream FFmpeg archive alone is not sufficient for the redistributed executable.

Qt for Python, Shiboken, and the bundled Qt libraries are distributed under GPL version 3 for this GPL application. Their exact 6.10.3 source archives must accompany the binary. The pillow-heif wheel's bundled notice identifies its libheif, libde265, x265, and libaom versions; their exact source archives must accompany the binary.

Run `scripts/prepare_corresponding_source.ps1` to download and verify the upstream archives, stage the self-built FFmpeg source archive, and generate `SOURCE_SHA256SUMS.txt`. The build copies this directory into a separate `Reforge-Pixels-windows-x64-corresponding-source.zip`. Do not publish one archive without the other.

This is an engineering release gate, not legal advice.
