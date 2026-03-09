[CmdletBinding()]
param(
    [string]$PythonExe = "python",
    [string]$OutputDir = "dist\houdini-package",
    [string]$HoudiniVersion = "21.0",
    [string]$HoudiniUserPrefDir = "",
    [switch]$Clean,
    [switch]$Install
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$resolvedOutputDir = if ([System.IO.Path]::IsPathRooted($OutputDir)) {
    $OutputDir
} else {
    Join-Path $repoRoot $OutputDir
}

$stagingRoot = Join-Path $resolvedOutputDir "HocusPocus"
$packageFilePath = Join-Path $resolvedOutputDir "hocuspocus.json"

function Write-Step {
    param([string]$Message)
    Write-Host "==> $Message"
}

function Ensure-Directory {
    param([string]$Path)
    if (-not (Test-Path $Path)) {
        New-Item -ItemType Directory -Path $Path | Out-Null
    }
}

function Copy-RepoPath {
    param(
        [string]$RelativePath,
        [string]$DestinationRoot
    )

    $sourcePath = Join-Path $repoRoot $RelativePath
    if (-not (Test-Path $sourcePath)) {
        throw "Source path not found: $sourcePath"
    }

    $destinationPath = Join-Path $DestinationRoot $RelativePath
    $destinationParent = Split-Path -Parent $destinationPath
    Ensure-Directory -Path $destinationParent
    Copy-Item -Path $sourcePath -Destination $destinationPath -Recurse -Force
}

function Build-PackageJson {
    param([string]$Path)

    $content = @'
{
  "env": [
    {
      "HOCUSPOCUS_ROOT": "$HOUDINI_PACKAGE_PATH/HocusPocus"
    },
    {
      "PYTHONPATH": {
        "method": "prepend",
        "value": "$HOCUSPOCUS_ROOT/python3.11libs"
      }
    }
  ],
  "hpath": "$HOCUSPOCUS_ROOT"
}
'@

    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, $content, $utf8NoBom)
}

if ($Clean -and (Test-Path $resolvedOutputDir)) {
    Write-Step "Cleaning existing output at $resolvedOutputDir"
    Remove-Item -Recurse -Force $resolvedOutputDir
}

Ensure-Directory -Path $resolvedOutputDir
Ensure-Directory -Path $stagingRoot

Write-Step "Staging Houdini package into $resolvedOutputDir"
foreach ($relativePath in @(
    "config",
    "python3.11libs",
    "scripts",
    "toolbar",
    "package"
)) {
    Copy-RepoPath -RelativePath $relativePath -DestinationRoot $stagingRoot
}

Build-PackageJson -Path $packageFilePath

$compileTarget = Join-Path $stagingRoot "python3.11libs"
Write-Step "Compiling Python modules with $PythonExe"
& $PythonExe -m compileall $compileTarget
if ($LASTEXITCODE -ne 0) {
    throw "compileall failed with exit code $LASTEXITCODE"
}

if ($Install) {
    $prefDir = $HoudiniUserPrefDir
    if (-not $prefDir) {
        $prefDir = Join-Path ([Environment]::GetFolderPath("MyDocuments")) ("houdini" + $HoudiniVersion)
    }

    $packagesDir = Join-Path $prefDir "packages"
    Ensure-Directory -Path $packagesDir

    Write-Step "Installing package into $packagesDir"
    $installedPluginDir = Join-Path $packagesDir "HocusPocus"
    if (Test-Path $installedPluginDir) {
        Remove-Item -Recurse -Force $installedPluginDir
    }

    Copy-Item -Path $stagingRoot -Destination $installedPluginDir -Recurse -Force
    Copy-Item -Path $packageFilePath -Destination (Join-Path $packagesDir "hocuspocus.json") -Force

    Write-Host ""
    Write-Host "Installed to:"
    Write-Host "  $installedPluginDir"
    Write-Host "Package file:"
    Write-Host "  $(Join-Path $packagesDir 'hocuspocus.json')"
} else {
    Write-Host ""
    Write-Host "Staged package:"
    Write-Host "  $stagingRoot"
    Write-Host "Package file:"
    Write-Host "  $packageFilePath"
}
