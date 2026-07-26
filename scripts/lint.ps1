[CmdletBinding()]
param(
    [string]$PythonExe = "python"
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$status = 0

Push-Location $repoRoot
try {
    & $PythonExe -m ruff check python3.11libs scripts tests
    $status = $LASTEXITCODE
} finally {
    Pop-Location
}

if ($status -ne 0) {
    exit $status
}
