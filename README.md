# Reforge Pixels

Reforge Pixels is a portable, offline Windows application for enlarging images and videos with an NVIDIA RTX GPU. It uses bundled NCNN/Vulkan engines and never uploads media or downloads models at runtime.

> This independent project is not affiliated with or endorsed by NVIDIA.

## Features

- Drag and drop or choose an image/video from Windows Explorer.
- Configure input type, content suggestion, model, scale, denoise, TTA, and output format before selecting a file.
- Photo and anime/illustration models from Waifu2x, Real-ESRGAN, and Real-CUGAN.
- Native 1x restoration and 2x/3x/4x recipes with clear `Native`, repeated-AI, or AI-to-downscale labels.
- PNG, JPEG, WebP, MP4, and MKV output.
- HEIC, HEIF, and AVIF decoding with orientation-aware dimension detection.
- Bounded-memory tiled image processing and chunked video processing.
- Audio, frame rate, metadata, and chapters preserved for supported CFR video.
- Container-aware audio handling with visible per-stream actions, Opus preservation in MKV, and automatic Opus-to-AAC conversion for MP4.
- Explicit HDR-to-SDR conversion for PQ/HDR10, HLG, high-bit-depth SDR, and Dolby Vision files with a decodable base layer.
- NVENC video encoding with an automatic CPU fallback.
- Fully offline operation after extracting the release ZIP.

## Requirements

- Windows 10 or Windows 11, 64-bit.
- NVIDIA RTX GPU with a current driver and Vulkan support.
- Sufficient free disk space for decoded and upscaled video-frame chunks.

Python, Qt, FFmpeg, the CUDA toolkit, and AI-model downloads are not required by portable-release users.

## Using the portable release

1. Download and extract `Reforge-Pixels-windows-x64.zip`.
2. Run `Reforge-Pixels.exe` from the extracted folder.
3. Choose Image or Video and configure the model and output settings.
4. Drop a file or select **Choose File**.
5. Confirm the calculated output resolution and select **Upscale**.

Do not run the executable directly from inside the ZIP.

### Video audio handling

- **Automatic** copies audio when compatible with the selected container and converts incompatible MP4 audio to AAC at 192 kbps.
- **Preserve when compatible** blocks the job rather than transcoding an incompatible stream.
- **Convert to AAC** produces AAC audio; an existing AAC stream is copied to avoid unnecessary quality loss.
- **Convert to Opus** produces Opus audio in MKV; Opus output is not exposed for MP4.
- **Remove audio** is the only mode that deliberately omits audio streams.

The ready state shows the resolved action for every audio stream before processing. Final output is accepted only after codec, stream count, channels, metadata, dispositions, timing, and duration checks pass.

### Video HDR handling

- **Convert HDR to SDR (BT.709)** tone-maps HDR before AI processing and produces tagged 8-bit BT.709 output for ordinary SDR displays.
- **Block HDR input** leaves HDR/high-bit-depth input disabled when conversion is not wanted.
- PQ/HDR10, HLG, and high-bit-depth SDR are detected separately. Dolby Vision conversion requires a decodable base layer; Dolby Vision preservation is not supported.

The conversion path is preflighted before GPU processing. The finished file is rejected if it remains high bit depth, lacks complete BT.709 primaries/transfer/matrix/range tags, or retains Dolby Vision, mastering-display, or content-light side data.

Apple QuickTime `mebx` tracks contain device/camera metadata rather than playable audio or video. Reforge Pixels groups them into one visible notice and removes them from the output. Other data streams remain blocked.

## Current limitations

- True HDR10/Dolby Vision preservation is not supported; the exposed HDR path converts to SDR.
- HDR/high-bit-depth still images remain blocked.
- Variable-frame-rate video is detected and blocked.
- Subtitles, attachments, non-`mebx` data streams, additional video streams, and audio that the bundled FFmpeg build can neither copy nor convert are blocked rather than silently discarded.
- Video enhancement is frame-based and can introduce temporal flicker.
- Output factors above 4x are not exposed.
- Very large inputs or intermediate AI dimensions are blocked by safety limits.
- Some VLC hardware-decoding configurations can display 2160x3840 portrait H.264 incorrectly; Windows Media Player has been verified to display the same output correctly.
- Linux packaging is deferred to future development.

## Bundled model families

- Waifu2x Upconv_7 Photo, Cunet, and Upconv_7 Anime Style
- Real-ESRGAN x4plus, x4plus Anime, and AnimeVideo-v3
- Real-CUGAN SE and Pro

General and Anime/Illustration categories are suggestions, not restrictions.

## Development

Python 3.11 is required:

```powershell
py -3.11 -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
.venv\Scripts\python -m pytest
.venv\Scripts\python -m reforge_pixels.app
```

Build and verify the Windows package:

```powershell
.\scripts\build_minimal_ffmpeg_windows.ps1
.\scripts\prepare_corresponding_source.ps1
$env:FFMPEG_BIN_DIRECTORY = "$PWD\artifacts\minimal-ffmpeg\bin"
.\scripts\build_windows.ps1 -CorrespondingSourceDirectory "$PWD\artifacts\corresponding-source"
.\scripts\verify_windows_release.ps1
```

The first command uses the pinned Docker recipe in `scripts/ffmpeg-builder` to cross-compile FFmpeg 7.1.1 and its static dependencies. Toolchain installation is cached, source archives are checksum-verified, concurrent builds are blocked, and the resulting Windows binaries must pass audio, HDR, NVENC, and import-table checks. The packaging step creates paired binary and corresponding-source ZIPs and refuses to finish unless [SOURCE_CODE.md](SOURCE_CODE.md) and [CORRESPONDING_SOURCE.md](CORRESPONDING_SOURCE.md) are satisfied.

For a public release, upload both locally built ZIPs to a draft GitHub release whose tag points to the current `main` commit. Run the **Verify and publish portable release** workflow from `main` with that tag. CI independently checks both archives and publishes the draft only when every gate passes. Do not commit release ZIPs to the repository.

## License

Reforge Pixels is licensed under GNU GPL version 3 or later. See [LICENSE](LICENSE), [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md), and [SOURCE_CODE.md](SOURCE_CODE.md).
