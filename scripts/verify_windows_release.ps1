[CmdletBinding()]
param(
    [string]$ReleaseDirectory = "dist\Reforge-Pixels-windows-x64"
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$releaseRoot = (Resolve-Path (Join-Path $projectRoot $ReleaseDirectory)).Path
$manifestPath = Join-Path $releaseRoot "SHA256SUMS.txt"
if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
    throw "Checksum manifest is missing: $manifestPath"
}

$expectedPaths = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
foreach ($line in Get-Content -LiteralPath $manifestPath) {
    if ($line -notmatch '^([0-9a-f]{64})  (.+)$') {
        throw "Invalid checksum line: $line"
    }
    $expectedHash = $Matches[1]
    $relative = $Matches[2]
    $null = $expectedPaths.Add($relative)
    $path = Join-Path $releaseRoot ($relative.Replace('/', '\'))
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Manifest file is missing: $relative"
    }
    $actualHash = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actualHash -ne $expectedHash) {
        throw "Checksum mismatch: $relative"
    }
}

$actualPaths = Get-ChildItem -LiteralPath $releaseRoot -Recurse -File |
    ForEach-Object { $_.FullName.Substring($releaseRoot.TrimEnd('\').Length + 1).Replace('\', '/') } |
    Where-Object { $_ -ne 'SHA256SUMS.txt' }
foreach ($relative in $actualPaths) {
    if (-not $expectedPaths.Contains($relative)) {
        throw "Release contains an unmanifested file: $relative"
    }
}
if ($expectedPaths.Count -ne @($actualPaths).Count) {
    throw "Checksum manifest count does not match release file count"
}

Write-Output "Verified $($expectedPaths.Count) release files and SHA-256 checksums."
