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

function Invoke-RemoteBashBytes {
    param(
        [string]$HostName,
        [byte[]]$InputBytes
    )

    $ssh = (Get-Command ssh.exe -ErrorAction Stop).Source
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $ssh
    $psi.Arguments = ('-o BatchMode=yes -o ConnectTimeout=10 "{0}" "bash -s"' -f ($HostName -replace '"',''))
    $psi.UseShellExecute = $false
    $psi.RedirectStandardInput = $true
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.CreateNoWindow = $true

    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $psi
    [void]$process.Start()

    $stdoutTask = $process.StandardOutput.ReadToEndAsync()
    $stderrTask = $process.StandardError.ReadToEndAsync()

    $process.StandardInput.BaseStream.Write($InputBytes, 0, $InputBytes.Length)
    $process.StandardInput.BaseStream.Flush()
    $process.StandardInput.Close()

    $process.WaitForExit()

    [pscustomobject]@{
        ExitCode = $process.ExitCode
        Stdout = $stdoutTask.Result
        Stderr = $stderrTask.Result
    }
}

function Sanitize-RemoteError {
    param([string]$Text)

    $safe = [string]$Text
    $safe = [regex]::Replace($safe, '(?i)authorization\s*:\s*bearer\s+\S+', 'Authorization: Bearer [REDACTED]')
    $safe = [regex]::Replace($safe, '(?i)(ghp|gho|github_pat)_[A-Za-z0-9_]+', '[REDACTED_GITHUB_TOKEN]')
    $safe = [regex]::Replace($safe, '(?i)(sk-[A-Za-z0-9_-]{16,})', '[REDACTED_API_KEY]')
    return $safe
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

Write-Host "==> Sovereign TrueNAS harness preflight; no model inference"
$remote = Invoke-RemoteBashBytes -HostName $TrueNas -InputBytes $bytes
if ($remote.ExitCode -ne 0) {
    $err = Join-Path $env:TEMP "sovereign-harness-preflight-stderr.txt"
    $safeError = Sanitize-RemoteError -Text $remote.Stderr
    Write-Utf8NoBom -Path $err -Text $safeError

    $lines = @($safeError -split "[\r\n]+" | Where-Object { $_ -ne "" })
    $tail = if ($lines.Count -gt 40) {
        ($lines[($lines.Count - 40)..($lines.Count - 1)] -join [Environment]::NewLine)
    } else {
        ($lines -join [Environment]::NewLine)
    }

    Write-Host "==> Sanitized remote stderr tail"
    if ($tail) { Write-Host $tail }

    throw "TrueNAS harness preflight failed with exit code $($remote.ExitCode). Sanitized remote stderr preserved locally at $err"
}
$result = $remote.Stdout.Trim()

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
