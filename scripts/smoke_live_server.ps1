param(
    [string]$BaseUrl = "http://127.0.0.1:37219/hocuspocus",
    [string]$TokenPath = "$env:USERPROFILE\Documents\houdini21.0\hocuspocus\runtime\token.txt",
    [switch]$IncludeOptionalDomains
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Get-HocusPocusToken {
    param([string]$Path)
    if (-not (Test-Path $Path)) {
        throw "Token file not found: $Path"
    }
    return (Get-Content $Path -Raw).Trim()
}

function Invoke-HpJson {
    param(
        [string]$Url,
        [string]$Token,
        [string]$Method = "GET",
        [object]$Body = $null
    )

    $headers = @{ Authorization = "Bearer $Token" }
    if ($null -eq $Body) {
        return Invoke-RestMethod -Uri $Url -Headers $headers -Method $Method
    }

    $json = $Body | ConvertTo-Json -Depth 30
    return Invoke-RestMethod -Uri $Url -Headers $headers -Method $Method -ContentType "application/json" -Body $json
}

function Invoke-HpMcp {
    param(
        [string]$BaseUrl,
        [string]$Token,
        [int]$Id,
        [string]$Method,
        [hashtable]$Params = @{}
    )

    return Invoke-HpJson -Url "$BaseUrl/mcp" -Token $Token -Method "POST" -Body @{
        jsonrpc = "2.0"
        id = $Id
        method = $Method
        params = $Params
    }
}

function Assert-True {
    param(
        [bool]$Condition,
        [string]$Message
    )
    if (-not $Condition) {
        throw $Message
    }
}

$token = Get-HocusPocusToken -Path $TokenPath
$health = Invoke-HpJson -Url "$BaseUrl/healthz" -Token $token
Assert-True ($health.running -eq $true) "Server is not running."

$tools = (Invoke-HpMcp -BaseUrl $BaseUrl -Token $token -Id 1 -Method "tools/list").result.tools
$toolNames = @($tools | ForEach-Object { $_.name })
foreach ($required in @("scene.get_summary", "node.create", "node.delete", "graph.query", "package.preview_scene")) {
    Assert-True ($toolNames -contains $required) "Required tool missing: $required"
}

$scene = Invoke-HpMcp -BaseUrl $BaseUrl -Token $token -Id 2 -Method "tools/call" -Params @{
    name = "scene.get_summary"
    arguments = @{}
}
Assert-True ($scene.result.isError -eq $false) "scene.get_summary returned an error."

$probeName = "smoke_probe_$([DateTimeOffset]::UtcNow.ToUnixTimeSeconds())"
$probePath = "/obj/$probeName"

$create = Invoke-HpMcp -BaseUrl $BaseUrl -Token $token -Id 3 -Method "tools/call" -Params @{
    name = "node.create"
    arguments = @{
        parent_path = "/obj"
        node_type_name = "geo"
        node_name = $probeName
    }
}
Assert-True ($create.result.isError -eq $false) "node.create failed."
Assert-True ($create.result.structuredContent.path -eq $probePath) "node.create returned the wrong path."

$graph = Invoke-HpMcp -BaseUrl $BaseUrl -Token $token -Id 4 -Method "resources/read" -Params @{
    uri = "houdini://graph/subgraph/obj/$probeName"
}
Assert-True ($graph.result.contents.Count -ge 1) "graph subgraph resource returned no content."

$packagePreview = Invoke-HpMcp -BaseUrl $BaseUrl -Token $token -Id 5 -Method "tools/call" -Params @{
    name = "package.preview_scene"
    arguments = @{}
}
Assert-True ($packagePreview.result.isError -eq $false) "package.preview_scene failed."

if ($IncludeOptionalDomains) {
    foreach ($resourceUri in @("houdini://scene/events", "houdini://tasks/recent")) {
        $resource = Invoke-HpMcp -BaseUrl $BaseUrl -Token $token -Id 100 -Method "resources/read" -Params @{
            uri = $resourceUri
        }
        Assert-True ($resource.result.contents.Count -ge 1) "Optional resource returned no content: $resourceUri"
    }
}

$delete = Invoke-HpMcp -BaseUrl $BaseUrl -Token $token -Id 6 -Method "tools/call" -Params @{
    name = "node.delete"
    arguments = @{
        path = $probePath
        ignore_missing = $false
    }
}
Assert-True ($delete.result.isError -eq $false) "node.delete failed."

[pscustomobject]@{
    health = $health
    checkedTools = @("scene.get_summary", "node.create", "node.delete", "graph.query", "package.preview_scene")
    probePath = $probePath
    graphResourceUri = "houdini://graph/subgraph/obj/$probeName"
    packagePreviewSummary = $packagePreview.result.structuredContent.summary
    packageDependencySummary = $packagePreview.result.structuredContent.dependencySummary
    optionalDomains = [bool]$IncludeOptionalDomains
    status = "passed"
} | ConvertTo-Json -Depth 20
