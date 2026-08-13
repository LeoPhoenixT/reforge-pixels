[CmdletBinding()]
param(
    [string]$ReleaseDirectory = "dist\Reforge-Pixels-windows-x64",
    [Parameter(Mandatory = $true)]
    [string]$CorrespondingSourceDirectory,
    [string]$ExpectedCommit
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$releaseCandidate = if ([System.IO.Path]::IsPathRooted($ReleaseDirectory)) { $ReleaseDirectory } else { Join-Path $projectRoot $ReleaseDirectory }
$sourceCandidate = if ([System.IO.Path]::IsPathRooted($CorrespondingSourceDirectory)) { $CorrespondingSourceDirectory } else { Join-Path $projectRoot $CorrespondingSourceDirectory }
$releaseRoot = (Resolve-Path $releaseCandidate).Path
$sourceRoot = (Resolve-Path $sourceCandidate).Path

$forbiddenPatterns = @(
    "PRIVATE_LOCAL_ONLY.txt",
    "*RTX*private*",
    "*rtx-video-vsr*",
    "*nvngx*",
    "*rtx_video*"
)
foreach ($pattern in $forbiddenPatterns) {
    $match = Get-ChildItem -LiteralPath $releaseRoot -Recurse -Force | Where-Object { $_.Name -like $pattern } | Select-Object -First 1
    if ($match) {
        throw "Release contains private RTX material: $($match.FullName)"
    }
}

$modelsManifest = Join-Path $releaseRoot "reforge_pixels\resources\models.json"
if (Test-Path -LiteralPath $modelsManifest -PathType Leaf) {
    if ((Get-Content -LiteralPath $modelsManifest -Raw) -match 'rtx-video-vsr|nvngx|rtx_video') {
        throw "Public model manifest contains a private RTX model or implementation reference"
    }
}

$requiredReleaseFiles = @(
    "LICENSE.md",
    "README.md",
    "SOURCE_CODE.md",
    "CORRESPONDING_SOURCE.md",
    "BUILD_PROVENANCE.json",
    "PORTABLE_SELF_TEST.json",
    "THIRD_PARTY_NOTICES.md",
    "licenses\LICENSE",
    "licenses\Qt-PySide6-Shiboken-GPLv3.txt",
    "licenses\CPython-LICENSE.txt",
    "licenses\Pillow-LICENSE.txt",
    "licenses\pillow-heif-LICENSE.txt",
    "licenses\pillow-heif-bundled-LICENSES.txt",
    "licenses\FFmpeg-COPYING.GPLv3.txt",
    "licenses\FFmpeg-build-LICENSE.txt",
    "licenses\FFmpeg-build-README.txt",
    "licenses\x264-COPYING.txt",
    "licenses\Opus-COPYING.txt",
    "licenses\zimg-COPYING.txt",
    "licenses\zlib-LICENSE.txt",
    "licenses\nv-codec-headers-LICENSE.txt",
    "licenses\ncnn-LICENSE.txt",
    "licenses\Real-ESRGAN-LICENSE.txt",
    "licenses\Real-ESRGAN-ncnn-vulkan-LICENSE.txt",
    "licenses\waifu2x-ncnn-vulkan-LICENSE.txt",
    "licenses\realcugan-ncnn-vulkan-LICENSE.txt"
)
foreach ($relative in $requiredReleaseFiles) {
    if (-not (Test-Path -LiteralPath (Join-Path $releaseRoot $relative) -PathType Leaf)) {
        throw "Required release license or notice file is missing: $relative"
    }
}

$selfTest = Get-Content -LiteralPath (Join-Path $releaseRoot "PORTABLE_SELF_TEST.json") -Raw | ConvertFrom-Json
if (-not $selfTest.success) {
    throw "Portable GPU self-test report does not record success"
}
$provenance = Get-Content -LiteralPath (Join-Path $releaseRoot "BUILD_PROVENANCE.json") -Raw | ConvertFrom-Json
if ($provenance.commit -notmatch '^[0-9a-f]{40}$' -or $provenance.tree -notmatch '^[0-9a-f]{40}$') {
    throw "Build provenance contains an invalid commit or tree hash"
}
if ($ExpectedCommit -and $provenance.commit -ne $ExpectedCommit) {
    throw "Portable archive was built from $($provenance.commit), expected $ExpectedCommit"
}

$requiredSources = @(
    "qtbase-everywhere-src-6.10.3.tar.xz",
    "pyside-setup-everywhere-src-6.10.3.tar.xz",
    "pillow-12.3.0.tar.gz",
    "pillow_heif-1.1.1.tar.gz",
    "libheif-1.18.1.tar.gz",
    "libde265-1.0.15.tar.gz",
    "x265-Release_3.4.tar.gz",
    "aom-v3.6.1.tar.gz",
    "ffmpeg-7.1.1-minimal-build-corresponding-source.tar.xz"
)
$manifestPath = Join-Path $sourceRoot "SOURCE_SHA256SUMS.txt"
if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
    throw "Corresponding-source checksum manifest is missing: $manifestPath"
}

$manifest = @{}
foreach ($line in Get-Content -LiteralPath $manifestPath) {
    if ($line -notmatch '^([0-9a-f]{64})  ([^/\\]+)$') {
        throw "Invalid corresponding-source checksum line: $line"
    }
    if ($manifest.ContainsKey($Matches[2])) {
        throw "Duplicate corresponding-source checksum entry: $($Matches[2])"
    }
    $manifest[$Matches[2]] = $Matches[1]
}
foreach ($name in $requiredSources) {
    if (-not $manifest.ContainsKey($name)) {
        throw "Corresponding-source manifest does not list: $name"
    }
    $path = Join-Path $sourceRoot $name
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Required corresponding-source archive is missing: $name"
    }
    $actual = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne $manifest[$name]) {
        throw "Corresponding-source checksum mismatch: $name"
    }
}
if ($manifest.Count -ne $requiredSources.Count) {
    throw "Corresponding-source manifest contains unexpected files"
}

Write-Output "Release compliance verified: no private RTX material, required notices present, and $($requiredSources.Count) corresponding-source archives matched."
