[CmdletBinding()]
param(
    [switch]$RebuildToolchain,
    [switch]$SkipNvencTest,
    [switch]$PrepareSourcesOnly,
    [string]$PythonPath = ".venv\Scripts\python.exe"
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$builderRoot = Join-Path $PSScriptRoot "ffmpeg-builder"
$sourceRoot = Join-Path $projectRoot "artifacts\ffmpeg-source-cache"
$outputRoot = Join-Path $projectRoot "artifacts\minimal-ffmpeg"
$stagingRoot = Join-Path $projectRoot "artifacts\minimal-ffmpeg-staging"
$image = "reforge-pixels-ffmpeg-builder:ubuntu24.04-20260801"
$container = "reforge-pixels-ffmpeg-build"
$sources = @(
    @{ Name = "ffmpeg-7.1.1.tar.xz"; Hash = "733984395e0dbbe5c046abda2dc49a5544e7e0e1e2366bba849222ae9e3a03b1"; Url = "https://ffmpeg.org/releases/ffmpeg-7.1.1.tar.xz" },
    @{ Name = "nv-codec-headers-12.2.72.0.tar.gz"; Hash = "c295a2ba8a06434d4bdc5c2208f8a825285210d71d91d572329b2c51fd0d4d03"; Url = "https://github.com/FFmpeg/nv-codec-headers/releases/download/n12.2.72.0/nv-codec-headers-12.2.72.0.tar.gz" },
    @{ Name = "opus-1.5.2.tar.gz"; Hash = "65c1d2f78b9f2fb20082c38cbe47c951ad5839345876e46941612ee87f9a7ce1"; Url = "https://downloads.xiph.org/releases/opus/opus-1.5.2.tar.gz" },
    @{ Name = "x264-b35605ace3ddf7c1a5d67a2eb553f034aef41d55.tar.gz"; Hash = "cd71a7515b0e9a012e1ac9b1f8415bebcaf6fc97d4db32286642ac4c0fbe24f9"; Url = "https://code.videolan.org/videolan/x264/-/archive/b35605ace3ddf7c1a5d67a2eb553f034aef41d55/x264-b35605ace3ddf7c1a5d67a2eb553f034aef41d55.tar.gz" },
    @{ Name = "zimg-release-3.0.5.tar.gz"; Hash = "a9a0226bf85e0d83c41a8ebe4e3e690e1348682f6a2a7838f1b8cbff1b799bcf"; Url = "https://github.com/sekrit-twc/zimg/archive/refs/tags/release-3.0.5.tar.gz" },
    @{ Name = "zlib-1.3.2.tar.xz"; Hash = "d7a0654783a4da529d1bb793b7ad9c3318020af77667bcae35f95d0e42a792f3"; Url = "https://github.com/madler/zlib/releases/download/v1.3.2/zlib-1.3.2.tar.xz" }
)

function Assert-Sha256 {
    param([string]$Path, [string]$Expected)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Required FFmpeg source archive is missing: $Path"
    }
    $actual = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne $Expected) {
        throw "SHA-256 mismatch for $Path. Expected $Expected, got $actual"
    }
}

New-Item -ItemType Directory -Force -Path $sourceRoot | Out-Null
foreach ($source in $sources) {
    $destination = Join-Path $sourceRoot $source.Name
    if (-not (Test-Path -LiteralPath $destination -PathType Leaf)) {
        $partial = "$destination.download"
        if (Test-Path -LiteralPath $partial) { Remove-Item -LiteralPath $partial -Force }
        Invoke-WebRequest -UseBasicParsing -Uri $source.Url -OutFile $partial
        Assert-Sha256 $partial $source.Hash
        Move-Item -LiteralPath $partial -Destination $destination
    }
    Assert-Sha256 $destination $source.Hash
}
if ($PrepareSourcesOnly) {
    Write-Output "Prepared and verified $($sources.Count) FFmpeg source archives at: $sourceRoot"
    return
}

docker version | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Docker Desktop is not available" }

$existing = docker container ls --all --filter "name=^/$container$" --format '{{.Status}}'
if ($LASTEXITCODE -ne 0) { throw "Unable to query existing Docker containers" }
if ($existing) {
    throw "Build container '$container' already exists with status '$existing'. Inspect it instead of starting a concurrent build."
}

$dockerBuildArguments = @("build", "--progress=plain", "--tag", $image)
if ($RebuildToolchain) { $dockerBuildArguments += "--no-cache" }
$dockerBuildArguments += $builderRoot
docker @dockerBuildArguments
if ($LASTEXITCODE -ne 0) { throw "Unable to build the pinned FFmpeg toolchain image" }

if (Test-Path -LiteralPath $stagingRoot) {
    Remove-Item -LiteralPath $stagingRoot -Recurse -Force
}
New-Item -ItemType Directory -Path $stagingRoot | Out-Null

docker create `
    --name $container `
    --cpus 12 `
    --memory 16g `
    --mount "type=bind,source=$sourceRoot,target=/sources,readonly" `
    --mount "type=bind,source=$stagingRoot,target=/out" `
    $image | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Unable to create the FFmpeg build container" }

$buildSucceeded = $false
try {
    docker start --attach $container
    if ($LASTEXITCODE -ne 0) { throw "Minimal FFmpeg cross-build failed" }
    $buildSucceeded = $true
} finally {
    if ($buildSucceeded) {
        docker rm -f $container 2>$null | Out-Null
    } else {
        Write-Warning "Failed build container '$container' was retained for inspection."
    }
}

$binaryManifest = Join-Path $stagingRoot "bin\FFMPEG_SHA256SUMS.txt"
if (-not (Test-Path -LiteralPath $binaryManifest -PathType Leaf)) {
    throw "FFmpeg output checksum manifest was not created"
}
if (Test-Path -LiteralPath $outputRoot) {
    Remove-Item -LiteralPath $outputRoot -Recurse -Force
}
Move-Item -LiteralPath $stagingRoot -Destination $outputRoot
$pythonCandidate = if ([System.IO.Path]::IsPathRooted($PythonPath)) { $PythonPath } else { Join-Path $projectRoot $PythonPath }
$python = (Resolve-Path $pythonCandidate).Path
$verificationArguments = @(
    (Join-Path $PSScriptRoot "verify_minimal_ffmpeg_windows.py"),
    "--bin-directory", (Join-Path $outputRoot "bin"),
    "--builder-image", $image
)
if (-not $SkipNvencTest) { $verificationArguments += "--require-nvenc" }
& $python @verificationArguments
if ($LASTEXITCODE -ne 0) { throw "Minimal FFmpeg verification failed" }
Get-Content -LiteralPath (Join-Path $outputRoot "bin\FFMPEG_SHA256SUMS.txt")
