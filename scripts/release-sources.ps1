function Read-ReleaseSources {
    param([Parameter(Mandatory = $true)][string]$ManifestPath)

    if (-not (Test-Path -LiteralPath $ManifestPath -PathType Leaf)) {
        throw "Release source manifest is missing: $ManifestPath"
    }
    try {
        $manifest = Get-Content -LiteralPath $ManifestPath -Raw | ConvertFrom-Json
    } catch {
        throw "Release source manifest is not valid JSON: $ManifestPath`n$($_.Exception.Message)"
    }
    if ($manifest.schemaVersion -ne 1) {
        throw "Release source manifest has an unsupported schemaVersion: $($manifest.schemaVersion)"
    }
    if (-not $manifest.sources -or @($manifest.sources).Count -eq 0) {
        throw "Release source manifest must contain a non-empty sources array"
    }

    $names = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
    $buildSources = 0
    foreach ($source in @($manifest.sources)) {
        if (-not $source.name -or $source.name -notmatch '^[^/\\]+$') {
            throw "Release source manifest contains a missing or invalid name: $($source.name)"
        }
        if (-not $names.Add([string]$source.name)) {
            throw "Release source manifest contains a duplicate name: $($source.name)"
        }
        if (-not $source.sha256 -or $source.sha256 -notmatch '^[0-9a-f]{64}$') {
            throw "Release source manifest contains an invalid SHA-256 for $($source.name)"
        }
        if ($source.kind -notin @("download", "ffmpeg-build")) {
            throw "Release source manifest contains an unsupported kind for $($source.name): $($source.kind)"
        }
        if ($source.kind -eq "download") {
            if (-not $source.url -or -not [Uri]::IsWellFormedUriString([string]$source.url, [UriKind]::Absolute)) {
                throw "Download source has a missing or invalid URL: $($source.name)"
            }
        } else {
            $buildSources++
            if ($source.url) {
                throw "Locally built FFmpeg source must not define a URL: $($source.name)"
            }
        }
    }
    if ($buildSources -ne 1) {
        throw "Release source manifest must define exactly one ffmpeg-build source"
    }
    return @($manifest.sources)
}
