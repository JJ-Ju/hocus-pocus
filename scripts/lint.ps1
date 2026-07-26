[CmdletBinding()]
param(
    [string]$PythonExe = "python"
)

function Get-RepoRelativePath {
    param(
        [string]$Root,
        [string]$Path
    )

    $separator = [IO.Path]::DirectorySeparatorChar
    $rootPrefix = $Root.TrimEnd(
        [IO.Path]::DirectorySeparatorChar,
        [IO.Path]::AltDirectorySeparatorChar
    ) + $separator
    if (-not $Path.StartsWith($rootPrefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Path '$Path' is outside repository root '$Root'."
    }
    return $Path.Substring($rootPrefix.Length)
}

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$status = 0
$testCount = 0
$oversizedFiles = @()
$complexitySuppressions = @()
$lineLimitedExtensions = @(
    ".bat", ".cfg", ".cmd", ".hocus", ".ini", ".json", ".md", ".ps1",
    ".psm1", ".py", ".pyi", ".shelf", ".sql", ".toml", ".txt", ".xml",
    ".yaml", ".yml"
)

Push-Location $repoRoot
try {
    & $PythonExe -m ruff check python3.11libs scripts tests
    $status = $LASTEXITCODE
    $testCount = @(
        Get-ChildItem -LiteralPath tests -Filter "test_*.py" -File |
            Select-String -Pattern '^\s*(?:async\s+)?def\s+test_'
    ).Count
    $excludedDirectories = @(
        ".git", ".hocuspocus", ".pytest_cache", ".ruff_cache", "dist"
    )
    $lineLimitedFiles = Get-ChildItem -LiteralPath . -Recurse -File | Where-Object {
        $relative = Get-RepoRelativePath -Root $repoRoot -Path $_.FullName
        $topLevel = ($relative -split '[\\/]')[0]
        $excludedDirectories -notcontains $topLevel -and
            $lineLimitedExtensions -contains $_.Extension.ToLowerInvariant()
    } | Sort-Object FullName -Unique
    $oversizedFiles = @(
        foreach ($file in $lineLimitedFiles) {
            $lineCount = @(Get-Content -LiteralPath $file.FullName).Count
            if ($lineCount -gt 1200) {
                [PSCustomObject]@{
                    Lines = $lineCount
                    File = Get-RepoRelativePath -Root $repoRoot -Path $file.FullName
                }
            }
        }
    )
    $pythonFiles = $lineLimitedFiles | Where-Object {
        $_.Extension -in @(".py", ".pyi")
    }
    $complexitySuppressions = @(
        $pythonFiles | Select-String -Pattern (
            '(?i)#\s*ruff:\s*noqa|#\s*noqa\s*$|' +
            '#\s*noqa\s*:[^#]*(?:C901|PLR0911|PLR0912|PLR0913|PLR0915)'
        )
        Select-String -LiteralPath ruff.toml -Pattern (
            '(?i)per-file-ignores|extend-per-file-ignores'
        )
    )
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

if ($oversizedFiles.Count -gt 0) {
    $oversizedTable = $oversizedFiles |
        Sort-Object Lines -Descending |
        Format-Table -AutoSize |
        Out-String
    Write-Host $oversizedTable
    Write-Error "Repository files must not exceed 1,200 physical lines." -ErrorAction Continue
    exit 1
}

if ($complexitySuppressions.Count -gt 0) {
    $complexitySuppressions | ForEach-Object {
        Write-Host "$($_.Path):$($_.LineNumber): $($_.Line.Trim())"
    }
    Write-Error "Complexity lint suppressions and per-file ignores are not allowed." -ErrorAction Continue
    exit 1
}

Write-Host "Test catalogue: $testCount/50 public scenarios."
Write-Host "File size: all checked files are at or below 1,200 lines."
