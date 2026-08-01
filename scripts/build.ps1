[CmdletBinding()]
param(
    [string]$PythonExe = "python",
    [string]$OutputDir = "dist\houdini-package",
    [string]$HoudiniVersion = "22.0",
    [string]$HoudiniUserPrefDir = "",
    [switch]$Clean,
    [switch]$Install,
    [switch]$RotateToken,
    [switch]$SkipUserEnvironment
)

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Security
if (-not ("HocusPocus.NativeFileIdentity" -as [type])) {
    Add-Type -TypeDefinition @"
using System;
using System.ComponentModel;
using System.IO;
using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;
namespace HocusPocus {
    public static class NativeFileIdentity {
        [StructLayout(LayoutKind.Sequential)]
        private struct BY_HANDLE_FILE_INFORMATION {
            public uint FileAttributes;
            public System.Runtime.InteropServices.ComTypes.FILETIME CreationTime;
            public System.Runtime.InteropServices.ComTypes.FILETIME LastAccessTime;
            public System.Runtime.InteropServices.ComTypes.FILETIME LastWriteTime;
            public uint VolumeSerialNumber;
            public uint FileSizeHigh;
            public uint FileSizeLow;
            public uint NumberOfLinks;
            public uint FileIndexHigh;
            public uint FileIndexLow;
        }
        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        private static extern SafeFileHandle CreateFile(
            string name, uint access, FileShare share, IntPtr security,
            FileMode mode, uint flags, IntPtr template);
        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool GetFileInformationByHandle(
            SafeFileHandle handle, out BY_HANDLE_FILE_INFORMATION information);
        public static string Read(string path) {
            const uint BackupSemantics = 0x02000000;
            using (SafeFileHandle handle = CreateFile(
                path, 0, FileShare.ReadWrite | FileShare.Delete, IntPtr.Zero,
                FileMode.Open, BackupSemantics, IntPtr.Zero)) {
                if (handle.IsInvalid) {
                    throw new Win32Exception(Marshal.GetLastWin32Error());
                }
                BY_HANDLE_FILE_INFORMATION information;
                if (!GetFileInformationByHandle(handle, out information)) {
                    throw new Win32Exception(Marshal.GetLastWin32Error());
                }
                return String.Format(
                    "{0:x8}:{1:x8}{2:x8}:{3}",
                    information.VolumeSerialNumber,
                    information.FileIndexHigh,
                    information.FileIndexLow,
                    information.NumberOfLinks);
            }
        }
    }
}
"@
}
$repoRoot = [System.IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$resolvedOutputDir = [System.IO.Path]::GetFullPath(
    $(if ([System.IO.Path]::IsPathRooted($OutputDir)) {
        $OutputDir
    } else {
        Join-Path $repoRoot $OutputDir
    })
)
$stagingRoot = Join-Path $resolvedOutputDir "HocusPocus"
$packageFilePath = Join-Path $resolvedOutputDir "hocuspocus.json"
$ownerFile = Join-Path $resolvedOutputDir ".hocuspocus-build-root.json"
$outputJournal = Join-Path $resolvedOutputDir ".hocuspocus-output-transaction.json"
$script:manifestPins = @()
$script:manifestSources = @()

function Add-PinnedManifestSource {
    param([string]$Name, [string]$Path, [string]$RelativePath)
    $stream = [System.IO.File]::Open(
        $Path, [System.IO.FileMode]::Open,
        [System.IO.FileAccess]::Read, [System.IO.FileShare]::Read
    )
    $memory = New-Object System.IO.MemoryStream
    try {
        $stream.CopyTo($memory)
        $bytes = $memory.ToArray()
    } finally {
        $memory.Dispose()
    }
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        $digest = "sha256:" + (
            [BitConverter]::ToString($sha.ComputeHash($bytes))
        ).Replace("-", "").ToLowerInvariant()
    } finally {
        $sha.Dispose()
    }
    $script:manifestPins += $stream
    $script:manifestSources += @{
        name = $Name
        source = [Convert]::ToBase64String($bytes)
        digest = $digest
        relativePath = $RelativePath
    }
}

Add-PinnedManifestSource -Name "hs8_windows_manifest_cleanup" -Path (
    Join-Path $repoRoot "scripts\hs8_windows_manifest_cleanup.py"
) -RelativePath "scripts/hs8_windows_manifest_cleanup.py"
Add-PinnedManifestSource -Name "__main__" -Path (
    Join-Path $repoRoot "scripts\hs8_install_manifest.py"
) -RelativePath "scripts/hs8_install_manifest.py"

function Write-Step { param([string]$Message) Write-Host "==> $Message" }

function Ensure-Directory {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        New-Item -ItemType Directory -Path $Path | Out-Null
    }
}

function Test-IsAncestor {
    param([string]$Ancestor, [string]$Descendant)
    $prefix = $Ancestor.TrimEnd('\', '/') + [System.IO.Path]::DirectorySeparatorChar
    return $Descendant.StartsWith(
        $prefix, [System.StringComparison]::OrdinalIgnoreCase
    )
}

function Assert-NoReparseComponents {
    param([string]$Path)
    $fullPath = [System.IO.Path]::GetFullPath($Path)
    $root = [System.IO.Path]::GetPathRoot($fullPath)
    $current = $root
    $relative = $fullPath.Substring($root.Length)
    foreach ($component in @($relative -split '[\\/]' | Where-Object { $_ })) {
        $current = Join-Path $current $component
        if (-not (Test-Path -LiteralPath $current)) { continue }
        $item = Get-Item -LiteralPath $current -Force
        if ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) {
            throw "Owned path contains a reparse point component: $current"
        }
    }
}

function Assert-OwnedChild {
    param([string]$Parent, [string]$Path)
    $fullParent = [System.IO.Path]::GetFullPath($Parent)
    $fullPath = [System.IO.Path]::GetFullPath($Path)
    Assert-NoReparseComponents -Path $fullParent
    Assert-NoReparseComponents -Path $fullPath
    if (-not (Test-IsAncestor -Ancestor $fullParent -Descendant $fullPath)) {
        throw "Owned path escapes its canonical parent: $fullPath"
    }
}

function Assert-SafeOutputRoot {
    Assert-NoReparseComponents -Path $resolvedOutputDir
    $volumeRoot = [System.IO.Path]::GetPathRoot($resolvedOutputDir)
    if (
        $resolvedOutputDir -eq $volumeRoot -or
        $resolvedOutputDir -eq $repoRoot -or
        (Test-IsAncestor -Ancestor $resolvedOutputDir -Descendant $repoRoot)
    ) {
        throw "OutputDir is a protected filesystem or repository path: $resolvedOutputDir"
    }
    if (Test-Path -LiteralPath $resolvedOutputDir) {
        $item = Get-Item -LiteralPath $resolvedOutputDir -Force
        if ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) {
            throw "OutputDir cannot be a reparse point: $resolvedOutputDir"
        }
        if (Test-Path -LiteralPath $ownerFile) {
            $owner = Get-Content -LiteralPath $ownerFile -Raw | ConvertFrom-Json
            if ($owner.schemaVersion -ne 1 -or $owner.repositoryRoot -ne $repoRoot) {
                throw "OutputDir belongs to a different build owner."
            }
        } else {
            $entries = @(Get-ChildItem -LiteralPath $resolvedOutputDir -Force)
            $defaultRoot = [System.IO.Path]::GetFullPath(
                (Join-Path $repoRoot "dist\houdini-package")
            )
            $legacyNames = @(
                "HocusPocus", "hocuspocus.json", ".hocuspocus-build.lock"
            )
            $adoptableEntries = @(
                $entries |
                    Where-Object { $_.Name -ne ".hocuspocus-build.lock" }
            )
            if (
                $adoptableEntries.Count -gt 0 -and (
                    $resolvedOutputDir -ne $defaultRoot -or
                    @(
                        $adoptableEntries |
                            Where-Object { $_.Name -notin $legacyNames }
                    ).Count -gt 0
                )
            ) {
                throw "Refusing to adopt a nonempty unowned OutputDir."
            }
        }
    }
}

function Assert-SafePreferenceRoot {
    param([string]$Path)
    $fullPath = [System.IO.Path]::GetFullPath($Path)
    Assert-NoReparseComponents -Path $fullPath
    $volumeRoot = [System.IO.Path]::GetPathRoot($fullPath)
    if (
        $fullPath -eq $volumeRoot -or
        $fullPath -eq $repoRoot -or
        (Test-IsAncestor -Ancestor $fullPath -Descendant $repoRoot) -or
        (Test-IsAncestor -Ancestor $repoRoot -Descendant $fullPath) -or
        $fullPath -eq $resolvedOutputDir -or
        (Test-IsAncestor -Ancestor $fullPath -Descendant $resolvedOutputDir) -or
        (Test-IsAncestor -Ancestor $resolvedOutputDir -Descendant $fullPath)
    ) {
        throw "HoudiniUserPrefDir overlaps a protected path: $fullPath"
    }
}

function Assert-SafeAuthorityRoot {
    param([string]$Path, [string]$PreferenceRoot)
    $fullPath = [System.IO.Path]::GetFullPath($Path)
    $fullPreference = [System.IO.Path]::GetFullPath($PreferenceRoot)
    Assert-NoReparseComponents -Path $fullPath
    $volumeRoot = [System.IO.Path]::GetPathRoot($fullPath)
    foreach ($protected in @(
        $repoRoot, $resolvedOutputDir, $fullPreference
    )) {
        if (
            $fullPath -eq $protected -or
            (Test-IsAncestor -Ancestor $fullPath -Descendant $protected) -or
            (Test-IsAncestor -Ancestor $protected -Descendant $fullPath)
        ) {
            throw "Token authority root overlaps a protected path: $fullPath"
        }
    }
    if ($fullPath -eq $volumeRoot) {
        throw "Token authority root is a protected filesystem path."
    }
}

function Assert-NoReparseTree {
    param([string]$Path)
    $root = Get-Item -LiteralPath $Path -Force
    if ($root.Attributes -band [System.IO.FileAttributes]::ReparsePoint) {
        throw "Owned path cannot be a reparse point: $Path"
    }
    if (-not $root.PSIsContainer) { return }
    $queue = New-Object "System.Collections.Generic.Queue[System.IO.DirectoryInfo]"
    $queue.Enqueue([System.IO.DirectoryInfo]$root)
    $count = 0
    while ($queue.Count -gt 0) {
        $directory = $queue.Dequeue()
        foreach ($entry in $directory.EnumerateFileSystemInfos()) {
            $count += 1
            if ($count -gt 50000) {
                throw "Owned path contains too many entries for safe cleanup: $Path"
            }
            if ($entry.Attributes -band [System.IO.FileAttributes]::ReparsePoint) {
                throw "Owned path contains a reparse point: $($entry.FullName)"
            }
            if ($entry -is [System.IO.DirectoryInfo]) {
                $queue.Enqueue($entry)
            }
        }
    }
}

function Remove-OwnedPath {
    param([string]$Path, [string]$Parent)
    if (-not (Test-Path -LiteralPath $Path)) { return }
    $fullPath = [System.IO.Path]::GetFullPath($Path)
    $fullParent = [System.IO.Path]::GetFullPath($Parent)
    Assert-OwnedChild -Parent $fullParent -Path $fullPath
    Assert-NoReparseTree -Path $fullPath
    $item = Get-Item -LiteralPath $fullPath -Force
    if ($item.PSIsContainer) {
        Remove-Item -LiteralPath $fullPath -Recurse -Force
    } else {
        Remove-Item -LiteralPath $fullPath -Force
    }
}

function Remove-PythonBytecode {
    param([string]$Path)
    Assert-NoReparseComponents -Path $Path
    Assert-NoReparseTree -Path $Path
    $files = @(
        Get-ChildItem -LiteralPath $Path -Recurse -Force -File |
            Where-Object { $_.Extension -in @(".pyc", ".pyo") }
    )
    foreach ($file in $files) {
        Remove-OwnedPath -Path $file.FullName -Parent $Path
    }
    $directories = @(
        Get-ChildItem -LiteralPath $Path -Recurse -Force -Directory |
            Where-Object { $_.Name -eq "__pycache__" } |
            Sort-Object { $_.FullName.Length } -Descending
    )
    foreach ($directory in $directories) {
        if (Test-Path -LiteralPath $directory.FullName) {
            Remove-OwnedPath -Path $directory.FullName -Parent $Path
        }
    }
    $remaining = @(
        Get-ChildItem -LiteralPath $Path -Recurse -Force |
            Where-Object {
                $_.Name -eq "__pycache__" -or
                $_.Extension -in @(".pyc", ".pyo")
            }
    )
    if ($remaining.Count -ne 0) {
        throw "Python bytecode remained in the distributable candidate."
    }
}

function Write-OwnerFile {
    Assert-OwnedChild -Parent $resolvedOutputDir -Path $ownerFile
    $owner = [ordered]@{
        schemaVersion = 1
        repositoryRoot = $repoRoot
    } | ConvertTo-Json
    [System.IO.File]::WriteAllText(
        $ownerFile, $owner + [Environment]::NewLine,
        (New-Object System.Text.UTF8Encoding($false))
    )
}

function Copy-RepoPath {
    param([string]$RelativePath, [string]$DestinationRoot)
    $sourcePath = Join-Path $repoRoot $RelativePath
    if (-not (Test-Path -LiteralPath $sourcePath)) {
        throw "Source path not found: $sourcePath"
    }
    $destinationPath = Join-Path $DestinationRoot $RelativePath
    Ensure-Directory -Path (Split-Path -Parent $destinationPath)
    Copy-Item -LiteralPath $sourcePath -Destination $destinationPath -Recurse -Force
}

function Build-PackageJson {
    param(
        [string]$Path,
        [string]$RootName,
        [string]$ConfigDigest,
        [string]$ManifestDigest
    )
    $content = @"
{
  "env": [
    {
      "HOCUSPOCUS_ROOT": "`$HOUDINI_PACKAGE_PATH/$RootName"
    },
    {
      "PYTHONPATH": {
        "method": "prepend",
        "value": "`$HOCUSPOCUS_ROOT/python3.11libs"
      }
    },
    {
      "PYTHONDONTWRITEBYTECODE": "1"
    }
  ],
  "hpath": "`$HOCUSPOCUS_ROOT",
  "hocuspocus": {
    "schemaVersion": 1,
    "activeConfigDigest": "$ConfigDigest",
    "installManifestDigest": "$ManifestDigest"
  }
}
"@
    [System.IO.File]::WriteAllText(
        $Path, $content, (New-Object System.Text.UTF8Encoding($false))
    )
}

function Assert-PackageActivation {
    param(
        [string]$Path,
        [string]$RootName,
        [string]$ConfigDigest,
        [string]$ManifestDigest
    )
    $payload = Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
    $roots = @()
    foreach ($entry in @($payload.env)) {
        if ($entry.PSObject.Properties.Name -contains "HOCUSPOCUS_ROOT") {
            $roots += [string]$entry.HOCUSPOCUS_ROOT
        }
    }
    $expected = '$HOUDINI_PACKAGE_PATH/' + $RootName
    if ($roots.Count -ne 1 -or $roots[0] -cne $expected) {
        throw "Activated package pointer does not select $RootName."
    }
    $authority = $payload.hocuspocus
    Assert-ExactProperties -Value $authority -Label "package credential authority" `
        -Names @("schemaVersion", "activeConfigDigest", "installManifestDigest")
    if (
        $authority.schemaVersion -ne 1 -or
        [string]$authority.activeConfigDigest -cne $ConfigDigest -or
        [string]$authority.installManifestDigest -cne $ManifestDigest
    ) {
        throw "Activated package pointer has stale credential authority."
    }
    $bytecodePolicies = @()
    foreach ($entry in @($payload.env)) {
        if (
            $entry.PSObject.Properties.Name -contains
                "PYTHONDONTWRITEBYTECODE"
        ) {
            $bytecodePolicies += [string]$entry.PYTHONDONTWRITEBYTECODE
        }
    }
    if (
        $bytecodePolicies.Count -ne 1 -or
        $bytecodePolicies[0] -cne "1"
    ) {
        throw "Activated package pointer does not disable Python bytecode."
    }
    if (
        @($payload.env | Where-Object {
            $_.PSObject.Properties.Name -contains "PYTHONPYCACHEPREFIX"
        }).Count -ne 0
    ) {
        throw "Activated package pointer routes Python bytecode outside the payload."
    }
}

function New-StableToken {
    $bytes = New-Object byte[] 24
    $generator = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $generator.GetBytes($bytes) } finally { $generator.Dispose() }
    return [Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+', '-').Replace('/', '_')
}

function Get-Sha256Hex {
    param([string]$Path)
    $stream = [System.IO.File]::OpenRead($Path)
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        return ([BitConverter]::ToString($sha.ComputeHash($stream))).Replace("-", "").ToLowerInvariant()
    } finally {
        $sha.Dispose()
        $stream.Dispose()
    }
}

function Read-ConfiguredToken {
    param([string]$ConfigPath)
    if (-not (Test-Path -LiteralPath $ConfigPath)) { return "" }
    $content = Get-Content -LiteralPath $ConfigPath -Raw
    $match = [regex]::Match($content, '(?m)^token\s*=\s*"([A-Za-z0-9_-]{32,128})"\s*$')
    return $(if ($match.Success) { $match.Groups[1].Value } else { "" })
}

function Provision-InstallToken {
    param(
        [string]$ConfigPath,
        [string]$ExistingToken,
        [bool]$ForceRotation
    )
    $content = Get-Content -LiteralPath $ConfigPath -Raw
    $mode = [regex]::Match($content, '(?m)^token_mode\s*=\s*"([^"]*)"')
    if (-not $mode.Success) { throw "token_mode not found in $ConfigPath" }
    if ($mode.Groups[1].Value -eq "disabled") {
        return @{ TokenEnabled = $false; Token = "" }
    }
    $token = $(if (-not $ForceRotation -and $ExistingToken) {
        $ExistingToken
    } else {
        New-StableToken
    })
    if ([regex]::IsMatch($content, '(?m)^token\s*=')) {
        $content = [regex]::Replace(
            $content, '(?m)^token\s*=\s*"[^"]*"\s*$', "token = `"$token`""
        )
    } else {
        $content += [Environment]::NewLine + "token = `"$token`"" + [Environment]::NewLine
    }
    [System.IO.File]::WriteAllText(
        $ConfigPath, $content, (New-Object System.Text.UTF8Encoding($false))
    )
    return @{ TokenEnabled = $true; Token = $token }
}

function Invoke-Manifest {
    param(
        [string]$Root,
        [string]$Command = "create",
        [string[]]$Arguments = @()
    )
    $bootstrap = @'
import base64,json,sys,types
p=json.loads(sys.stdin.readline())
for row in p["modules"]:
    if row["name"] == "__main__":
        continue
    m=types.ModuleType(row["name"])
    m.__file__="<pinned:"+row["name"]+">"
    sys.modules[row["name"]]=m
    exec(compile(base64.b64decode(row["source"]),m.__file__,"exec"),m.__dict__)
main=next(row for row in p["modules"] if row["name"]=="__main__")
sys.argv=p["argv"]
g={"__name__":"__main__","__file__":"<pinned:hs8_install_manifest>"}
exec(compile(base64.b64decode(main["source"]),g["__file__"],"exec"),g)
'@
    $encoded = [Convert]::ToBase64String(
        [Text.Encoding]::UTF8.GetBytes($bootstrap)
    )
    $start = New-Object System.Diagnostics.ProcessStartInfo
    $start.FileName = $PythonExe
    $start.Arguments = (
        '-I -S -c "import base64;exec(base64.b64decode(''' +
        $encoded + '''))"'
    )
    $start.UseShellExecute = $false
    $start.RedirectStandardInput = $true
    $start.RedirectStandardOutput = $true
    $start.RedirectStandardError = $true
    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $start
    if (-not $process.Start()) { throw "Manifest helper could not start." }
    $stdout = $process.StandardOutput.ReadToEndAsync()
    $stderr = $process.StandardError.ReadToEndAsync()
    $payload = @{
        argv = @("hs8_install_manifest.py", $Command, "--root", $Root) +
            $Arguments
        modules = $script:manifestSources
    } | ConvertTo-Json -Compress -Depth 6
    $process.StandardInput.WriteLine($payload)
    $process.StandardInput.Close()
    $process.WaitForExit()
    $output = $stdout.Result
    $errors = $stderr.Result
    $exitCode = $process.ExitCode
    $process.Dispose()
    if ($output.Length -gt 16777216 -or $errors.Length -gt 65536) {
        throw "Manifest helper output exceeds its bound."
    }
    if ($exitCode -ne 0) {
        throw "Install manifest $Command failed: $errors"
    }
    $result = $output | ConvertFrom-Json
    if ($Command -ceq "create") {
        foreach ($source in $script:manifestSources) {
            $rows = @($result.files | Where-Object {
                [string]$_.relativePath -ceq [string]$source.relativePath
            })
            if (
                $rows.Count -ne 1 -or
                [string]$rows[0].contentDigest -cne [string]$source.digest
            ) {
                throw "Pinned manifest helper identity differs from the governed tree."
            }
        }
    }
    return $result
}

try {
    . (Join-Path $PSScriptRoot "build_transaction.ps1")
    Invoke-BuildTransaction
} finally {
    foreach ($pin in $script:manifestPins) { $pin.Dispose() }
}

Write-Host ""
Write-Host "Staged package: $stagingRoot"
if ($Install) { Write-Host "Installed package manifest: $activePackage" }
