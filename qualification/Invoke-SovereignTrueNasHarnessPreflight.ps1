[CmdletBinding()]
param(
    [string]$TrueNas = "truenas",
    [switch]$NoPublish
)

Set-StrictMode -Version 2
$ErrorActionPreference = "Stop"

$Repo = "SemperSupra/model-spelunker"
$ScriptPath = "qualification/sovereign_truenas_harness_preflight.sh"
$HelperPath = "qualification/hydrate_oci_layout.py"
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

function Sanitize-RemoteError {
    param([string]$Text)
    $safe = [string]$Text
    $safe = [regex]::Replace($safe, '(?i)authorization\s*:\s*bearer\s+\S+', 'Authorization: Bearer [REDACTED]')
    $safe = [regex]::Replace($safe, '(?i)(ghp|gho|github_pat)_[A-Za-z0-9_]+', '[REDACTED_GITHUB_TOKEN]')
    $safe = [regex]::Replace($safe, '(?i)(sk-[A-Za-z0-9_-]{16,})', '[REDACTED_API_KEY]')
    return $safe
}

function Invoke-SshCapture {
    param(
        [string]$HostName,
        [string]$RemoteCommand
    )

    $ssh = (Get-Command ssh.exe -ErrorAction Stop).Source
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $ssh
    $escapedCommand = $RemoteCommand.Replace('"','\"')
    $psi.Arguments = '-o BatchMode=yes -o ConnectTimeout=10 "' + $HostName + '" "' + $escapedCommand + '"'
    $psi.UseShellExecute = $false
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.CreateNoWindow = $true

    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $psi
    [void]$process.Start()

    $stdoutTask = $process.StandardOutput.ReadToEndAsync()
    $stderrTask = $process.StandardError.ReadToEndAsync()
    $process.WaitForExit()

    [pscustomobject]@{
        ExitCode = $process.ExitCode
        Stdout = $stdoutTask.Result
        Stderr = $stderrTask.Result
    }
}

Require-Command gh
Require-Command ssh.exe
Require-Command scp.exe

$sha = (gh api "repos/$Repo/branches/main" --jq ".commit.sha").Trim()
if ($LASTEXITCODE -ne 0 -or $sha.Length -ne 40) {
    throw "Could not resolve exact Model Spelunker main."
}

$payload = gh api --method GET "repos/$Repo/contents/$ScriptPath" -f "ref=$sha" | ConvertFrom-Json
if ($LASTEXITCODE -ne 0 -or -not $payload.content) {
    throw "Could not fetch sovereign harness preflight from Model Spelunker."
}
$helperPayload = gh api --method GET "repos/$Repo/contents/$HelperPath" -f "ref=$sha" | ConvertFrom-Json
if ($LASTEXITCODE -ne 0 -or -not $helperPayload.content) {
    throw "Could not fetch OCI hydration helper from Model Spelunker."
}

[byte[]]$bytes = [Convert]::FromBase64String(($payload.content -replace '\s',''))
if ($bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF) {
    [byte[]]$bytes = $bytes[3..($bytes.Length - 1)]
}
[byte[]]$helperBytes = [Convert]::FromBase64String(($helperPayload.content -replace '\s',''))
if ($helperBytes.Length -ge 3 -and $helperBytes[0] -eq 0xEF -and $helperBytes[1] -eq 0xBB -and $helperBytes[2] -eq 0xBF) {
    [byte[]]$helperBytes = $helperBytes[3..($helperBytes.Length - 1)]
}

$work = Join-Path $env:TEMP ("model-spelunker-preflight-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Force -Path $work | Out-Null
$localScript = Join-Path $work "preflight.sh"
$localHelper = Join-Path $work "hydrate_oci_layout.py"
[IO.File]::WriteAllBytes($localScript, $bytes)
[IO.File]::WriteAllBytes($localHelper, $helperBytes)

$remoteDir = $null
$sshBase = @("-o","BatchMode=yes","-o","ConnectTimeout=10",$TrueNas)

try {
    Write-Host "==> Verify native TrueNAS GitHub CLI"
    $ghCheck = @(& ssh.exe @sshBase 'PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin:$PATH"; command -v gh; gh --version | head -n 1; gh auth status >/dev/null')
    if ($LASTEXITCODE -ne 0) {
        throw "TrueNAS gh is missing from ~/.local/bin or is not authenticated."
    }
    $ghCheck | ForEach-Object { if ($_){ Write-Host $_ } }

    Write-Host "==> Stage exact preflight script by SCP"
    $remoteDir = (& ssh.exe @sshBase "mktemp -d -t model-spelunker-preflight.XXXXXX").Trim()
    if ($LASTEXITCODE -ne 0 -or -not $remoteDir) {
        throw "Could not create temporary TrueNAS preflight directory."
    }

    $destination = $TrueNas + ":" + $remoteDir + "/"
    $scpArgs = @("-q","-o","BatchMode=yes","-o","ConnectTimeout=10",$localScript,$localHelper,$destination)
    & scp.exe @scpArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Could not transfer preflight tooling to TrueNAS."
    }

    Write-Host "==> Sovereign TrueNAS harness preflight; no model inference"
    $remoteScript = $remoteDir + "/preflight.sh"
    $remoteCommand = 'chmod 700 ' + "'" + $remoteScript + "'" + '; bash ' + "'" + $remoteScript + "'"

    $remoteResult = Invoke-SshCapture -HostName $TrueNas -RemoteCommand $remoteCommand
    $rc = $remoteResult.ExitCode
    $stdout = ([string]$remoteResult.Stdout).Trim()
    $stderr = [string]$remoteResult.Stderr

    if ($rc -ne 0) {
        $safeError = Sanitize-RemoteError -Text $stderr
        $safePath = Join-Path $env:TEMP "sovereign-harness-preflight-stderr.txt"
        Write-Utf8NoBom -Path $safePath -Text $safeError

        $lines = @($safeError -split "[\r\n]+" | Where-Object { $_ -ne "" })
        $tail = if ($lines.Count -gt 40) {
            ($lines[($lines.Count - 40)..($lines.Count - 1)] -join [Environment]::NewLine)
        } else {
            ($lines -join [Environment]::NewLine)
        }

        Write-Host "==> Sanitized remote stderr tail"
        if ($tail) { Write-Host $tail }
        if ($stdout) {
            Write-Host "==> Remote stdout"
            Write-Host $stdout
        }
        throw "TrueNAS harness preflight failed with exit code $rc. Sanitized stderr preserved locally at $safePath"
    }

    try {
        $doc = $stdout | ConvertFrom-Json
    } catch {
        throw "Harness preflight returned success but stdout was not valid JSON."
    }

    if ($doc.schema -ne "model-spelunker.sovereign-harness-preflight.v1") {
        throw "Unexpected preflight schema: $($doc.schema)"
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
    Write-Utf8NoBom -Path $out -Text ($stdout + [Environment]::NewLine)

    $publication = "NOT_REQUESTED"
    if (-not $NoPublish) {
        $body = Join-Path $work ("sovereign-harness-preflight-" + $stamp + ".md")
        $indented = (($stdout -split "[\r\n]+") | ForEach-Object { "    " + $_ }) -join [Environment]::NewLine
        $lines = @(
            "## Sovereign TrueNAS admitted-harness preflight",
            "",
            "- Model Spelunker source: " + $sha,
            "- Node: truenas",
            "- Model inference: none",
            "- Registry authentication: native TrueNAS gh -> temporary regctl auth",
            "- Artifact transport: rootless regctl -> OCI layout",
            "- Docker daemon/socket/sudo: not used",
            "- Credential values projected: none",
            "",
            "This is harness/substrate admission evidence only. It does not qualify a model or configured actor.",
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
}
finally {
    if ($remoteDir) {
        & ssh.exe @sshBase "rm -rf '$remoteDir'" 2>$null | Out-Null
    }
    if (Test-Path $work) {
        Remove-Item -LiteralPath $work -Recurse -Force
    }
}
