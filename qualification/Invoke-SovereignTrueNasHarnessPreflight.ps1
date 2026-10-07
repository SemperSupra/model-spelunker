[CmdletBinding()]
param(
    [string]$TrueNas = "truenas",
    [switch]$NoPublish
)

Set-StrictMode -Version 2
$ErrorActionPreference = "Stop"

$Repo = "SemperSupra/model-spelunker"
$ScriptPath = "qualification/sovereign_truenas_harness_preflight.sh"
$Issue = 139

function Require-Command {
    param([string]$Name)
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "$Name is required."
    }
}

function Write-Utf8NoBom {
    param([string]$Path,[string]$Text)
    $enc = New-Object System.Text.UTF8Encoding($false)
    [IO.File]::WriteAllText($Path,$Text,$enc)
}

Require-Command gh
Require-Command ssh.exe

$sha = (gh api "repos/$Repo/branches/main" --jq ".commit.sha").Trim()
if ($LASTEXITCODE -ne 0 -or $sha.Length -ne 40) {
    throw "Could not resolve exact Model Spelunker main."
}

$payload = gh api --method GET "repos/$Repo/contents/$ScriptPath" -f "ref=$sha" | ConvertFrom-Json
if ($LASTEXITCODE -ne 0 -or -not $payload.content) {
    throw "Could not fetch sovereign harness preflight from Model Spelunker."
}
$bytes = [Convert]::FromBase64String(($payload.content -replace '\s',''))
$script = [Text.Encoding]::UTF8.GetString($bytes)

Write-Host "==> Sovereign TrueNAS harness preflight; no model inference"
$result = ($script | & ssh.exe -o BatchMode=yes -o ConnectTimeout=10 $TrueNas "bash -s" 2>&1) -join [Environment]::NewLine
if ($LASTEXITCODE -ne 0) {
    throw "TrueNAS harness preflight failed."
}

try {
    $doc = $result | ConvertFrom-Json
} catch {
    throw "Harness preflight did not return valid JSON."
}
if ($doc.schema -ne "model-spelunker.sovereign-harness-preflight.v1") {
    throw "Unexpected preflight schema."
}
if ($doc.model_inference_performed -or $doc.credentials_projected -or $doc.persistent_docker_auth_written) {
    throw "Preflight authority boundary was violated."
}
$failed = @($doc.harnesses | Where-Object { $_.state -ne "PASS" })
if ($failed.Count -gt 0) {
    throw "One or more admitted harness artifacts failed preflight."
}

$stamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
$out = Join-Path $env:TEMP ("sovereign-harness-preflight-" + $stamp + ".json")
Write-Utf8NoBom -Path $out -Text ($result + [Environment]::NewLine)

$publication = "NOT_REQUESTED"
if (-not $NoPublish) {
    $body = Join-Path $env:TEMP ("sovereign-harness-preflight-" + $stamp + ".md")
    $indented = (($result -split [Environment]::NewLine) | ForEach-Object { "    " + $_ }) -join [Environment]::NewLine
    $lines = @(
        "## Sovereign TrueNAS admitted-harness preflight",
        "",
        "- Model Spelunker source: " + $sha,
        "- Node: truenas",
        "- Model inference: none",
        "- Persistent credential projection: none",
        "",
        "This is a harness/substrate admission preflight only. It does not qualify a model or actor.",
        "",
        $indented
    )
    Write-Utf8NoBom -Path $body -Text (($lines -join [Environment]::NewLine) + [Environment]::NewLine)
    gh issue comment $Issue --repo $Repo --body-file $body | Out-Host
    if ($LASTEXITCODE -ne 0) {
        throw "Preflight passed locally but publication to issue 139 failed. Result preserved at $out"
    }
    $publication = "ISSUE_139"
}

[pscustomobject]@{
    status = "PASS_HARNESS_PREFLIGHT"
    source_revision = $sha
    result_path = $out
    publication = $publication
    harnesses = @($doc.harnesses | ForEach-Object { $_.harness })
} | ConvertTo-Json -Depth 8
