[CmdletBinding()]
param(
    [string]$PythonExe = "python"
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$status = 0
$testCount = 0

Push-Location $repoRoot
try {
    & $PythonExe -m ruff check python3.11libs scripts tests
    $status = $LASTEXITCODE
    $testCount = @(
        Get-ChildItem -LiteralPath tests -Filter "test_*.py" -File |
            Select-String -Pattern '^\s*(?:async\s+)?def\s+test_'
    ).Count
} finally {
    Pop-Location
}

if ($status -ne 0) {
    exit $status
}

if ($testCount -gt 50) {
    Write-Error "Test catalogue contains $testCount tests; the repository limit is 50."
    exit 1
}

Write-Host "Test catalogue: $testCount/50 public scenarios."
