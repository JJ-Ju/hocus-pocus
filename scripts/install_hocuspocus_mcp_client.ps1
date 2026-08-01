param(
    [string]$HoudiniPreferenceRoot = (
        Join-Path $HOME "Documents\houdini22.0"
    ),
    [string]$PythonExe = "",
    [string]$HttpUrl = "http://127.0.0.1:37219/hocuspocus/mcp"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$parsedUrl = $null
if (
    -not [uri]::TryCreate($HttpUrl, [UriKind]::Absolute, [ref]$parsedUrl) -or
    $parsedUrl.Scheme -ne "http" -or
    $parsedUrl.Host -ne "127.0.0.1" -or
    $parsedUrl.AbsolutePath -ne "/hocuspocus/mcp" -or
    $parsedUrl.Query
) {
    throw "HttpUrl must select the HocusPocus MCP route on numeric loopback."
}

function Resolve-BrokerPython {
    param([string]$Requested)
    $candidates = @()
    if ($Requested) {
        $candidates += $Requested
    } else {
        $houdiniRoots = @(
            Get-ChildItem `
                -LiteralPath "C:\Program Files\Side Effects Software" `
                -Directory -Filter "Houdini 22.*" -ErrorAction SilentlyContinue |
                Sort-Object Name -Descending
        )
        foreach ($root in $houdiniRoots) {
            $candidates += Join-Path $root.FullName "python313\python.exe"
            $candidates += Join-Path $root.FullName "python311\python.exe"
        }
        $ambient = Get-Command python -ErrorAction SilentlyContinue
        if ($null -ne $ambient) {
            $candidates += $ambient.Source
        }
    }
    foreach ($candidate in $candidates) {
        if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) {
            continue
        }
        $version = & $candidate -I -c (
            "import sys; " +
            "print(f'{sys.version_info.major}.{sys.version_info.minor}'); " +
            "raise SystemExit(0 if sys.version_info >= (3, 11) else 9)"
        )
        if ($LASTEXITCODE -eq 0) {
            return [pscustomobject]@{
                Path = [System.IO.Path]::GetFullPath($candidate)
                Version = [string]$version
            }
        }
    }
    throw "A standalone Python 3.11 or newer runtime is required."
}

function Invoke-InstallerAdmission {
    param(
        [string]$PythonPath,
        [string]$PointerPath
    )
    $validator = @'
import base64
import hashlib
import json
import os
import re
import stat
import sys
from pathlib import Path

DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
VERSION = re.compile(r"HocusPocus\.[0-9a-f]{12}\.[0-9a-f]{8}")
TOKEN = re.compile(rb'(?m)^token\s*=\s*"[^"]*"\s*$')
ROOTS = (
    "config", "docs/schemas", "python_panels", "python3.11libs",
    "scripts", "toolbar", "package",
)
MANIFEST = "package/install-manifest-v1.json"
LAUNCHER = "scripts/hocuspocus-mcp-stdio.py"
REPARSE = 0x400
MAX_LAUNCHER = 2 * 1024 * 1024

def digest(content):
    return "sha256:" + hashlib.sha256(content).hexdigest()

def identity(info):
    return [info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns]

def read_file(path, limit):
    before = path.lstat()
    attributes = getattr(before, "st_file_attributes", 0)
    if (
        not stat.S_ISREG(before.st_mode) or stat.S_ISLNK(before.st_mode)
        or attributes & REPARSE or before.st_nlink != 1 or before.st_size > limit
    ):
        raise ValueError("unsafe file")
    with path.open("rb") as stream:
        opened = os.fstat(stream.fileno())
        content = stream.read(limit + 1)
        after = os.fstat(stream.fileno())
    if len(content) > limit or identity(before) != identity(opened):
        raise ValueError("unstable file")
    if identity(opened) != identity(after) or len(content) != opened.st_size:
        raise ValueError("unstable file")
    return content, identity(after)

def dir_identity(path):
    info = path.lstat()
    attributes = getattr(info, "st_file_attributes", 0)
    if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode) or attributes & REPARSE:
        raise ValueError("unsafe directory")
    return [info.st_dev, info.st_ino]

def canonical(value):
    return json.dumps(
        value, ensure_ascii=False, allow_nan=False,
        separators=(",", ":"), sort_keys=True,
    ).encode("utf-8")

def load_json(content):
    return json.loads(content.decode("utf-8"))

def record(root, path):
    resolved = path.resolve(strict=True)
    relative = resolved.relative_to(root).as_posix()
    content, file_id = read_file(resolved, 64 * 1024 * 1024)
    role = "generated_config" if relative == "config/default.toml" else "immutable"
    governed = content
    if role == "generated_config":
        if TOKEN.search(content) is None:
            raise ValueError("invalid generated configuration")
        governed = TOKEN.sub(b'token = "<redacted>"', content)
    return {
        "relativePath": relative,
        "role": role,
        "byteLength": len(governed),
        "contentDigest": digest(governed),
    }, content, file_id

def validate(pointer_path):
    lexical = pointer_path.absolute()
    for component in (lexical, *lexical.parents):
        info = component.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & REPARSE:
            raise ValueError("unsafe pointer component")
    packages = pointer_path.parent.resolve(strict=True)
    packages_id = dir_identity(packages)
    pointer_raw, pointer_id = read_file(pointer_path, 64 * 1024)
    pointer = load_json(pointer_raw)
    if not isinstance(pointer, dict) or set(pointer) != {"env", "hpath", "hocuspocus"}:
        raise ValueError("invalid pointer")
    env = pointer["env"]
    if not isinstance(env, list) or len(env) != 3:
        raise ValueError("invalid pointer environment")
    prefix = "$HOUDINI_PACKAGE_PATH/"
    first = env[0]
    if not isinstance(first, dict) or set(first) != {"HOCUSPOCUS_ROOT"}:
        raise ValueError("invalid root selector")
    selector = first["HOCUSPOCUS_ROOT"]
    if not isinstance(selector, str) or not selector.startswith(prefix):
        raise ValueError("invalid root selector")
    root_name = selector[len(prefix):]
    if VERSION.fullmatch(root_name) is None:
        raise ValueError("unsafe root selector")
    root = (packages / root_name).resolve(strict=True)
    if root.parent != packages or dir_identity(root) != dir_identity(packages / root_name):
        raise ValueError("unsafe active root")
    root_id = dir_identity(root)
    config_raw, config_id = read_file(root / "config/default.toml", 1024 * 1024)
    config_digest = digest(config_raw)
    manifest_path = root / MANIFEST
    manifest_raw, manifest_id = read_file(manifest_path, 32 * 1024 * 1024)
    manifest = load_json(manifest_raw)
    fields = {"$schema", "kind", "schemaVersion", "governedRoots", "files", "manifestDigest"}
    if not isinstance(manifest, dict) or set(manifest) != fields:
        raise ValueError("invalid manifest envelope")
    if (
        manifest["$schema"] != "hocuspocus://schemas/install-manifest/v1"
        or manifest["kind"] != "hocus_install_manifest"
        or manifest["schemaVersion"] != 1
        or manifest["governedRoots"] != list(ROOTS)
        or not isinstance(manifest["files"], list)
        or len(manifest["files"]) > 20000
    ):
        raise ValueError("invalid manifest identity")
    unsigned = {key: value for key, value in manifest.items() if key != "manifestDigest"}
    manifest_digest = digest(canonical(unsigned))
    if manifest["manifestDigest"] != manifest_digest:
        raise ValueError("invalid manifest digest")
    rows = []
    launcher_bytes = None
    launcher_id = None
    for governed in ROOTS:
        base = root / governed
        dir_identity(base)
        for path in sorted(base.rglob("*"), key=lambda value: value.as_posix().casefold()):
            info = path.lstat()
            attributes = getattr(info, "st_file_attributes", 0)
            if stat.S_ISLNK(info.st_mode) or attributes & REPARSE:
                raise ValueError("unsafe governed path")
            if path.name == "__pycache__" or path.suffix.casefold() in {".pyc", ".pyo"}:
                raise ValueError("ungoverned bytecode")
            if stat.S_ISDIR(info.st_mode):
                continue
            if not stat.S_ISREG(info.st_mode):
                raise ValueError("unsafe governed special file")
            resolved = path.resolve(strict=True)
            relative = resolved.relative_to(root).as_posix()
            if relative == MANIFEST:
                continue
            row, content, file_id = record(root, resolved)
            rows.append(row)
            if relative == LAUNCHER:
                launcher_bytes, launcher_id = content, file_id
    if (
        rows != manifest["files"] or launcher_bytes is None
        or len(launcher_bytes) > MAX_LAUNCHER
    ):
        raise ValueError("manifest does not match install")
    launcher_row = next((row for row in rows if row["relativePath"] == LAUNCHER), None)
    if launcher_row is None or launcher_row["role"] != "immutable":
        raise ValueError("launcher is not governed")
    authority = pointer["hocuspocus"]
    if (
        not isinstance(authority, dict)
        or set(authority) != {"schemaVersion", "activeConfigDigest", "installManifestDigest"}
        or authority["schemaVersion"] != 1
        or not isinstance(authority["activeConfigDigest"], str)
        or DIGEST.fullmatch(authority["activeConfigDigest"]) is None
        or not isinstance(authority["installManifestDigest"], str)
        or DIGEST.fullmatch(authority["installManifestDigest"]) is None
        or authority["activeConfigDigest"] != config_digest
        or authority["installManifestDigest"] != manifest_digest
    ):
        raise ValueError("stale pointer authority")
    expected = {
        "env": [
            {"HOCUSPOCUS_ROOT": prefix + root_name},
            {"PYTHONPATH": {"method": "prepend", "value": "$HOCUSPOCUS_ROOT/python3.11libs"}},
            {"PYTHONDONTWRITEBYTECODE": "1"},
        ],
        "hpath": "$HOCUSPOCUS_ROOT",
        "hocuspocus": authority,
    }
    if pointer != expected:
        raise ValueError("noncanonical pointer")
    pointer_again, pointer_id_again = read_file(pointer_path, 64 * 1024)
    config_again, config_id_again = read_file(root / "config/default.toml", 1024 * 1024)
    manifest_again, manifest_id_again = read_file(manifest_path, 32 * 1024 * 1024)
    launcher_again, launcher_id_again = read_file(root / LAUNCHER, 64 * 1024 * 1024)
    if (
        pointer_again != pointer_raw or pointer_id_again != pointer_id
        or config_again != config_raw or config_id_again != config_id
        or manifest_again != manifest_raw or manifest_id_again != manifest_id
        or launcher_again != launcher_bytes or launcher_id_again != launcher_id
        or dir_identity(packages) != packages_id or dir_identity(root) != root_id
    ):
        raise ValueError("authority changed during admission")
    return {
        "schemaVersion": 1,
        "rootName": root_name,
        "pointerDigest": digest(pointer_raw),
        "configDigest": config_digest,
        "manifestDigest": manifest_digest,
        "launcherDigest": digest(launcher_bytes),
        "launcherLength": len(launcher_bytes),
        "launcherIdentity": launcher_id,
        "launcherContent": base64.b64encode(launcher_bytes).decode("ascii"),
    }

try:
    print(json.dumps(validate(Path(sys.argv[1])), separators=(",", ":")))
except Exception:
    sys.stderr.write("HocusPocus client installer admission failed.\n")
    raise SystemExit(1)
'@
    $validatorPath = Join-Path ([IO.Path]::GetTempPath()) (
        "hocuspocus-client-admission-" + [guid]::NewGuid().ToString("N") + ".py"
    )
    $validatorBytes = (New-Object Text.UTF8Encoding($false)).GetBytes($validator)
    $validatorStream = [IO.File]::Open(
        $validatorPath,
        [IO.FileMode]::CreateNew,
        [IO.FileAccess]::Write,
        [IO.FileShare]::None
    )
    try {
        $validatorStream.Write($validatorBytes, 0, $validatorBytes.Length)
        $validatorStream.Flush($true)
    } finally {
        $validatorStream.Dispose()
    }
    try {
        $result = & $PythonPath -I -B $validatorPath $PointerPath
        if ($LASTEXITCODE -ne 0) {
            throw "HocusPocus active package failed installer admission."
        }
    } finally {
        Remove-Item -LiteralPath $validatorPath -Force -ErrorAction SilentlyContinue
    }
    try {
        return ($result | Out-String | ConvertFrom-Json)
    } catch {
        throw "HocusPocus installer admission returned invalid evidence."
    }
}

function Assert-SameAdmission {
    param($Expected, $Actual)
    foreach ($name in @(
        "rootName", "pointerDigest", "configDigest", "manifestDigest",
        "launcherDigest", "launcherLength", "launcherContent"
    )) {
        if ([string]$Expected.$name -cne [string]$Actual.$name) {
            throw "HocusPocus active package changed during client installation."
        }
    }
    if (
        @($Expected.launcherIdentity).Count -ne 4 -or
        @($Actual.launcherIdentity).Count -ne 4
    ) {
        throw "HocusPocus installer admission returned invalid identity evidence."
    }
    for ($index = 0; $index -lt 4; $index++) {
        if (
            [string]$Expected.launcherIdentity[$index] -cne
            [string]$Actual.launcherIdentity[$index]
        ) {
            throw "HocusPocus active package changed during client installation."
        }
    }
}

function Get-BytesDigest {
    param([byte[]]$Content)
    $hasher = [Security.Cryptography.SHA256]::Create()
    try {
        $digest = $hasher.ComputeHash($Content)
    } finally {
        $hasher.Dispose()
    }
    return "sha256:" + [BitConverter]::ToString($digest).Replace("-", "").ToLowerInvariant()
}

function Get-LauncherSnapshot {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        return [pscustomobject]@{
            Exists = $false; Length = 0; Digest = ""; LastWriteTicks = 0
        }
    }
    $item = Get-Item -LiteralPath $Path -Force
    if (
        $item.PSIsContainer -or
        ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -or
        $item.Length -gt 2MB
    ) {
        throw "Stable HocusPocus launcher destination is unsafe."
    }
    $bytes = [IO.File]::ReadAllBytes($item.FullName)
    return [pscustomobject]@{
        Exists = $true
        Length = [int64]$bytes.Length
        Digest = Get-BytesDigest -Content $bytes
        LastWriteTicks = [int64]$item.LastWriteTimeUtc.Ticks
    }
}

function Test-LauncherSnapshot {
    param($Expected, $Actual)
    return (
        [bool]$Expected.Exists -eq [bool]$Actual.Exists -and
        [int64]$Expected.Length -eq [int64]$Actual.Length -and
        [string]$Expected.Digest -ceq [string]$Actual.Digest -and
        [int64]$Expected.LastWriteTicks -eq [int64]$Actual.LastWriteTicks
    )
}

function Publish-LauncherCandidate {
    param(
        [string]$Candidate,
        [string]$Destination,
        $ExpectedDestination
    )
    $actual = Get-LauncherSnapshot -Path $Destination
    if (-not (Test-LauncherSnapshot -Expected $ExpectedDestination -Actual $actual)) {
        throw "Stable HocusPocus launcher changed before publication."
    }
    if (-not [bool]$ExpectedDestination.Exists) {
        [IO.File]::Move($Candidate, $Destination)
        return ""
    }
    $backup = Join-Path ([IO.Path]::GetDirectoryName($Destination)) (
        "." + [IO.Path]::GetFileName($Destination) + "." +
        [guid]::NewGuid().ToString("N") + ".rollback"
    )
    [IO.File]::Replace($Candidate, $Destination, $backup)
    $displaced = Get-LauncherSnapshot -Path $backup
    if (-not (Test-LauncherSnapshot -Expected $ExpectedDestination -Actual $displaced)) {
        [IO.File]::Replace($backup, $Destination, $null)
        throw "Stable HocusPocus launcher changed during publication."
    }
    return $backup
}

function Restore-LauncherPublication {
    param(
        [string]$Destination,
        [string]$Backup,
        $ExpectedDestination,
        [string]$PublishedDigest
    )
    $published = Get-LauncherSnapshot -Path $Destination
    if ($published.Digest -cne $PublishedDigest) {
        throw "Stable HocusPocus launcher changed after publication."
    }
    if ([bool]$ExpectedDestination.Exists) {
        [IO.File]::Replace($Backup, $Destination, $null)
    } else {
        Remove-Item -LiteralPath $Destination -Force
    }
}

function Publish-AtomicCandidate {
    param(
        [string]$Candidate,
        [string]$Destination
    )
    if (-not (Test-Path -LiteralPath $Destination)) {
        Move-Item -LiteralPath $Candidate -Destination $Destination
        return
    }
    $backup = Join-Path ([System.IO.Path]::GetDirectoryName($Destination)) (
        "." + [System.IO.Path]::GetFileName($Destination) + "." +
        [guid]::NewGuid().ToString("N") + ".bak"
    )
    try {
        [System.IO.File]::Replace($Candidate, $Destination, $backup)
    } finally {
        if (Test-Path -LiteralPath $backup) {
            Remove-Item -LiteralPath $backup -Force
        }
    }
}

function Write-AtomicText {
    param(
        [string]$Path,
        [string]$Content
    )
    $candidate = Join-Path ([System.IO.Path]::GetDirectoryName($Path)) (
        "." + [System.IO.Path]::GetFileName($Path) + "." +
        [guid]::NewGuid().ToString("N") + ".tmp"
    )
    try {
        [System.IO.File]::WriteAllText(
            $candidate,
            $Content,
            (New-Object System.Text.UTF8Encoding($false))
        )
        Publish-AtomicCandidate -Candidate $candidate -Destination $Path
    } finally {
        if (Test-Path -LiteralPath $candidate) {
            Remove-Item -LiteralPath $candidate -Force
        }
    }
}

$python = Resolve-BrokerPython -Requested $PythonExe
$packages = [System.IO.Path]::GetFullPath(
    (Join-Path $HoudiniPreferenceRoot "packages")
)
$pointer = Join-Path $packages "hocuspocus.json"
if (-not (Test-Path -LiteralPath $pointer -PathType Leaf)) {
    throw "HocusPocus active-package pointer not found: $pointer"
}
$admission = Invoke-InstallerAdmission `
    -PythonPath $python.Path -PointerPath $pointer
$rootName = [string]$admission.rootName

$destination = Join-Path $packages "hocuspocus-mcp-stdio.py"
$destinationBefore = Get-LauncherSnapshot -Path $destination
$candidate = Join-Path $packages (
    ".hocuspocus-mcp-stdio." + [guid]::NewGuid().ToString("N") + ".tmp"
)
$backup = ""
$published = $false
try {
    $launcherBytes = [Convert]::FromBase64String(
        [string]$admission.launcherContent
    )
    if (
        $launcherBytes.Length -ne [int64]$admission.launcherLength -or
        (Get-BytesDigest -Content $launcherBytes) -cne
            [string]$admission.launcherDigest
    ) {
        throw "HocusPocus installer admission returned invalid launcher bytes."
    }
    $candidateStream = [IO.File]::Open(
        $candidate,
        [IO.FileMode]::CreateNew,
        [IO.FileAccess]::Write,
        [IO.FileShare]::None
    )
    try {
        $candidateStream.Write($launcherBytes, 0, $launcherBytes.Length)
        $candidateStream.Flush($true)
    } finally {
        $candidateStream.Dispose()
    }
    $candidateSnapshot = Get-LauncherSnapshot -Path $candidate
    if (
        $candidateSnapshot.Length -ne [int64]$admission.launcherLength -or
        $candidateSnapshot.Digest -cne [string]$admission.launcherDigest
    ) {
        throw "HocusPocus launcher candidate changed before publication."
    }
    $finalAdmission = Invoke-InstallerAdmission `
        -PythonPath $python.Path -PointerPath $pointer
    Assert-SameAdmission -Expected $admission -Actual $finalAdmission
    $backup = Publish-LauncherCandidate `
        -Candidate $candidate -Destination $destination `
        -ExpectedDestination $destinationBefore
    $published = $true
    $installedLauncher = Get-LauncherSnapshot -Path $destination
    if (
        $installedLauncher.Length -ne [int64]$admission.launcherLength -or
        $installedLauncher.Digest -cne [string]$admission.launcherDigest
    ) {
        throw "Stable HocusPocus launcher publication is invalid."
    }
    $postAdmission = Invoke-InstallerAdmission `
        -PythonPath $python.Path -PointerPath $pointer
    Assert-SameAdmission -Expected $admission -Actual $postAdmission
} catch {
    if ($published) {
        Restore-LauncherPublication `
            -Destination $destination -Backup $backup `
            -ExpectedDestination $destinationBefore `
            -PublishedDigest ([string]$admission.launcherDigest)
    }
    throw
} finally {
    if (Test-Path -LiteralPath $candidate) {
        Remove-Item -LiteralPath $candidate -Force
    }
    if ($backup -and (Test-Path -LiteralPath $backup)) {
        Remove-Item -LiteralPath $backup -Force -ErrorAction SilentlyContinue
    }
}

$codexConfig = Join-Path $packages "hocuspocus-codex.toml"
$claudeConfig = Join-Path $packages "hocuspocus-claude.json"
$pythonToml = $python.Path.Replace("'", "''")
$launcherToml = $destination.Replace("'", "''")
$codexContent = @"
[mcp_servers.hocuspocus]
command = '$pythonToml'
args = ['-I', '-B', '$launcherToml']
startup_timeout_sec = 120
tool_timeout_sec = 120

[mcp_servers.hocuspocus.env]
HOCUSPOCUS_HTTP_URL = '$HttpUrl'
HOCUSPOCUS_CONNECT_TIMEOUT_SECONDS = '1.0'
HOCUSPOCUS_REQUEST_TIMEOUT_SECONDS = '30.0'
PYTHONDONTWRITEBYTECODE = '1'
"@
Write-AtomicText -Path $codexConfig -Content (
    $codexContent + [Environment]::NewLine
)
$claudeContent = [ordered]@{
    mcpServers = [ordered]@{
        hocuspocus = [ordered]@{
            command = $python.Path
            args = @("-I", "-B", $destination)
            env = [ordered]@{
                HOCUSPOCUS_HTTP_URL = (
                    $HttpUrl
                )
                HOCUSPOCUS_CONNECT_TIMEOUT_SECONDS = "1.0"
                HOCUSPOCUS_REQUEST_TIMEOUT_SECONDS = "30.0"
                PYTHONDONTWRITEBYTECODE = "1"
            }
        }
    }
} | ConvertTo-Json -Depth 8
Write-AtomicText -Path $claudeConfig -Content (
    $claudeContent + [Environment]::NewLine
)

[pscustomobject]@{
    schemaVersion = 1
    commandName = "hocuspocus-mcp-stdio"
    launcherPath = $destination
    pythonExe = $python.Path
    pythonVersion = $python.Version
    arguments = @("-I", "-B", $destination)
    activePackage = $rootName
    codexConfig = $codexConfig
    claudeConfig = $claudeConfig
} | ConvertTo-Json
