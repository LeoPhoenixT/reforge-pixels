[CmdletBinding()]
param(
    [string]$SourceDirectory = "artifacts\corresponding-source",
    [string]$FfmpegBuildDirectory = "artifacts\minimal-ffmpeg"
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$sourceCandidate = if ([System.IO.Path]::IsPathRooted($SourceDirectory)) { $SourceDirectory } else { Join-Path $projectRoot $SourceDirectory }
$ffmpegCandidate = if ([System.IO.Path]::IsPathRooted($FfmpegBuildDirectory)) { $FfmpegBuildDirectory } else { Join-Path $projectRoot $FfmpegBuildDirectory }
$sourceRoot = [System.IO.Path]::GetFullPath($sourceCandidate)
$ffmpegRoot = [System.IO.Path]::GetFullPath($ffmpegCandidate)

$sources = @(
    @{ Name = "qtbase-everywhere-src-6.10.3.tar.xz"; Hash = "383dc907816338f0cba72088a524c07458dfc69ce684ca9132fcc4fe91c24b0b"; Url = "https://download.qt.io/official_releases/qt/6.10/6.10.3/submodules/qtbase-everywhere-src-6.10.3.tar.xz" },
    @{ Name = "pyside-setup-everywhere-src-6.10.3.tar.xz"; Hash = "2c7462fe0cecb5b8ac0a3d92014b8d0b88bd4d9f8646709dab5286d9416f45bc"; Url = "https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-6.10.3-src/pyside-setup-everywhere-src-6.10.3.tar.xz" },
    @{ Name = "pillow-12.3.0.tar.gz"; Hash = "3b8182a766685eaa002637e28b4ec8d6b18819a0c71f579bf0dbaa5830297cce"; Url = "https://files.pythonhosted.org/packages/1c/3d/bb7fca845737cf9d7dbde16ed1843984665ff2e0a518f5db43e77ec540b9/pillow-12.3.0.tar.gz" },
    @{ Name = "pillow_heif-1.1.1.tar.gz"; Hash = "f60e8c8a8928556104cec4fff39d43caa1da105625bdb53b11ce3c89d09b6bde"; Url = "https://files.pythonhosted.org/packages/64/65/77284daf2a8a2849b9040889bd8e1b845e693ed97973a28ba2122b8922ad/pillow_heif-1.1.1.tar.gz" },
    @{ Name = "libheif-1.18.1.tar.gz"; Hash = "8702564b0f288707ea72b260b3bf4ba9bf7abfa7dac01353def3a86acd6bbb76"; Url = "https://github.com/strukturag/libheif/releases/download/v1.18.1/libheif-1.18.1.tar.gz" },
    @{ Name = "libde265-1.0.15.tar.gz"; Hash = "00251986c29d34d3af7117ed05874950c875dd9292d016be29d3b3762666511d"; Url = "https://github.com/strukturag/libde265/releases/download/v1.0.15/libde265-1.0.15.tar.gz" },
    @{ Name = "x265-Release_3.4.tar.gz"; Hash = "d23240caf20f58dd54948c675b14147e1be975a150a75f0aac77e330e2748683"; Url = "https://bitbucket.org/multicoreware/x265_git/get/Release_3.4.tar.gz" },
    @{ Name = "aom-v3.6.1.tar.gz"; Hash = "8448d03589041c33cd9f22ea35783739eb7829050fa3cef359b8ff67561f6f32"; Url = "https://aomedia.googlesource.com/aom/+archive/refs/tags/v3.6.1.tar.gz" }
)
$ffmpegSource = @{
    Name = "ffmpeg-7.1.1-minimal-build-corresponding-source.tar.xz"
    Hash = "456349722e877eb280c795584f0be4c8cba11c83147cbe31bef194a1abaeabf0"
}

function Assert-Sha256 {
    param([string]$Path, [string]$Expected)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Required source archive is missing: $Path"
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

$builtFfmpegSource = Join-Path $ffmpegRoot $ffmpegSource.Name
Assert-Sha256 $builtFfmpegSource $ffmpegSource.Hash
$stagedFfmpegSource = Join-Path $sourceRoot $ffmpegSource.Name
Copy-Item -LiteralPath $builtFfmpegSource -Destination $stagedFfmpegSource -Force
Assert-Sha256 $stagedFfmpegSource $ffmpegSource.Hash

$expectedNames = @($sources.Name) + $ffmpegSource.Name
$unexpected = Get-ChildItem -LiteralPath $sourceRoot -File |
    Where-Object { $_.Name -ne "SOURCE_SHA256SUMS.txt" -and $_.Name -notin $expectedNames }
if ($unexpected) {
    throw "Corresponding-source directory contains unexpected files: $($unexpected.Name -join ', ')"
}

$hashByName = @{}
foreach ($source in $sources) { $hashByName[$source.Name] = $source.Hash }
$hashByName[$ffmpegSource.Name] = $ffmpegSource.Hash
$manifest = $expectedNames | Sort-Object | ForEach-Object { "$($hashByName[$_])  $_" }
[System.IO.File]::WriteAllLines((Join-Path $sourceRoot "SOURCE_SHA256SUMS.txt"), $manifest)

foreach ($name in $expectedNames) {
    & tar -tf (Join-Path $sourceRoot $name) *> $null
    if ($LASTEXITCODE -ne 0) { throw "Source archive failed integrity check: $name" }
}

Write-Output "Prepared and verified $($expectedNames.Count) corresponding-source archives at: $sourceRoot"
