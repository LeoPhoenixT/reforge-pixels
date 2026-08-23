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
. (Join-Path $PSScriptRoot "release-sources.ps1")
$releaseSources = Read-ReleaseSources -ManifestPath (Join-Path $PSScriptRoot "release-sources.json")
$sources = @($releaseSources | Where-Object { $_.kind -eq "download" })
$ffmpegSource = @($releaseSources | Where-Object { $_.kind -eq "ffmpeg-build" })[0]

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
        Assert-Sha256 $partial $source.sha256
        Move-Item -LiteralPath $partial -Destination $destination
    }
    Assert-Sha256 $destination $source.sha256
}

$builtFfmpegSource = Join-Path $ffmpegRoot $ffmpegSource.Name
Assert-Sha256 $builtFfmpegSource $ffmpegSource.sha256
$stagedFfmpegSource = Join-Path $sourceRoot $ffmpegSource.Name
Copy-Item -LiteralPath $builtFfmpegSource -Destination $stagedFfmpegSource -Force
Assert-Sha256 $stagedFfmpegSource $ffmpegSource.sha256

$expectedNames = @($releaseSources.Name)
$unexpected = Get-ChildItem -LiteralPath $sourceRoot -File |
    Where-Object { $_.Name -ne "SOURCE_SHA256SUMS.txt" -and $_.Name -notin $expectedNames }
if ($unexpected) {
    throw "Corresponding-source directory contains unexpected files: $($unexpected.Name -join ', ')"
}

$hashByName = @{}
foreach ($source in $releaseSources) { $hashByName[$source.Name] = $source.sha256 }
$manifest = $expectedNames | Sort-Object | ForEach-Object { "$($hashByName[$_])  $_" }
[System.IO.File]::WriteAllLines((Join-Path $sourceRoot "SOURCE_SHA256SUMS.txt"), $manifest)

foreach ($name in $expectedNames) {
    & tar -tf (Join-Path $sourceRoot $name) *> $null
    if ($LASTEXITCODE -ne 0) { throw "Source archive failed integrity check: $name" }
}

Write-Output "Prepared and verified $($expectedNames.Count) corresponding-source archives at: $sourceRoot"
