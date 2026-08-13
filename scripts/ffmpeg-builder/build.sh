#!/usr/bin/env bash
set -euo pipefail

export SOURCE_DATE_EPOCH=1740960000
export TZ=UTC
export LC_ALL=C

sources=/sources
work=/build
prefix=/opt/ffmpeg-minimal
out=/out
cross=x86_64-w64-mingw32
x264_commit=b35605ace3ddf7c1a5d67a2eb553f034aef41d55

expected_sources=(
  "733984395e0dbbe5c046abda2dc49a5544e7e0e1e2366bba849222ae9e3a03b1  ffmpeg-7.1.1.tar.xz"
  "c295a2ba8a06434d4bdc5c2208f8a825285210d71d91d572329b2c51fd0d4d03  nv-codec-headers-12.2.72.0.tar.gz"
  "65c1d2f78b9f2fb20082c38cbe47c951ad5839345876e46941612ee87f9a7ce1  opus-1.5.2.tar.gz"
  "cd71a7515b0e9a012e1ac9b1f8415bebcaf6fc97d4db32286642ac4c0fbe24f9  x264-b35605ace3ddf7c1a5d67a2eb553f034aef41d55.tar.gz"
  "a9a0226bf85e0d83c41a8ebe4e3e690e1348682f6a2a7838f1b8cbff1b799bcf  zimg-release-3.0.5.tar.gz"
  "d7a0654783a4da529d1bb793b7ad9c3318020af77667bcae35f95d0e42a792f3  zlib-1.3.2.tar.xz"
)

phase() { printf '\n[%s] %s\n' "$(date -u +%H:%M:%S)" "$*"; }

phase "Verify pinned source archives"
printf '%s\n' "${expected_sources[@]}" > /tmp/expected-sources.txt
(cd "$sources" && sha256sum --check /tmp/expected-sources.txt)

rm -rf "$work" "$prefix"
mkdir -p "$work" "$prefix" "$out"

phase "Build nv-codec-headers 12.2.72.0"
tar -xf "$sources/nv-codec-headers-12.2.72.0.tar.gz" -C "$work"
make -C "$work/nv-codec-headers-12.2.72.0" PREFIX="$prefix" install

phase "Build Opus 1.5.2"
tar -xf "$sources/opus-1.5.2.tar.gz" -C "$work"
(cd "$work/opus-1.5.2" && ./configure --host="$cross" --prefix="$prefix" --disable-shared --enable-static && make -j12 && make install)

phase "Build zlib 1.3.2"
tar -xf "$sources/zlib-1.3.2.tar.xz" -C "$work"
(cd "$work/zlib-1.3.2" && CHOST="$cross" ./configure --prefix="$prefix" --static && make -j12 && make install)

phase "Build zimg 3.0.5"
tar -xf "$sources/zimg-release-3.0.5.tar.gz" -C "$work"
(cd "$work/zimg-release-3.0.5" && ./autogen.sh && ./configure --host="$cross" --prefix="$prefix" --disable-shared --enable-static && make -j12 && make install)

phase "Build x264 $x264_commit"
tar -xf "$sources/x264-$x264_commit.tar.gz" -C "$work"
(cd "$work/x264-$x264_commit" && ./configure --host="$cross" --cross-prefix="$cross-" --prefix="$prefix" --enable-static --disable-cli && make -j12 && make install)

phase "Configure FFmpeg 7.1.1"
tar -xf "$sources/ffmpeg-7.1.1.tar.xz" -C "$work"
configure_args=(
  --prefix="$prefix"
  --pkg-config=pkg-config
  --pkg-config-flags=--static
  --extra-cflags="-I$prefix/include -ffile-prefix-map=$work=/usr/src -fdebug-prefix-map=$work=/usr/src"
  --extra-ldflags="-L$prefix/lib -static"
  --extra-libs="-lpthread"
  --enable-cross-compile
  --target-os=mingw32
  --arch=x86_64
  --cross-prefix="$cross-"
  --disable-autodetect
  --disable-debug
  --disable-doc
  --disable-network
  --disable-shared
  --enable-static
  --enable-gpl
  --enable-version3
  --enable-w32threads
  --enable-libx264
  --enable-libopus
  --enable-libzimg
  --enable-zlib
  --enable-ffnvcodec
  --enable-nvenc
)
printf '%q ' "${configure_args[@]}" > /tmp/configure-command.txt
printf '\n' >> /tmp/configure-command.txt
(cd "$work/ffmpeg-7.1.1" && PKG_CONFIG_PATH="$prefix/lib/pkgconfig" ./configure "${configure_args[@]}")

phase "Compile FFmpeg and FFprobe"
make -C "$work/ffmpeg-7.1.1" -j12 ffmpeg.exe ffprobe.exe

phase "Assemble deterministic outputs"
staging=/tmp/output
rm -rf "$staging"
mkdir -p "$staging/bin" "$staging/licenses" "$staging/corresponding-source/sources" "$staging/corresponding-source/recipe"
cp "$work/ffmpeg-7.1.1/ffmpeg.exe" "$work/ffmpeg-7.1.1/ffprobe.exe" "$staging/bin/"
cp "$work/ffmpeg-7.1.1/COPYING.GPLv3" "$staging/LICENSE"
cp "$work/ffmpeg-7.1.1/COPYING.GPLv3" "$staging/licenses/FFmpeg-COPYING.GPLv3.txt"
cp "$work/x264-$x264_commit/COPYING" "$staging/licenses/x264-COPYING.txt"
cp "$work/opus-1.5.2/COPYING" "$staging/licenses/Opus-COPYING.txt"
cp "$work/zimg-release-3.0.5/COPYING" "$staging/licenses/zimg-COPYING.txt"
cp "$work/zlib-1.3.2/LICENSE" "$staging/licenses/zlib-LICENSE.txt"
sed -n '1,/^ \*\/$/p' \
  "$work/nv-codec-headers-12.2.72.0/include/ffnvcodec/nvEncodeAPI.h" \
  > "$staging/licenses/nv-codec-headers-LICENSE.txt"
cp /tmp/configure-command.txt "$staging/configure-command.txt"
cp /recipe/toolchain-packages.txt "$staging/toolchain-packages.txt"
{
  echo "Reforge Pixels minimal FFmpeg Windows build"
  echo "FFmpeg: 7.1.1 with x264, Opus, zimg, zlib, and nv-codec-headers"
  echo "Source date epoch: $SOURCE_DATE_EPOCH"
  echo "Builder base: ubuntu@sha256:561618e2c15bf2397621dd04f96926663a3b5616c189cf7e38db7e82f5c538ea"
  echo "Ubuntu snapshot: 20260801T000000Z"
  echo "See configure-command.txt, toolchain-packages.txt, and the paired corresponding-source archive."
} > "$staging/README.txt"
(cd "$staging/bin" && sha256sum ffmpeg.exe ffprobe.exe | sort > FFMPEG_SHA256SUMS.txt)

while IFS= read -r source_line; do
  cp "$sources/${source_line#*  }" "$staging/corresponding-source/sources/"
done < /tmp/expected-sources.txt
printf '%s\n' "${expected_sources[@]}" > "$staging/corresponding-source/sources/SOURCE_SHA256SUMS.txt"
cp /recipe/Dockerfile /recipe/build.sh /recipe/toolchain-packages.txt /tmp/configure-command.txt "$staging/corresponding-source/recipe/"
cp -r "$staging/licenses" "$staging/corresponding-source/"
find "$staging/corresponding-source" -exec touch -h -d "@$SOURCE_DATE_EPOCH" {} +
tar --sort=name --mtime="@$SOURCE_DATE_EPOCH" --owner=0 --group=0 --numeric-owner \
  -C "$staging/corresponding-source" -cJf "$staging/ffmpeg-7.1.1-minimal-build-corresponding-source.tar.xz" .

rm -rf "$out"/*
cp -r "$staging"/* "$out/"
phase "Build complete"
cat "$out/bin/FFMPEG_SHA256SUMS.txt"
