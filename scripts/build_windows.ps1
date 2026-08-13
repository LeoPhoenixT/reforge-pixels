[CmdletBinding()]
param(
    [string]$PythonPath = ".venv\Scripts\python.exe",
    [string]$FfmpegBinDirectory = $env:FFMPEG_BIN_DIRECTORY,
    [Parameter(Mandatory = $true)]
    [string]$CorrespondingSourceDirectory
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$trackedChanges = git -C $projectRoot status --porcelain --untracked-files=no
if ($LASTEXITCODE -ne 0) { throw "Unable to inspect Git state" }
if ($trackedChanges) { throw "Refusing to build a release from tracked working-tree changes" }
$sourceCommit = (git -C $projectRoot rev-parse HEAD).Trim()
$sourceTree = (git -C $projectRoot rev-parse 'HEAD^{tree}').Trim()
$pythonCandidate = if ([System.IO.Path]::IsPathRooted($PythonPath)) { $PythonPath } else { Join-Path $projectRoot $PythonPath }
$python = (Resolve-Path $pythonCandidate).Path
if (-not $FfmpegBinDirectory) {
    throw "Pass -FfmpegBinDirectory or set FFMPEG_BIN_DIRECTORY to the pinned FFmpeg 7.1.1 full-build bin directory"
}
$ffmpegDirectory = (Resolve-Path $FfmpegBinDirectory).Path
$buildRoot = Join-Path $projectRoot "build\windows"
$releaseRoot = Join-Path $projectRoot "dist\Reforge-Pixels-windows-x64"
$downloadDirectory = Join-Path $projectRoot "artifacts\downloads"
$engineArchive = Join-Path $downloadDirectory "realesrgan-ncnn-vulkan-20220424-windows.zip"
$engineSource = Join-Path $projectRoot "artifacts\realesrgan"
$waifuArchive = Join-Path $downloadDirectory "waifu2x-ncnn-vulkan-20250915-windows.zip"
$waifuExtractRoot = Join-Path $projectRoot "artifacts\waifu2x-20250915"
$waifuSource = Join-Path $waifuExtractRoot "waifu2x-ncnn-vulkan-20250915-windows"
$cuganArchive = Join-Path $downloadDirectory "realcugan-ncnn-vulkan-20220728-windows.zip"
$cuganExtractRoot = Join-Path $projectRoot "artifacts\realcugan-20220728"
$cuganSource = Join-Path $cuganExtractRoot "realcugan-ncnn-vulkan-20220728-windows"
$licenseSource = Join-Path $projectRoot "artifacts\licenses"
$releaseArchive = Join-Path $projectRoot "dist\Reforge-Pixels-windows-x64.zip"
$sourceArchive = Join-Path $projectRoot "dist\Reforge-Pixels-windows-x64-corresponding-source.zip"
$appIcon = Join-Path $projectRoot "src\reforge_pixels\resources\app-icon.ico"
if (-not (Test-Path -LiteralPath $appIcon -PathType Leaf)) {
    throw "Application icon is missing: $appIcon"
}

function Assert-Sha256 {
    param([string]$Path, [string]$Expected)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Required file is missing: $Path"
    }
    $actual = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne $Expected.ToLowerInvariant()) {
        throw "SHA-256 mismatch for $Path. Expected $Expected, got $actual"
    }
}

New-Item -ItemType Directory -Force -Path $downloadDirectory | Out-Null
if (-not (Test-Path -LiteralPath $engineArchive -PathType Leaf)) {
    Invoke-WebRequest `
        -Uri "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/realesrgan-ncnn-vulkan-20220424-windows.zip" `
        -OutFile $engineArchive
}
Assert-Sha256 $engineArchive "abc02804e17982a3be33675e4d471e91ea374e65b70167abc09e31acb412802d"

if (-not (Test-Path -LiteralPath $waifuArchive -PathType Leaf)) {
    Invoke-WebRequest -Uri "https://github.com/nihui/waifu2x-ncnn-vulkan/releases/download/20250915/waifu2x-ncnn-vulkan-20250915-windows.zip" -OutFile $waifuArchive
}
Assert-Sha256 $waifuArchive "7425be94b94e4c8f37a1e433ac0e0100c43790e2c37418f4b65d8235adfbdc87"

if (-not (Test-Path -LiteralPath $cuganArchive -PathType Leaf)) {
    Invoke-WebRequest -Uri "https://github.com/nihui/realcugan-ncnn-vulkan/releases/download/20220728/realcugan-ncnn-vulkan-20220728-windows.zip" -OutFile $cuganArchive
}
Assert-Sha256 $cuganArchive "c6e08d46c11704b1e3a1ada9ddd591cb5005f52f132136c8633ba25def400e01"

if (-not (Test-Path -LiteralPath (Join-Path $engineSource "realesrgan-ncnn-vulkan.exe"))) {
    New-Item -ItemType Directory -Force -Path $engineSource | Out-Null
    Expand-Archive -LiteralPath $engineArchive -DestinationPath $engineSource -Force
}
if (-not (Test-Path -LiteralPath (Join-Path $waifuSource "waifu2x-ncnn-vulkan.exe"))) {
    New-Item -ItemType Directory -Force -Path $waifuExtractRoot | Out-Null
    Expand-Archive -LiteralPath $waifuArchive -DestinationPath $waifuExtractRoot -Force
}
if (-not (Test-Path -LiteralPath (Join-Path $cuganSource "realcugan-ncnn-vulkan.exe"))) {
    New-Item -ItemType Directory -Force -Path $cuganExtractRoot | Out-Null
    Expand-Archive -LiteralPath $cuganArchive -DestinationPath $cuganExtractRoot -Force
}

$ffmpeg = Join-Path $ffmpegDirectory "ffmpeg.exe"
$ffprobe = Join-Path $ffmpegDirectory "ffprobe.exe"
Assert-Sha256 $ffmpeg "b1383f5d07470d503edecdaee4bddc5891e986e916a698299b357f79cfe445fd"
Assert-Sha256 $ffprobe "012bddded3cbc5204055210d7ff4f0b3f7521bca441a694939856d01909f5756"

$licenseDownloads = @(
    @{ Name = "Real-ESRGAN-ncnn-vulkan-LICENSE.txt"; Url = "https://raw.githubusercontent.com/xinntao/Real-ESRGAN-ncnn-vulkan/v0.2.0/LICENSE"; Hash = "5abb941454de437b0e90d78dcb72e3688f74e14bcd4e24393273cb5cd0e9c937" },
    @{ Name = "Real-ESRGAN-LICENSE.txt"; Url = "https://raw.githubusercontent.com/xinntao/Real-ESRGAN/v0.2.5.0/LICENSE"; Hash = "4a699ec4863d96a91fc265948a0c90033f7e8735d515524dcf3444736406e0c2" },
    @{ Name = "ncnn-LICENSE.txt"; Url = "https://raw.githubusercontent.com/Tencent/ncnn/20220420/LICENSE.txt"; Hash = "6495f972a09ad7f64ccd953e79adba91a93d862edc7135e6d95210bbf4002a01" },
    @{ Name = "FFmpeg-COPYING.GPLv3.txt"; Url = "https://raw.githubusercontent.com/FFmpeg/FFmpeg/n7.1.1/COPYING.GPLv3"; Hash = "8ceb4b9ee5adedde47b31e975c1d90c73ad27b6b165a1dcd80c7c545eb65b903" }
)
New-Item -ItemType Directory -Force -Path $licenseSource | Out-Null
foreach ($license in $licenseDownloads) {
    $licensePath = Join-Path $licenseSource $license.Name
    if (-not (Test-Path -LiteralPath $licensePath -PathType Leaf)) {
        Invoke-WebRequest -Uri $license.Url -OutFile $licensePath
    }
    Assert-Sha256 $licensePath $license.Hash
}

if (Test-Path -LiteralPath $buildRoot) {
    Remove-Item -LiteralPath $buildRoot -Recurse -Force
}
if (Test-Path -LiteralPath $releaseRoot) {
    Remove-Item -LiteralPath $releaseRoot -Recurse -Force
}
if (Test-Path -LiteralPath $releaseArchive) {
    Remove-Item -LiteralPath $releaseArchive -Force
}
if (Test-Path -LiteralPath $sourceArchive) {
    Remove-Item -LiteralPath $sourceArchive -Force
}
New-Item -ItemType Directory -Force -Path $buildRoot,$releaseRoot | Out-Null

& $python -m pip install "Nuitka==2.7.11" "ordered-set==4.1.0" "zstandard==0.23.0"
if ($LASTEXITCODE -ne 0) { throw "Unable to install pinned build dependencies" }

& $python -m nuitka `
    (Join-Path $projectRoot "src\reforge_pixels\app.py") `
    --standalone `
    --enable-plugin=pyside6 `
    --include-package=reforge_pixels `
    --include-package-data=reforge_pixels `
    --windows-console-mode=disable `
    --windows-icon-from-ico=$appIcon `
    --output-filename=Reforge-Pixels.exe `
    --output-dir=$buildRoot `
    --assume-yes-for-downloads `
    --noinclude-qt-plugins=iconengines `
    --noinclude-qt-plugins=imageformats `
    --noinclude-qt-plugins=tls `
    --noinclude-qt-translations
if ($LASTEXITCODE -ne 0) { throw "Nuitka build failed" }

$standaloneDirectory = Get-ChildItem -LiteralPath $buildRoot -Directory -Filter "*.dist" | Select-Object -First 1
if (-not $standaloneDirectory) { throw "Nuitka standalone output was not found" }
Copy-Item -Path (Join-Path $standaloneDirectory.FullName "*") -Destination $releaseRoot -Recurse -Force

$engineDestination = Join-Path $releaseRoot "runtime\engines\windows"
$realesrganDestination = Join-Path $engineDestination "realesrgan"
$waifuDestination = Join-Path $engineDestination "waifu2x"
$cuganDestination = Join-Path $engineDestination "realcugan"
$toolDestination = Join-Path $releaseRoot "runtime\tools\windows"
$licenseDestination = Join-Path $releaseRoot "licenses"
New-Item -ItemType Directory -Force -Path $realesrganDestination,$waifuDestination,$cuganDestination,$toolDestination,$licenseDestination | Out-Null
Copy-Item -LiteralPath (Join-Path $engineSource "realesrgan-ncnn-vulkan.exe") -Destination $realesrganDestination
Copy-Item -LiteralPath (Join-Path $engineSource "vcomp140.dll") -Destination $realesrganDestination
Copy-Item -LiteralPath (Join-Path $engineSource "models") -Destination $realesrganDestination -Recurse
Copy-Item -LiteralPath (Join-Path $waifuSource "waifu2x-ncnn-vulkan.exe") -Destination $waifuDestination
Copy-Item -LiteralPath (Join-Path $waifuSource "vcomp140.dll") -Destination $waifuDestination
Copy-Item -LiteralPath (Join-Path $waifuSource "models-upconv_7_photo") -Destination $waifuDestination -Recurse
Copy-Item -LiteralPath (Join-Path $waifuSource "models-cunet") -Destination $waifuDestination -Recurse
Copy-Item -LiteralPath (Join-Path $waifuSource "models-upconv_7_anime_style_art_rgb") -Destination $waifuDestination -Recurse
Copy-Item -LiteralPath (Join-Path $cuganSource "realcugan-ncnn-vulkan.exe") -Destination $cuganDestination
Copy-Item -LiteralPath (Join-Path $cuganSource "vcomp140.dll") -Destination $cuganDestination
Copy-Item -LiteralPath (Join-Path $cuganSource "models-se") -Destination $cuganDestination -Recurse
Copy-Item -LiteralPath (Join-Path $cuganSource "models-pro") -Destination $cuganDestination -Recurse
Copy-Item -LiteralPath $ffmpeg,$ffprobe -Destination $toolDestination
Copy-Item -LiteralPath (Join-Path $projectRoot "README.md"),(Join-Path $projectRoot "THIRD_PARTY_NOTICES.md"),(Join-Path $projectRoot "SOURCE_CODE.md"),(Join-Path $projectRoot "CORRESPONDING_SOURCE.md") -Destination $releaseRoot
Copy-Item -LiteralPath (Join-Path $projectRoot "LICENSE") -Destination (Join-Path $releaseRoot "LICENSE.md")
$ffmpegDistributionRoot = Split-Path $ffmpegDirectory -Parent
$ffmpegBuildReadme = Join-Path $ffmpegDistributionRoot "README.txt"
$ffmpegBuildLicense = Join-Path $ffmpegDistributionRoot "LICENSE"
if (-not (Test-Path -LiteralPath $ffmpegBuildReadme -PathType Leaf) -or -not (Test-Path -LiteralPath $ffmpegBuildLicense -PathType Leaf)) {
    throw "FFmpeg distributor README or license is missing from: $ffmpegDistributionRoot"
}

if (Test-Path -LiteralPath (Join-Path $projectRoot "LICENSE")) {
    Copy-Item -LiteralPath (Join-Path $projectRoot "LICENSE") -Destination $licenseDestination
    Copy-Item -LiteralPath (Join-Path $projectRoot "LICENSE") -Destination (Join-Path $licenseDestination "Qt-PySide6-Shiboken-GPLv3.txt")
} else {
    throw "Repository LICENSE is missing; refusing to create a distributable package"
}
foreach ($license in $licenseDownloads) {
    Copy-Item -LiteralPath (Join-Path $licenseSource $license.Name) -Destination $licenseDestination
}
Copy-Item -LiteralPath $ffmpegBuildReadme -Destination (Join-Path $licenseDestination "FFmpeg-build-README.txt")
Copy-Item -LiteralPath $ffmpegBuildLicense -Destination (Join-Path $licenseDestination "FFmpeg-build-LICENSE.txt")
Copy-Item -LiteralPath (Join-Path $waifuSource "LICENSE") -Destination (Join-Path $licenseDestination "waifu2x-ncnn-vulkan-LICENSE.txt")
Copy-Item -LiteralPath (Join-Path $cuganSource "LICENSE") -Destination (Join-Path $licenseDestination "realcugan-ncnn-vulkan-LICENSE.txt")
$pythonBase = (& $python -c "import sys; print(sys.base_prefix)").Trim()
$pythonLicense = Join-Path $pythonBase "LICENSE.txt"
if (-not (Test-Path -LiteralPath $pythonLicense -PathType Leaf)) {
    throw "Required CPython license is missing: $pythonLicense"
}
Copy-Item -LiteralPath $pythonLicense -Destination (Join-Path $licenseDestination "CPython-LICENSE.txt")
$pythonSitePackages = Join-Path (Split-Path $python -Parent) "..\Lib\site-packages"
$wheelLicenses = @(
    @{ Source = "pillow-12.3.0.dist-info\licenses\LICENSE"; Destination = "Pillow-LICENSE.txt" },
    @{ Source = "pillow_heif-1.1.1.dist-info\licenses\LICENSE.txt"; Destination = "pillow-heif-LICENSE.txt" },
    @{ Source = "pillow_heif-1.1.1.dist-info\licenses\LICENSES_bundled.txt"; Destination = "pillow-heif-bundled-LICENSES.txt" }
)
foreach ($license in $wheelLicenses) {
    $source = Join-Path $pythonSitePackages $license.Source
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
        throw "Required installed-wheel license is missing: $source"
    }
    Copy-Item -LiteralPath $source -Destination (Join-Path $licenseDestination $license.Destination)
}

$selfTestReport = Join-Path $buildRoot "portable-self-test.json"
$selfTestProcess = Start-Process `
    -FilePath (Join-Path $releaseRoot "Reforge-Pixels.exe") `
    -ArgumentList @("--self-test-report", $selfTestReport) `
    -PassThru `
    -WindowStyle Hidden
if (-not $selfTestProcess.WaitForExit(60000)) {
    $selfTestProcess.Kill()
    throw "Portable GPU self-test timed out"
}
if ($selfTestProcess.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $selfTestReport)) {
    throw "Portable GPU self-test failed"
}
$selfTest = Get-Content -LiteralPath $selfTestReport -Raw | ConvertFrom-Json
if (-not $selfTest.success) {
    throw "Portable GPU self-test reported failure: $($selfTest.error)"
}
Copy-Item -LiteralPath $selfTestReport -Destination (Join-Path $releaseRoot "PORTABLE_SELF_TEST.json")
$provenance = [ordered]@{
    commit = $sourceCommit
    tree = $sourceTree
    python = (& $python --version 2>&1).ToString().Trim()
    built_at_utc = [DateTime]::UtcNow.ToString("o")
}
$provenance | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $releaseRoot "BUILD_PROVENANCE.json") -Encoding utf8

$hashLines = Get-ChildItem -LiteralPath $releaseRoot -Recurse -File |
    Sort-Object FullName |
    ForEach-Object {
        $relative = [System.IO.Path]::GetRelativePath($releaseRoot, $_.FullName).Replace("\", "/")
        $hash = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        "$hash  $relative"
    }
[System.IO.File]::WriteAllLines((Join-Path $releaseRoot "SHA256SUMS.txt"), $hashLines)

& (Join-Path $projectRoot "scripts\verify_release_compliance.ps1") `
    -ReleaseDirectory $releaseRoot `
    -CorrespondingSourceDirectory $CorrespondingSourceDirectory
if ($LASTEXITCODE -ne 0) { throw "Portable release compliance verification failed" }

Compress-Archive -LiteralPath $releaseRoot -DestinationPath $releaseArchive -CompressionLevel Optimal
Compress-Archive -Path (Join-Path (Resolve-Path $CorrespondingSourceDirectory).Path "*") -DestinationPath $sourceArchive -CompressionLevel Optimal

Write-Output "Portable Windows directory created at: $releaseRoot"
Write-Output "Portable Windows archive created at: $releaseArchive"
Write-Output "Corresponding-source archive created at: $sourceArchive"
