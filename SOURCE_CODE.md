# Corresponding Source for Binary Releases

Reforge Pixels binary releases combine GPL/LGPL components with permissively licensed components. Publishing a binary release requires corresponding-source availability, not only license links.

For every public binary release:

1. The Git tag must contain the exact Reforge Pixels source and build scripts used for the binary.
2. GitHub's automatically generated source archives must remain attached to the release.
3. Exact corresponding-source archives and build/configuration material for the redistributed FFmpeg build and its statically linked GPL components must be attached to the same release or made available through an equivalent durable download next to the binary.
4. Exact Qt/PySide6 source availability and relinking/replacement rights required by the selected GPLv3/LGPLv3 terms must be documented and provided.
5. The release must include applicable license and notice files for CPython, Qt/PySide6/Shiboken6, Pillow, pillow-heif/libheif, FFmpeg, NCNN, Real-ESRGAN, Waifu2x, Real-CUGAN, and bundled runtime libraries.
6. Release maintainers must retain the source and build inputs for as long as the release is distributed and for any additional period required by the selected license-conveyance method.

The exact required source-bundle inventory and release pairing are defined in [CORRESPONDING_SOURCE.md](CORRESPONDING_SOURCE.md). The portable build fails when that source bundle is absent or incomplete.

Build the Windows release locally on an RTX system, complete this checklist, verify the binary/source asset hashes, and then create or update the GitHub release manually. Do not publish a binary release before the corresponding-source requirements above are satisfied.

This file is a release checklist, not legal advice.
