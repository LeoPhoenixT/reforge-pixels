# Third-Party Notices

Reforge Pixels is distributed under GNU GPL version 3 or later. A binary release must satisfy `SOURCE_CODE.md` and include the applicable license and notice texts.

## Real-ESRGAN NCNN/Vulkan

- Component: `realesrgan-ncnn-vulkan-20220424-windows`
- Upstream: <https://github.com/xinntao/Real-ESRGAN-ncnn-vulkan>
- Project release: Real-ESRGAN v0.2.5.0
- License: BSD 3-Clause
- Bundle SHA-256: `abc02804e17982a3be33675e4d471e91ea374e65b70167abc09e31acb412802d`
- License-text SHA-256: `5abb941454de437b0e90d78dcb72e3688f74e14bcd4e24393273cb5cd0e9c937`

The release includes the unmodified executable, supporting DLLs, and validated model files from the official portable bundle.

## Waifu2x NCNN/Vulkan

- Component: `waifu2x-ncnn-vulkan-20250915-windows`
- Upstream: <https://github.com/nihui/waifu2x-ncnn-vulkan>
- License: MIT
- Bundle SHA-256: `7425be94b94e4c8f37a1e433ac0e0100c43790e2c37418f4b65d8235adfbdc87`
- Bundled license SHA-256: `0100dda18fae09954490a58690d1ddd9355794a0a60da80609c9a8886ca587c6`

The portable release includes the official executable plus `models-upconv_7_photo`, `models-cunet`, and `models-upconv_7_anime_style_art_rgb`.

## Real-CUGAN NCNN/Vulkan

- Component: `realcugan-ncnn-vulkan-20220728-windows`
- Upstream: <https://github.com/nihui/realcugan-ncnn-vulkan>
- License: MIT
- Bundle SHA-256: `c6e08d46c11704b1e3a1ada9ddd591cb5005f52f132136c8633ba25def400e01`
- Bundled license SHA-256: `0100dda18fae09954490a58690d1ddd9355794a0a60da80609c9a8886ca587c6`

The portable release includes the official executable and the SE and Pro native-scale model families. Model selection is capability-driven; unsupported scale/noise combinations are never synthesized.

## FFmpeg

- Component: FFmpeg 7.1.1 full Windows build
- Upstream: <https://ffmpeg.org/>
- Binary distributor: <https://www.gyan.dev/ffmpeg/builds/>
- Effective license: GPL, because the selected build configuration contains `--enable-gpl` and GPL components
- `ffmpeg.exe` SHA-256: `b1383f5d07470d503edecdaee4bddc5891e986e916a698299b357f79cfe445fd`
- `ffprobe.exe` SHA-256: `012bddded3cbc5204055210d7ff4f0b3f7521bca441a694939856d01909f5756`
- GPLv3 license-text SHA-256: `8ceb4b9ee5adedde47b31e975c1d90c73ad27b6b165a1dcd80c7c545eb65b903`

The exact configure string from `ffmpeg -version`, license text, build material, and complete corresponding source for FFmpeg and applicable statically linked components must be available with a public binary release.

## CPython

- Component: CPython 3.11 runtime embedded by Nuitka
- Upstream: <https://www.python.org/>
- License: Python Software Foundation License Version 2 and bundled notices

The portable package includes the installed CPython license text.

## Qt for Python / PySide6

- Components: PySide6, PySide6 Essentials, PySide6 Addons, and Shiboken6 6.10.3
- Upstream: <https://doc.qt.io/qtforpython-6/>
- License choice for this GPL application: GPLv3; the upstream packages also offer LGPLv3/commercial alternatives

Only modules included by the standalone build are redistributed. The portable release includes the GPLv3 text and is paired with the exact Qt Base, PySide6, and Shiboken 6.10.3 corresponding-source archive described in `CORRESPONDING_SOURCE.md`.

## NCNN

- Component: NCNN version used by the pinned Real-ESRGAN portable engine
- Upstream: <https://github.com/Tencent/ncnn>
- License: BSD 3-Clause, with bundled third-party notices
- Pinned license/notice-text SHA-256: `6495f972a09ad7f64ccd953e79adba91a93d862edc7135e6d95210bbf4002a01`

## Nuitka (build-time only)

- Component: Nuitka 2.7.11
- Upstream: <https://nuitka.net/>
- Purpose: build-time Python compiler/packager
- License: Apache License 2.0

Nuitka is not presented as an end-user runtime dependency. The exact final binary inventory must be regenerated and reviewed for every release candidate.

## Pillow and pillow-heif

- Components: Pillow 12.3.0 and pillow-heif 1.1.1
- Upstreams: <https://python-pillow.github.io/> and <https://github.com/bigcat88/pillow_heif>
- Purpose: authoritative still-image metadata, orientation handling, HEIC/HEIF/AVIF decoding, tiling, and final image encoding

The pillow-heif binary wheel identifies bundled libheif 1.18.1 (LGPLv3), libde265 1.0.15 (LGPLv3), x265 Release 3.4 (GPLv2 or later), and libaom 3.6.1 (BSD 3-Clause). Their applicable notices are included, and the public binary must be paired with the exact source archives listed in `CORRESPONDING_SOURCE.md`.
