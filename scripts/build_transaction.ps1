# Private manifest-identity transactions for build.ps1.

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

function Get-Sha256Bytes {
    param([byte[]]$Value)
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        return ([BitConverter]::ToString(
            $sha.ComputeHash($Value)
        )).Replace("-", "").ToLowerInvariant()
    } finally {
        $sha.Dispose()
    }
}

function Get-Sha256Text {
    param([string]$Value)
    return Get-Sha256Bytes -Value ([Text.Encoding]::UTF8.GetBytes($Value))
}

function Test-StableToken {
    param([string]$Token)
    return $Token -cmatch '^[A-Za-z0-9_-]{32,128}$'
}

function Get-PathIdentity {
    param([string]$Path)
    $full = [System.IO.Path]::GetFullPath($Path)
    if (-not (Test-Path -LiteralPath $full)) {
        throw "Identity path is absent."
    }
    if ([Environment]::OSVersion.Platform -eq [PlatformID]::Win32NT) {
        return [HocusPocus.NativeFileIdentity]::Read($full)
    }
    $item = Get-Item -LiteralPath $full -Force
    return "$($item.CreationTimeUtc.Ticks):$($item.Length):$full"
}

function Get-FileSnapshot {
    param([string]$Path, [int64]$MaximumBytes = 65536)
    $full = [System.IO.Path]::GetFullPath($Path)
    if (-not (Test-Path -LiteralPath $full)) {
        return [pscustomobject]@{
            Exists = $false
            Identity = ""
            Digest = ""
            Bytes = ""
        }
    }
    Assert-NoReparseComponents -Path $full
    $item = Get-Item -LiteralPath $full -Force
    if ($item.PSIsContainer -or $item.Length -gt $MaximumBytes) {
        throw "Authority file is not a bounded regular file."
    }
    $bytes = [System.IO.File]::ReadAllBytes($full)
    return [pscustomobject]@{
        Exists = $true
        Identity = Get-PathIdentity -Path $full
        Digest = Get-Sha256Bytes -Value $bytes
        Bytes = [Convert]::ToBase64String($bytes)
    }
}

function Assert-ExactProperties {
    param($Value, [string[]]$Names, [string]$Label)
    if ($null -eq $Value) { throw "Invalid $Label." }
    $actual = @($Value.PSObject.Properties.Name | Sort-Object)
    $expected = @($Names | Sort-Object)
    if (
        $actual.Count -ne $expected.Count -or
        (Compare-Object -CaseSensitive $actual $expected)
    ) {
        throw "Invalid $Label fields."
    }
}

function ConvertTo-FileSnapshot {
    param($Value)
    Assert-ExactProperties -Value $Value `
        -Names @("Exists", "Identity", "Digest", "Bytes") `
        -Label "authority-file snapshot"
    if (
        $null -eq $Value -or
        [bool]$Value.Exists -and (
            [string]$Value.Identity -notmatch '^[A-Za-z0-9:._\\/-]{1,1024}$' -or
            [string]$Value.Digest -notmatch '^[0-9a-f]{64}$' -or
            [string]$Value.Bytes -notmatch '^[A-Za-z0-9+/]*={0,2}$'
        )
    ) {
        throw "Invalid authority-file snapshot."
    }
    return [pscustomobject]@{
        Exists = [bool]$Value.Exists
        Identity = [string]$Value.Identity
        Digest = [string]$Value.Digest
        Bytes = [string]$Value.Bytes
    }
}

function Test-FileSnapshot {
    param([string]$Path, $Expected, [int64]$MaximumBytes = 65536)
    $expectedSnapshot = ConvertTo-FileSnapshot -Value $Expected
    try {
        $actual = Get-FileSnapshot -Path $Path -MaximumBytes $MaximumBytes
    } catch {
        return $false
    }
    return (
        $actual.Exists -eq $expectedSnapshot.Exists -and
        $actual.Identity -ceq $expectedSnapshot.Identity -and
        $actual.Digest -ceq $expectedSnapshot.Digest -and
        $actual.Bytes -ceq $expectedSnapshot.Bytes
    )
}

function Assert-FileSnapshot {
    param(
        [string]$Path,
        $Expected,
        [string]$Label,
        [int64]$MaximumBytes = 65536
    )
    if (-not (
        Test-FileSnapshot `
            -Path $Path -Expected $Expected -MaximumBytes $MaximumBytes
    )) {
        throw "$Label changed outside its transaction authority."
    }
}

function Replace-FileAtomically {
    param([string]$Candidate, [string]$Active, [string]$Backup)
    if (-not (Test-Path -LiteralPath $Active)) {
        [System.IO.File]::Move($Candidate, $Active)
        return
    }
    $ephemeral = $(if ($Backup) {
        $Backup
    } else {
        $Active + ".replace." + [guid]::NewGuid().ToString("N")
    })
    [System.IO.File]::Replace($Candidate, $Active, $ephemeral, $true)
    if (-not $Backup -and (Test-Path -LiteralPath $ephemeral)) {
        [System.IO.File]::Delete($ephemeral)
    }
}

function New-PackagePointerCandidate {
    param([string]$Path, [string]$RootName, [string]$Parent)
    Assert-OwnedChild -Parent $Parent -Path $Path
    Build-PackageJson -Path $Path -RootName $RootName
    return Get-FileSnapshot -Path $Path
}

function Publish-PackageCandidate {
    param(
        [string]$Path,
        [string]$Candidate,
        [string]$Backup,
        [string]$Parent,
        $Before,
        $After,
        [string]$RootName
    )
    Assert-OwnedChild -Parent $Parent -Path $Path
    Assert-OwnedChild -Parent $Parent -Path $Candidate
    if ($Backup) { Assert-OwnedChild -Parent $Parent -Path $Backup }
    if (Test-FileSnapshot -Path $Path -Expected $After) {
        Assert-PackageActivation -Path $Path -RootName $RootName
        return
    }
    Assert-FileSnapshot -Path $Candidate -Expected $After `
        -Label "Package pointer candidate"
    Assert-FileSnapshot -Path $Path -Expected $Before `
        -Label "Package pointer"
    if ([bool]$Before.Exists) {
        if (-not $Backup) { throw "Package pointer backup authority is absent." }
        if (Test-Path -LiteralPath $Backup) {
            throw "Package pointer backup path is already occupied."
        }
        [System.IO.File]::Replace($Candidate, $Path, $Backup, $true)
        Assert-FileSnapshot -Path $Backup -Expected $Before `
            -Label "Package pointer backup"
    } else {
        [System.IO.File]::Move($Candidate, $Path)
    }
    Assert-FileSnapshot -Path $Path -Expected $After `
        -Label "Published package pointer"
    Assert-PackageActivation -Path $Path -RootName $RootName
}

function Remove-PackagePointerBackup {
    param([string]$Path, [string]$Parent, $Expected)
    if (-not $Path -or -not (Test-Path -LiteralPath $Path)) { return }
    Assert-FileSnapshot -Path $Path -Expected $Expected `
        -Label "Package pointer backup"
    Remove-OwnedPath -Path $Path -Parent $Parent
}

function Invoke-BestEffortCleanup {
    param(
        [scriptblock]$Action,
        [string]$Label,
        [ValidateSet("committed", "primary-failure", "rollback-failure")]
        [string]$Classification = "committed"
    )
    try {
        & $Action
        return $true
    } catch {
        Write-Warning "HocusPocus $Classification cleanup deferred: $Label."
        return $false
    }
}

function Write-JsonJournal {
    param([string]$Path, [System.Collections.IDictionary]$State)
    $candidate = $Path + ".candidate." + [guid]::NewGuid().ToString("N")
    [System.IO.File]::WriteAllText(
        $candidate,
        ($State | ConvertTo-Json -Compress -Depth 12) +
            [Environment]::NewLine,
        (New-Object System.Text.UTF8Encoding($false))
    )
    Replace-FileAtomically -Candidate $candidate -Active $Path -Backup $null
}

function Get-VerifiedManifestDigest {
    param([string]$Path, [switch]$AllowAbsent)
    if (-not (Test-Path -LiteralPath $Path)) {
        if ($AllowAbsent) { return "" }
        throw "Manifest tree is absent."
    }
    Assert-NoReparseTree -Path $Path
    $manifest = Invoke-Manifest -Root $Path -Command "verify"
    $digest = [string]$manifest.manifestDigest
    if ($digest -notmatch '^sha256:[0-9a-f]{64}$') {
        throw "Manifest identity is invalid."
    }
    return $digest
}

function Assert-ManifestDigest {
    param([string]$Path, [string]$Expected, [string]$Label)
    if ((Get-VerifiedManifestDigest -Path $Path) -cne $Expected) {
        throw "$Label manifest identity changed."
    }
}

function Complete-OutputTransaction {
    param(
        [string]$JournalPath,
        [string]$OutputRoot,
        [string]$ActiveTree,
        [string]$ActivePointer,
        [System.Collections.IDictionary]$State
    )
    $candidate = Join-Path $OutputRoot ([string]$State.candidateName)
    $previous = $(if ($State.previousName) {
        Join-Path $OutputRoot ([string]$State.previousName)
    } else { $null })
    $pointerCandidate = Join-Path $OutputRoot (
        [string]$State.pointerCandidateName
    )
    $pointerBackup = $(if ($State.pointerBackupName) {
        Join-Path $OutputRoot ([string]$State.pointerBackupName)
    } else { $null })
    $activeDigest = Get-VerifiedManifestDigest -Path $ActiveTree -AllowAbsent
    $candidateDigest = Get-VerifiedManifestDigest -Path $candidate -AllowAbsent
    $previousDigest = $(if ($previous) {
        Get-VerifiedManifestDigest -Path $previous -AllowAbsent
    } else { "" })

    if ($activeDigest -cne [string]$State.candidateManifestDigest) {
        if ($candidateDigest -cne [string]$State.candidateManifestDigest) {
            throw "Recoverable output candidate identity is absent."
        }
        if ($activeDigest) {
            if (
                -not $previous -or $previousDigest -or
                $activeDigest -cne [string]$State.previousManifestDigest
            ) {
                throw "Output tree identities cannot be reconciled safely."
            }
            Move-Item -LiteralPath $ActiveTree -Destination $previous
            $previousDigest = Get-VerifiedManifestDigest -Path $previous
        } elseif (
            [string]$State.previousManifestDigest -and
            $previousDigest -cne [string]$State.previousManifestDigest
        ) {
            throw "Last known-good output tree is absent."
        }
        Move-Item -LiteralPath $candidate -Destination $ActiveTree
    }
    Assert-ManifestDigest -Path $ActiveTree `
        -Expected ([string]$State.candidateManifestDigest) `
        -Label "Active output"
    Publish-PackageCandidate `
        -Path $ActivePointer -Candidate $pointerCandidate `
        -Backup $pointerBackup -Parent $OutputRoot `
        -Before $State.pointerBefore -After $State.pointerAfter `
        -RootName "HocusPocus"
    $State.phase = "committed"
    Write-JsonJournal -Path $JournalPath -State $State

    $clean = $true
    if (Test-Path -LiteralPath $candidate) {
        $clean = (Invoke-BestEffortCleanup -Label "redundant output candidate" -Action {
            Assert-ManifestDigest -Path $candidate `
                -Expected ([string]$State.candidateManifestDigest) `
                -Label "Output candidate"
            Remove-OwnedPath -Path $candidate -Parent $OutputRoot
        }) -and $clean
    }
    if ($previous -and (Test-Path -LiteralPath $previous)) {
        $clean = (Invoke-BestEffortCleanup -Label "previous output tree" -Action {
            Assert-ManifestDigest -Path $previous `
                -Expected ([string]$State.previousManifestDigest) `
                -Label "Previous output"
            Remove-OwnedPath -Path $previous -Parent $OutputRoot
        }) -and $clean
    }
    if ($pointerBackup -and (Test-Path -LiteralPath $pointerBackup)) {
        $clean = (Invoke-BestEffortCleanup -Label "output pointer backup" -Action {
            Remove-PackagePointerBackup `
                -Path $pointerBackup -Parent $OutputRoot `
                -Expected $State.pointerBefore
        }) -and $clean
    }
    if (Test-Path -LiteralPath $pointerCandidate) {
        $clean = (Invoke-BestEffortCleanup -Label "output pointer candidate" -Action {
            Assert-FileSnapshot -Path $pointerCandidate `
                -Expected $State.pointerAfter -Label "Pointer candidate"
            Remove-OwnedPath -Path $pointerCandidate -Parent $OutputRoot
        }) -and $clean
    }
    if ($clean) {
        Invoke-BestEffortCleanup -Label "output transaction journal" -Action {
            Remove-OwnedPath -Path $JournalPath -Parent $OutputRoot
        } | Out-Null
    }
}

function Recover-OutputTransaction {
    param(
        [string]$JournalPath,
        [string]$OutputRoot,
        [string]$ActiveTree,
        [string]$ActivePointer
    )
    if (-not (Test-Path -LiteralPath $JournalPath)) { return }
    try {
        if ((Get-Item -LiteralPath $JournalPath).Length -gt 65536) {
            throw "oversized output journal"
        }
        $raw = Get-Content -LiteralPath $JournalPath -Raw | ConvertFrom-Json
        Assert-ExactProperties -Value $raw -Label "output journal" -Names @(
            "schemaVersion", "desired", "phase",
            "candidateName", "candidateManifestDigest",
            "previousName", "previousManifestDigest",
            "pointerCandidateName", "pointerBackupName",
            "pointerBefore", "pointerAfter"
        )
        if (
            $raw.schemaVersion -ne 2 -or
            [string]$raw.desired -cne "commit" -or
            $raw.phase -notin @("prepared", "committed") -or
            [string]$raw.candidateName -cnotmatch
                '^\.HocusPocus\.candidate\.[0-9a-f]{32}$' -or
            [string]$raw.previousName -cnotmatch
                '^(\.HocusPocus\.previous\.[0-9a-f]{32})?$' -or
            [string]$raw.pointerCandidateName -cnotmatch
                '^hocuspocus\.json\.candidate\.[0-9a-f]{32}$' -or
            [string]$raw.pointerBackupName -cnotmatch
                '^(hocuspocus\.json\.backup\.[0-9a-f]{32})?$' -or
            [string]$raw.candidateManifestDigest -notmatch
                '^sha256:[0-9a-f]{64}$' -or
            [string]$raw.previousManifestDigest -notmatch
                '^(sha256:[0-9a-f]{64})?$'
        ) {
            throw "invalid output journal"
        }
        $state = [ordered]@{
            schemaVersion = 2
            desired = "commit"
            phase = [string]$raw.phase
            candidateName = [string]$raw.candidateName
            candidateManifestDigest = [string]$raw.candidateManifestDigest
            previousName = [string]$raw.previousName
            previousManifestDigest = [string]$raw.previousManifestDigest
            pointerCandidateName = [string]$raw.pointerCandidateName
            pointerBackupName = [string]$raw.pointerBackupName
            pointerBefore = ConvertTo-FileSnapshot -Value $raw.pointerBefore
            pointerAfter = ConvertTo-FileSnapshot -Value $raw.pointerAfter
        }
        Complete-OutputTransaction `
            -JournalPath $JournalPath -OutputRoot $OutputRoot `
            -ActiveTree $ActiveTree -ActivePointer $ActivePointer `
            -State $state
    } catch {
        throw "Unfinished staged publication requires manifest-identity recovery."
    }
}

function Protect-AuthorityEnvelope {
    param([System.Collections.IDictionary]$Envelope)
    $plain = [Text.Encoding]::UTF8.GetBytes(
        ($Envelope | ConvertTo-Json -Compress -Depth 12)
    )
    $protected = [System.Security.Cryptography.ProtectedData]::Protect(
        $plain,
        [Text.Encoding]::UTF8.GetBytes("HocusPocus.install.journal.v2"),
        [System.Security.Cryptography.DataProtectionScope]::CurrentUser
    )
    return [Convert]::ToBase64String($protected)
}

function Unprotect-AuthorityEnvelope {
    param([string]$ProtectedEnvelope)
    $protected = [Convert]::FromBase64String($ProtectedEnvelope)
    $plain = [System.Security.Cryptography.ProtectedData]::Unprotect(
        $protected,
        [Text.Encoding]::UTF8.GetBytes("HocusPocus.install.journal.v2"),
        [System.Security.Cryptography.DataProtectionScope]::CurrentUser
    )
    return [Text.Encoding]::UTF8.GetString($plain) | ConvertFrom-Json
}

function Write-TokenJournal {
    param(
        [string]$Path,
        [string]$AuthorityRoot,
        [System.Collections.IDictionary]$Envelope
    )
    $candidate = $Path + ".candidate." + [guid]::NewGuid().ToString("N")
    $outer = [ordered]@{
        schemaVersion = 2
        protectedEnvelope = Protect-AuthorityEnvelope -Envelope $Envelope
    }
    [System.IO.File]::WriteAllText(
        $candidate,
        ($outer | ConvertTo-Json -Compress) + [Environment]::NewLine,
        (New-Object System.Text.UTF8Encoding($false))
    )
    Assert-OwnedChild -Parent $AuthorityRoot -Path $candidate
    Replace-FileAtomically -Candidate $candidate -Active $Path -Backup $null
}

function Read-TokenJournal {
    param([string]$Path)
    if ((Get-Item -LiteralPath $Path).Length -gt 65536) {
        throw "oversized token journal"
    }
    $outer = Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
    Assert-ExactProperties -Value $outer `
        -Names @("schemaVersion", "protectedEnvelope") `
        -Label "protected token journal"
    if (
        $outer.schemaVersion -ne 2 -or
        [string]$outer.protectedEnvelope -notmatch '^[A-Za-z0-9+/]+={0,2}$'
    ) {
        throw "invalid protected token journal"
    }
    return Unprotect-AuthorityEnvelope `
        -ProtectedEnvelope ([string]$outer.protectedEnvelope)
}

function Get-UserToken {
    param([string]$AuthorityRoot)
    if ($env:HOCUSPOCUS_BUILD_USER_TOKEN_FILE) {
        $path = [System.IO.Path]::GetFullPath(
            $env:HOCUSPOCUS_BUILD_USER_TOKEN_FILE
        )
        Assert-OwnedChild -Parent $AuthorityRoot -Path $path
        if (-not (Test-Path -LiteralPath $path)) { return "" }
        return [System.IO.File]::ReadAllText($path).Trim()
    }
    return [string][Environment]::GetEnvironmentVariable(
        "HOCUSPOCUS_TOKEN", "User"
    )
}

function Set-UserToken {
    param([string]$AuthorityRoot, [string]$Token)
    if ($env:HOCUSPOCUS_BUILD_USER_TOKEN_FILE) {
        $path = [System.IO.Path]::GetFullPath(
            $env:HOCUSPOCUS_BUILD_USER_TOKEN_FILE
        )
        Assert-OwnedChild -Parent $AuthorityRoot -Path $path
        if (-not $Token) {
            if (Test-Path -LiteralPath $path) {
                Remove-OwnedPath -Path $path -Parent $AuthorityRoot
            }
            if (Test-Path -LiteralPath $path) {
                throw "Persisted HocusPocus token removal failed."
            }
            return
        }
        $candidate = $path + ".candidate." + [guid]::NewGuid().ToString("N")
        [System.IO.File]::WriteAllText(
            $candidate, $Token, (New-Object System.Text.UTF8Encoding($false))
        )
        Replace-FileAtomically -Candidate $candidate -Active $path -Backup $null
        if ([System.IO.File]::ReadAllText($path) -cne $Token) {
            throw "Persisted HocusPocus token verification failed."
        }
        return
    }
    [Environment]::SetEnvironmentVariable(
        "HOCUSPOCUS_TOKEN", $(if ($Token) { $Token } else { $null }), "User"
    )
    if (
        [string][Environment]::GetEnvironmentVariable(
            "HOCUSPOCUS_TOKEN", "User"
        ) -cne $Token
    ) {
        throw "Persisted HocusPocus token verification failed."
    }
}

function ConvertTo-TokenEnvelope {
    param($Raw)
    Assert-ExactProperties -Value $Raw -Label "token authority envelope" `
        -Names @(
            "schemaVersion", "desired", "phase",
            "authorityRoot", "authorityRootIdentity",
            "packagesDir", "packagesDirIdentity",
            "versionName", "manifestDigest",
            "pointerCandidateName", "pointerBackupName",
            "pointerBefore", "pointerAfter",
            "tokenEnabled", "publishUserToken",
            "oldToken", "oldTokenDigest", "newToken", "newTokenDigest"
        )
    if (
        $Raw.schemaVersion -ne 2 -or
        [string]$Raw.desired -cne "commit" -or
        $Raw.phase -notin @(
            "prepared", "pointer_published",
            "environment_published", "committed"
        ) -or
        [string]$Raw.authorityRoot -ne
            [System.IO.Path]::GetFullPath([string]$Raw.authorityRoot) -or
        [string]$Raw.packagesDir -ne
            [System.IO.Path]::GetFullPath([string]$Raw.packagesDir) -or
        [string]$Raw.versionName -cnotmatch
            '^HocusPocus\.[0-9a-f]{12}\.[0-9a-f]{8}$' -or
        [string]$Raw.manifestDigest -notmatch '^sha256:[0-9a-f]{64}$' -or
        [string]$Raw.pointerCandidateName -cnotmatch
            '^\.hocuspocus\.json\.candidate\.[0-9a-f]{32}$' -or
        [string]$Raw.pointerBackupName -cnotmatch
            '^(\.hocuspocus\.json\.backup\.[0-9a-f]{32})?$' -or
        -not [string]$Raw.authorityRootIdentity -or
        -not [string]$Raw.packagesDirIdentity -or
        -not (
            (-not [bool]$Raw.tokenEnabled -and -not [string]$Raw.newToken) -or
            (
                [bool]$Raw.tokenEnabled -and
                (Test-StableToken -Token ([string]$Raw.newToken))
            )
        ) -or
        (
            [string]$Raw.oldToken -and
            -not (Test-StableToken -Token ([string]$Raw.oldToken))
        ) -or
        [string]$Raw.oldTokenDigest -cne
            (Get-Sha256Text -Value ([string]$Raw.oldToken)) -or
        [string]$Raw.newTokenDigest -cne
            (Get-Sha256Text -Value ([string]$Raw.newToken))
    ) {
        throw "invalid token authority envelope"
    }
    return [ordered]@{
        schemaVersion = 2
        desired = "commit"
        phase = [string]$Raw.phase
        authorityRoot = [string]$Raw.authorityRoot
        authorityRootIdentity = [string]$Raw.authorityRootIdentity
        packagesDir = [string]$Raw.packagesDir
        packagesDirIdentity = [string]$Raw.packagesDirIdentity
        versionName = [string]$Raw.versionName
        manifestDigest = [string]$Raw.manifestDigest
        pointerCandidateName = [string]$Raw.pointerCandidateName
        pointerBackupName = [string]$Raw.pointerBackupName
        pointerBefore = ConvertTo-FileSnapshot -Value $Raw.pointerBefore
        pointerAfter = ConvertTo-FileSnapshot -Value $Raw.pointerAfter
        tokenEnabled = [bool]$Raw.tokenEnabled
        publishUserToken = [bool]$Raw.publishUserToken
        oldToken = [string]$Raw.oldToken
        oldTokenDigest = [string]$Raw.oldTokenDigest
        newToken = [string]$Raw.newToken
        newTokenDigest = [string]$Raw.newTokenDigest
    }
}

function Complete-TokenTransaction {
    param(
        [string]$Path,
        [string]$AuthorityRoot,
        [System.Collections.IDictionary]$Envelope
    )
    $packagesDir = [string]$Envelope.packagesDir
    $pointer = Join-Path $packagesDir "hocuspocus.json"
    $pointerCandidate = Join-Path $packagesDir (
        [string]$Envelope.pointerCandidateName
    )
    $pointerBackup = $(if ($Envelope.pointerBackupName) {
        Join-Path $packagesDir ([string]$Envelope.pointerBackupName)
    } else { $null })
    $versionPath = Join-Path $packagesDir ([string]$Envelope.versionName)
    if (
        (Get-PathIdentity -Path $AuthorityRoot) -cne
            [string]$Envelope.authorityRootIdentity -or
        (Get-PathIdentity -Path $packagesDir) -cne
            [string]$Envelope.packagesDirIdentity
    ) {
        throw "Token journal authority root identity changed."
    }
    Assert-ManifestDigest -Path $versionPath `
        -Expected ([string]$Envelope.manifestDigest) `
        -Label "Installed version"
    if ((Read-ConfiguredToken -ConfigPath (
        Join-Path $versionPath "config\default.toml"
    )) -cne [string]$Envelope.newToken) {
        throw "Installed version token changed."
    }
    Publish-PackageCandidate `
        -Path $pointer -Candidate $pointerCandidate `
        -Backup $pointerBackup -Parent $packagesDir `
        -Before $Envelope.pointerBefore -After $Envelope.pointerAfter `
        -RootName ([string]$Envelope.versionName)
    $Envelope.phase = "pointer_published"
    Write-TokenJournal -Path $Path -AuthorityRoot $AuthorityRoot `
        -Envelope $Envelope
    if ([bool]$Envelope.publishUserToken) {
        Set-UserToken -AuthorityRoot $AuthorityRoot `
            -Token ([string]$Envelope.newToken)
        $env:HOCUSPOCUS_TOKEN = [string]$Envelope.newToken
    }
    $Envelope.phase = "environment_published"
    Write-TokenJournal -Path $Path -AuthorityRoot $AuthorityRoot `
        -Envelope $Envelope
    $Envelope.phase = "committed"
    Write-TokenJournal -Path $Path -AuthorityRoot $AuthorityRoot `
        -Envelope $Envelope

    $clean = $true
    if ($pointerBackup -and (Test-Path -LiteralPath $pointerBackup)) {
        $clean = (Invoke-BestEffortCleanup -Label "install pointer backup" -Action {
            Remove-PackagePointerBackup `
                -Path $pointerBackup -Parent $packagesDir `
                -Expected $Envelope.pointerBefore
        }) -and $clean
    }
    if (Test-Path -LiteralPath $pointerCandidate) {
        $clean = (Invoke-BestEffortCleanup -Label "install pointer candidate" -Action {
            Assert-FileSnapshot -Path $pointerCandidate `
                -Expected $Envelope.pointerAfter -Label "Pointer candidate"
            Remove-OwnedPath -Path $pointerCandidate -Parent $packagesDir
        }) -and $clean
    }
    if ($clean) {
        Invoke-BestEffortCleanup -Label "token activation journal" -Action {
            Remove-OwnedPath -Path $Path -Parent $AuthorityRoot
        } | Out-Null
    }
}

function Recover-TokenTransaction {
    param([string]$Path, [string]$AuthorityRoot)
    if (-not (Test-Path -LiteralPath $Path)) { return }
    $preferenceLock = $null
    try {
        $envelope = ConvertTo-TokenEnvelope -Raw (
            Read-TokenJournal -Path $Path
        )
        if (
            [string]$envelope.authorityRoot -cne
                [System.IO.Path]::GetFullPath($AuthorityRoot) -or
            (Get-PathIdentity -Path $AuthorityRoot) -cne
                [string]$envelope.authorityRootIdentity
        ) {
            throw "Token journal does not belong to this authority root."
        }
        Assert-NoReparseComponents -Path ([string]$envelope.packagesDir)
        $preferenceLock = Enter-PathLock `
            -Parent ([string]$envelope.packagesDir) `
            -Name ".hocuspocus-install.lock"
        Complete-TokenTransaction `
            -Path $Path -AuthorityRoot $AuthorityRoot -Envelope $envelope
    } catch {
        throw "Unfinished HocusPocus token activation requires recovery."
    } finally {
        if ($preferenceLock) { $preferenceLock.Dispose() }
    }
}

function Enter-PathLock {
    param([string]$Parent, [string]$Name)
    $path = Join-Path $Parent $Name
    Assert-OwnedChild -Parent $Parent -Path $path
    $deadline = [DateTime]::UtcNow.AddMinutes(5)
    while ([DateTime]::UtcNow -lt $deadline) {
        try {
            $stream = [System.IO.File]::Open(
                $path, [System.IO.FileMode]::OpenOrCreate,
                [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::None
            )
        } catch [System.IO.IOException] {
            Start-Sleep -Milliseconds 100
            continue
        }
        try {
            Assert-NoReparseComponents -Path $path
            return $stream
        } catch {
            $stream.Dispose()
            throw
        }
    }
    throw "Timed out waiting for a HocusPocus filesystem lock."
}

function Assert-FrozenManifestCopy {
    param(
        [string]$SourceRoot,
        [string]$CopyRoot,
        [string]$ExpectedDigest,
        $ExpectedManifestFile
    )
    Assert-ManifestDigest -Path $SourceRoot -Expected $ExpectedDigest `
        -Label "Staged output"
    Assert-ManifestDigest -Path $CopyRoot -Expected $ExpectedDigest `
        -Label "Install snapshot"
    Assert-FileSnapshot `
        -Path (Join-Path $SourceRoot "package\install-manifest-v1.json") `
        -Expected $ExpectedManifestFile -Label "Staged manifest" `
        -MaximumBytes (8 * 1024 * 1024)
    $copiedManifestFile = Get-FileSnapshot `
        -Path (Join-Path $CopyRoot "package\install-manifest-v1.json") `
        -MaximumBytes (8 * 1024 * 1024)
    $expectedManifestFile = ConvertTo-FileSnapshot `
        -Value $ExpectedManifestFile
    if (
        -not $copiedManifestFile.Exists -or
        $copiedManifestFile.Digest -cne $expectedManifestFile.Digest -or
        $copiedManifestFile.Bytes -cne $expectedManifestFile.Bytes
    ) {
        throw "Frozen install manifest content changed during snapshot copy."
    }
}

function Get-ActivePackageName {
    param([string]$Pointer)
    if (-not (Test-Path -LiteralPath $Pointer)) { return "HocusPocus" }
    $match = [regex]::Match(
        [System.IO.File]::ReadAllText($Pointer),
        'HocusPocus(?:\.[0-9a-f]{12}\.[0-9a-f]{8})?'
    )
    return $(if ($match.Success) { $match.Value } else { "HocusPocus" })
}

function Invoke-InstallSnapshot {
    param(
        [string]$StagedRoot,
        [string]$PreferenceRoot,
        [string]$AuthorityRoot,
        [bool]$Rotate,
        [bool]$PublishUserToken
    )
    Assert-SafePreferenceRoot -Path $PreferenceRoot
    Assert-SafeAuthorityRoot `
        -Path $AuthorityRoot -PreferenceRoot $PreferenceRoot
    Ensure-Directory -Path $AuthorityRoot
    Assert-NoReparseComponents -Path $AuthorityRoot
    $tokenLock = Enter-PathLock `
        -Parent $AuthorityRoot -Name ".hocuspocus-token.lock"
    $preferenceLock = $null
    $tokenJournal = Join-Path $AuthorityRoot "token-activation.json"
    try {
        Recover-TokenTransaction `
            -Path $tokenJournal -AuthorityRoot $AuthorityRoot
        $packagesDir = Join-Path $PreferenceRoot "packages"
        Ensure-Directory -Path $packagesDir
        Assert-NoReparseComponents -Path $packagesDir
        $preferenceLock = Enter-PathLock `
            -Parent $packagesDir -Name ".hocuspocus-install.lock"
        $activePointer = Join-Path $packagesDir "hocuspocus.json"
        $stagedManifest = Invoke-Manifest `
            -Root $StagedRoot -Command "verify"
        $stagedDigest = [string]$stagedManifest.manifestDigest
        $stagedManifestFile = Get-FileSnapshot -Path (
            Join-Path $StagedRoot "package\install-manifest-v1.json"
        ) -MaximumBytes (8 * 1024 * 1024)
        $activeName = Get-ActivePackageName -Pointer $activePointer
        $configuredToken = Read-ConfiguredToken -ConfigPath (
            Join-Path $packagesDir "$activeName\config\default.toml"
        )
        $oldUserToken = $(if ($PublishUserToken) {
            Get-UserToken -AuthorityRoot $AuthorityRoot
        } else { "" })
        if (
            $oldUserToken -and
            -not (Test-StableToken -Token $oldUserToken) -and
            -not $Rotate
        ) {
            throw "Persisted HocusPocus token authority is malformed."
        }
        $existingToken = $(if (
            $PublishUserToken -and (Test-StableToken -Token $oldUserToken)
        ) {
            $oldUserToken
        } else {
            $configuredToken
        })
        $installCandidate = Join-Path $packagesDir (
            ".HocusPocus.install." + [guid]::NewGuid().ToString("N")
        )
        $versionPath = $null
        $newVersionPath = $null
        $pointerCandidate = $null
        $journalWritten = $false
        try {
            Assert-OwnedChild -Parent $packagesDir -Path $installCandidate
            Copy-Item -LiteralPath $StagedRoot `
                -Destination $installCandidate -Recurse -Force
            Assert-NoReparseTree -Path $installCandidate
            Assert-FrozenManifestCopy `
                -SourceRoot $StagedRoot -CopyRoot $installCandidate `
                -ExpectedDigest $stagedDigest `
                -ExpectedManifestFile $stagedManifestFile
            $tokenInfo = Provision-InstallToken `
                -ConfigPath (
                    Join-Path $installCandidate "config\default.toml"
                ) `
                -ExistingToken $existingToken -ForceRotation $Rotate
            Assert-FrozenManifestCopy `
                -SourceRoot $StagedRoot -CopyRoot $installCandidate `
                -ExpectedDigest $stagedDigest `
                -ExpectedManifestFile $stagedManifestFile
            $configDigest = Get-Sha256Hex -Path (
                Join-Path $installCandidate "config\default.toml"
            )
            $versionName = (
                "HocusPocus." + $stagedDigest.Substring(7, 12) +
                "." + $configDigest.Substring(0, 8)
            )
            $versionPath = Join-Path $packagesDir $versionName
            Assert-OwnedChild -Parent $packagesDir -Path $versionPath
            if (Test-Path -LiteralPath $versionPath) {
                Assert-ManifestDigest -Path $versionPath `
                    -Expected $stagedDigest -Label "Existing installed version"
                if (
                    (Get-Sha256Hex -Path (
                        Join-Path $versionPath "config\default.toml"
                    )) -cne $configDigest
                ) {
                    throw "Existing installed version has conflicting config."
                }
                Remove-OwnedPath `
                    -Path $installCandidate -Parent $packagesDir
                $installCandidate = $null
            } else {
                Move-Item -LiteralPath $installCandidate `
                    -Destination $versionPath
                $installCandidate = $null
                $newVersionPath = $versionPath
                Assert-ManifestDigest -Path $versionPath `
                    -Expected $stagedDigest -Label "Installed version"
            }
            $pointerBefore = Get-FileSnapshot -Path $activePointer
            $pointerCandidate = Join-Path $packagesDir (
                ".hocuspocus.json.candidate." +
                [guid]::NewGuid().ToString("N")
            )
            $pointerAfter = New-PackagePointerCandidate `
                -Path $pointerCandidate -RootName $versionName `
                -Parent $packagesDir
            $pointerBackup = $(if ($pointerBefore.Exists) {
                Join-Path $packagesDir (
                    ".hocuspocus.json.backup." +
                    [guid]::NewGuid().ToString("N")
                )
            } else { $null })
            $envelope = [ordered]@{
                schemaVersion = 2
                desired = "commit"
                phase = "prepared"
                authorityRoot = [System.IO.Path]::GetFullPath($AuthorityRoot)
                authorityRootIdentity = Get-PathIdentity -Path $AuthorityRoot
                packagesDir = [System.IO.Path]::GetFullPath($packagesDir)
                packagesDirIdentity = Get-PathIdentity -Path $packagesDir
                versionName = $versionName
                manifestDigest = $stagedDigest
                pointerCandidateName = Split-Path -Leaf $pointerCandidate
                pointerBackupName = $(if ($pointerBackup) {
                    Split-Path -Leaf $pointerBackup
                } else { "" })
                pointerBefore = $pointerBefore
                pointerAfter = $pointerAfter
                tokenEnabled = [bool]$tokenInfo.TokenEnabled
                publishUserToken = (
                    [bool]$tokenInfo.TokenEnabled -and $PublishUserToken
                )
                oldToken = [string]$oldUserToken
                oldTokenDigest = Get-Sha256Text -Value ([string]$oldUserToken)
                newToken = [string]$tokenInfo.Token
                newTokenDigest = Get-Sha256Text -Value ([string]$tokenInfo.Token)
            }
            Write-TokenJournal `
                -Path $tokenJournal -AuthorityRoot $AuthorityRoot `
                -Envelope $envelope
            $journalWritten = $true
            Complete-TokenTransaction `
                -Path $tokenJournal -AuthorityRoot $AuthorityRoot `
                -Envelope $envelope
            $newVersionPath = $null
            $pointerCandidate = $null
            Write-Step "Activated $versionName"
        } catch {
            $primaryError = $_
            if (-not $journalWritten) {
                foreach ($cleanup in @(
                    @($installCandidate, "install candidate"),
                    @($pointerCandidate, "install pointer candidate"),
                    @($newVersionPath, "new installed version")
                )) {
                    if ($cleanup[0] -and (Test-Path -LiteralPath $cleanup[0])) {
                        Invoke-BestEffortCleanup `
                            -Label $cleanup[1] `
                            -Classification "primary-failure" -Action {
                            Remove-OwnedPath `
                                -Path $cleanup[0] -Parent $packagesDir
                        } | Out-Null
                    }
                }
            }
            throw $primaryError
        }
    } finally {
        if ($preferenceLock) { $preferenceLock.Dispose() }
        $tokenLock.Dispose()
    }
}

function Invoke-BuildTransaction {
    Assert-SafeOutputRoot
    Ensure-Directory -Path $resolvedOutputDir
    Assert-NoReparseComponents -Path $resolvedOutputDir
    $outputLock = Enter-PathLock `
        -Parent $resolvedOutputDir -Name ".hocuspocus-build.lock"
    try {
        Assert-SafeOutputRoot
        Recover-OutputTransaction `
            -JournalPath $outputJournal -OutputRoot $resolvedOutputDir `
            -ActiveTree $stagingRoot -ActivePointer $packageFilePath
        Write-OwnerFile
        if ($Clean) {
            Write-Step "Building a clean replacement without deleting active output"
        }
        $candidate = Join-Path $resolvedOutputDir (
            ".HocusPocus.candidate." + [guid]::NewGuid().ToString("N")
        )
        $pointerCandidate = $null
        $journalWritten = $false
        try {
            Ensure-Directory -Path $candidate
            Write-Step "Building candidate package"
            foreach ($relativePath in @(
                "config", "docs\schemas", "python_panels",
                "python3.11libs", "scripts", "toolbar", "package"
            )) {
                Copy-RepoPath `
                    -RelativePath $relativePath -DestinationRoot $candidate
            }
            Assert-NoReparseTree -Path $candidate
            Write-Step "Compiling Python modules with $PythonExe"
            & $PythonExe -m compileall (
                Join-Path $candidate "python3.11libs"
            )
            if ($LASTEXITCODE -ne 0) {
                throw "compileall failed with exit code $LASTEXITCODE"
            }
            Remove-PythonBytecode -Path $candidate
            $manifest = Invoke-Manifest -Root $candidate
            $candidateDigest = [string]$manifest.manifestDigest
            Assert-ManifestDigest -Path $candidate `
                -Expected $candidateDigest -Label "Build candidate"
            $previousName = $(if (Test-Path -LiteralPath $stagingRoot) {
                ".HocusPocus.previous." + [guid]::NewGuid().ToString("N")
            } else { "" })
            $previousDigest = $(if ($previousName) {
                Get-VerifiedManifestDigest -Path $stagingRoot
            } else { "" })
            $pointerBefore = Get-FileSnapshot -Path $packageFilePath
            $pointerCandidate = Join-Path $resolvedOutputDir (
                "hocuspocus.json.candidate." +
                [guid]::NewGuid().ToString("N")
            )
            $pointerAfter = New-PackagePointerCandidate `
                -Path $pointerCandidate -RootName "HocusPocus" `
                -Parent $resolvedOutputDir
            $pointerBackupName = $(if ($pointerBefore.Exists) {
                "hocuspocus.json.backup." +
                    [guid]::NewGuid().ToString("N")
            } else { "" })
            $state = [ordered]@{
                schemaVersion = 2
                desired = "commit"
                phase = "prepared"
                candidateName = Split-Path -Leaf $candidate
                candidateManifestDigest = $candidateDigest
                previousName = $previousName
                previousManifestDigest = $previousDigest
                pointerCandidateName = Split-Path -Leaf $pointerCandidate
                pointerBackupName = $pointerBackupName
                pointerBefore = $pointerBefore
                pointerAfter = $pointerAfter
            }
            Write-JsonJournal -Path $outputJournal -State $state
            $journalWritten = $true
            # This exact move remains the atomic candidate-to-active boundary.
            Complete-OutputTransaction `
                -JournalPath $outputJournal `
                -OutputRoot $resolvedOutputDir `
                -ActiveTree $stagingRoot `
                -ActivePointer $packageFilePath -State $state
            $candidate = $null
            $pointerCandidate = $null
            if ($Install) {
                $preferenceRoot = $(if ($HoudiniUserPrefDir) {
                    [System.IO.Path]::GetFullPath($HoudiniUserPrefDir)
                } else {
                    Join-Path (
                        [Environment]::GetFolderPath("MyDocuments")
                    ) ("houdini" + $HoudiniVersion)
                })
                $authorityRoot = [System.IO.Path]::GetFullPath(
                    $(if ($env:HOCUSPOCUS_BUILD_AUTHORITY_ROOT) {
                        $env:HOCUSPOCUS_BUILD_AUTHORITY_ROOT
                    } else {
                        Join-Path $env:LOCALAPPDATA `
                            "HocusPocus\install-authority"
                    })
                )
                Invoke-InstallSnapshot `
                    -StagedRoot $stagingRoot `
                    -PreferenceRoot $preferenceRoot `
                    -AuthorityRoot $authorityRoot `
                    -Rotate ([bool]$RotateToken) `
                    -PublishUserToken (-not [bool]$SkipUserEnvironment)
                $script:activePackage = Join-Path `
                    (Join-Path $preferenceRoot "packages") "hocuspocus.json"
            }
        } catch {
            $primaryError = $_
            if (-not $journalWritten) {
                foreach ($cleanup in @(
                    @($candidate, "build candidate"),
                    @($pointerCandidate, "output pointer candidate")
                )) {
                    if ($cleanup[0] -and (Test-Path -LiteralPath $cleanup[0])) {
                        Invoke-BestEffortCleanup `
                            -Label $cleanup[1] `
                            -Classification "primary-failure" -Action {
                            Remove-OwnedPath `
                                -Path $cleanup[0] -Parent $resolvedOutputDir
                        } | Out-Null
                    }
                }
            }
            throw $primaryError
        }
    } finally {
        $outputLock.Dispose()
    }
}
