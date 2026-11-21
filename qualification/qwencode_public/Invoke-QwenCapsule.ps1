#requires -Version 5.1
<#
Generic PUBLIC-SAFE Qwen Code portable payload reconciler.
Only run Apply within a separate disposable guest/workcell.
This script does not create VMs, issue credentials, alter host configuration,
install a global package, start services, or grant production authority.

SyntheticCI is designed only for ephemeral GitHub Actions runner qualification.
Production is deliberately denied here until a separately authenticated,
controller-owned workcell adapter is independently qualified.
#>
[CmdletBinding()]
param(
    [ValidateSet('Observe','Plan','Apply','Verify','Rollback')]
    [string]$Phase = 'Observe',
    [Parameter(Mandatory=$true)][string]$ManifestPath,
    [string]$ArchivePath = '',
    [string]$Root = (Join-Path $env:TEMP 'qwen-disposable-capsule'),
    [string]$ApprovePlanSha256 = '',
    [ValidateSet('Production','SyntheticCI')][string]$Mode = 'Production',
    [string]$AdmissionReceiptPath = '',
    [string]$AdmissionVerifierPath = ''
)
Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

function Require([bool]$Condition, [string]$Reason) {
    if(-not $Condition) { throw $Reason }
}
function LoadJson([string]$Path) {
    Require (Test-Path -LiteralPath $Path -PathType Leaf) 'REQUIRED_JSON_MISSING'
    Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
}
function ShaFile([string]$Path) {
    Require (Test-Path -LiteralPath $Path -PathType Leaf) 'ARTIFACT_MISSING'
    (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}
function ShaText([string]$Value) {
    $alg = [Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [Text.Encoding]::UTF8.GetBytes($Value)
        ([BitConverter]::ToString($alg.ComputeHash($bytes))).Replace('-','').ToLowerInvariant()
    } finally { $alg.Dispose() }
}
function ToJson($Object) {
    ConvertTo-Json -InputObject $Object -Depth 12 -Compress
}
function NoReparse([string]$Path) {
    if(Test-Path -LiteralPath $Path) {
        $obj = Get-Item -LiteralPath $Path -Force
        Require (($obj.Attributes -band [IO.FileAttributes]::ReparsePoint) -eq 0) 'REPARSE_POINT_FORBIDDEN'
    }
}
function IsVM {
    try {
        $sys = Get-CimInstance Win32_ComputerSystem
        return ($sys.Model -match '(?i)virtual|vmware|kvm|hvm|hyper-v' -or
                $sys.Manufacturer -match '(?i)vmware|qemu|xen')
    } catch { return $false }
}
function RequireWorkcell([string]$Plan) {
    if($Mode -eq 'SyntheticCI') {
        Require ($env:GITHUB_ACTIONS -eq 'true' -and $env:CI -eq 'true') 'SYNTHETIC_CI_ONLY'
        return
    }
    # Synthetic public packaging qualification is the only authority accepted
    # by this standalone capsule. A user-provided verifier executable path
    # cannot prove trusted-controller identity or an authenticated lease.
    # Actual guest production admission belongs to Agent Dispatch and its
    # independently pinned controller. Do not execute caller-controlled
    # verifier programs to manufacture a successful admission receipt.
    throw 'PRODUCTION_REQUIRES_EXTERNAL_TRUSTED_CONTROLLER_INTEGRATION_NOT_IMPLEMENTED'
}
function CheckZipSafety([string]$ZipPath) {
    Add-Type -AssemblyName System.IO.Compression
    $file = [IO.File]::OpenRead($ZipPath)
    try {
        $zip = New-Object IO.Compression.ZipArchive($file, [IO.Compression.ZipArchiveMode]::Read)
        try {
            $seen = @{}
            [long]$size = 0
            foreach($item in $zip.Entries) {
                $name = [string]$item.FullName
                Require ($name.Length -gt 0 -and (-not $name.Contains('\'))) 'UNSAFE_ZIP_PATH'
                $clean = $name.TrimEnd('/')
                Require ($clean.Length -gt 0 -and (-not $clean.StartsWith('/'))) 'UNSAFE_ZIP_PATH'
                $parts = $clean.Split('/')
                foreach($part in $parts) {
                    Require ($part -ne '..' -and $part -ne '.' -and $part -ne '') 'UNSAFE_ZIP_PATH'
                }
                Require (-not $parts[0].Contains(':')) 'UNSAFE_ZIP_PATH'
                $key = $clean.ToLowerInvariant()
                Require (-not $seen.ContainsKey($key)) 'DUPLICATE_ZIP_PATH'
                $seen[$key] = $true
                $kind = ($item.ExternalAttributes -shr 16) -band 61440
                Require ($kind -ne 40960) 'SYMLINK_ZIP_PATH'
                $size += $item.Length
                Require ($size -lt 700000000) 'ZIP_EXPANSION_LIMIT'
            }
        } finally { $zip.Dispose() }
    } finally { $file.Dispose() }
}
function ManifestEntry($Manifest) {
    Require ($Manifest.schema -eq 'qwencode-public-release/v1') 'WRONG_MANIFEST_SCHEMA'
    Require ($Manifest.upstream -eq 'QwenLM/qwen-code') 'WRONG_UPSTREAM'
    Require ($Manifest.upstream_ref -eq ('v' + [string]$Manifest.version)) 'WRONG_UPSTREAM_VERSION'
    Require ($Manifest.platforms.PSObject.Properties.Name -contains 'windows-x64') 'WINDOWS_RELEASE_MISSING'
    $entry = $Manifest.platforms.'windows-x64'
    Require ($entry.asset -eq 'qwen-code-win-x64.zip' -and $entry.format -eq 'zip') 'WINDOWS_ASSET_NOT_PINNED'
    Require (([string]$entry.sha256) -cmatch '^[0-9a-f]{64}$') 'RELEASE_DIGEST_MISSING'
    return $entry
}
function OwnerMatches([string]$Directory, [string]$Plan) {
    if(-not (Test-Path -LiteralPath $Directory -PathType Container)) { return $false }
    NoReparse $Directory
    $p = Join-Path $Directory 'owner.json'
    if(-not (Test-Path -LiteralPath $p -PathType Leaf)) { return $false }
    NoReparse $p
    $marker = LoadJson $p
    return ($marker.schema -eq 'qwencode-public-owner/v1' -and
            $marker.plan -ceq $Plan -and
            $marker.workset -eq 'public-synthetic-qwen-capsule')
}
function RunVersion([string]$Directory, [string]$Version) {
    $bin = Join-Path $Directory 'qwen-code\bin\qwen.cmd'
    Require (Test-Path -LiteralPath $bin -PathType Leaf) 'QWEN_COMMAND_MISSING'
    $output = (& $bin --version 2>&1 | Out-String).Trim()
    Require ($LASTEXITCODE -eq 0 -and $output.Contains($Version)) 'QWEN_VERSION_MISMATCH'
    return $output
}
function VerifyInstalled([string]$Directory, [string]$Plan, [string]$Version) {
    Require (OwnerMatches $Directory $Plan) 'FOREIGN_OR_MISSING_OWNER'
    $marker = LoadJson (Join-Path $Directory 'owner.json')
    $cli = Join-Path $Directory 'qwen-code\lib\cli.js'
    Require ((ShaFile $cli) -ceq $marker.cliSha256) 'INSTALLED_CLI_TAINT'
    $output = RunVersion $Directory $Version
    return $output
}

$manifest = LoadJson $ManifestPath
$entry = ManifestEntry $manifest
Require (-not $Root.StartsWith('\\')) 'UNC_WORKROOT_FORBIDDEN'
$Root = [IO.Path]::GetFullPath($Root)
$systemRoot = [IO.Path]::GetPathRoot($Root)
Require ($Root.Length -gt ($systemRoot.Length + 10)) 'WORKROOT_TOO_BROAD'
$forbidden = @($env:SystemRoot, $env:ProgramFiles, $env:USERPROFILE)
foreach($x in $forbidden) {
    if($x) {
        Require ($Root.TrimEnd('\') -ine ([IO.Path]::GetFullPath($x)).TrimEnd('\')) 'PERSISTENT_ROOT_FORBIDDEN'
    }
}
NoReparse $Root
$desiredArchive = if($ArchivePath) { [IO.Path]::GetFullPath($ArchivePath) } else { '' }
$planSeed = 'qwencode-public-plan/v1|' + [string]$manifest.version + '|' +
            [string]$entry.sha256 + '|' + $Root.ToLowerInvariant()
$plan = ShaText $planSeed
$active = Join-Path $Root 'active'
$stage = Join-Path $Root ('stage-' + $plan.Substring(0,12))
$validInput = $false
$blocking = @()
if(-not $desiredArchive -or -not (Test-Path -LiteralPath $desiredArchive -PathType Leaf)) {
    $blocking += 'ARCHIVE_MISSING'
} else {
    try {
        if((ShaFile $desiredArchive) -cne [string]$entry.sha256) {
            $blocking += 'ARCHIVE_HASH_MISMATCH'
        } else {
            CheckZipSafety $desiredArchive
            $validInput = $true
        }
    } catch { $blocking += 'UNSAFE_OR_UNREADABLE_ARCHIVE' }
}
if(Test-Path -LiteralPath $stage) { $blocking += 'INCOMPLETE_STAGE' }
if((Test-Path -LiteralPath $active) -and -not (OwnerMatches $active $plan)) { $blocking += 'FOREIGN_ACTIVE' }
switch($Phase) {
    'Observe' {
        ToJson ([ordered]@{phase='observe';planSha256=$plan;synthetic=($Mode -eq 'SyntheticCI');
            isVirtualMachine=(IsVM);psVersion=[string]$PSVersionTable.PSVersion;
            archivePresent=($desiredArchive -and (Test-Path -LiteralPath $desiredArchive -PathType Leaf));
            existingActive=(Test-Path -LiteralPath $active);
            installedTools='UNKNOWN_NO_INSTALL';hostMutation='NONE'})
        break
    }
    'Plan' {
        $state = if($blocking.Count -gt 0) {'BLOCKED'} elseif(OwnerMatches $active $plan) {'NOOP'} else {'CREATE'}
        ToJson ([ordered]@{phase='plan';planSha256=$plan;state=$state;blockers=@($blocking);
            version=[string]$manifest.version;sourceSha256=[string]$entry.sha256;
            productionRequiresExternalAdmission=$true;rootClass='GUEST_ONLY'})
        break
    }
    'Apply' {
        Require ($ApprovePlanSha256 -ceq $plan) 'PLAN_APPROVAL_MISMATCH'
        RequireWorkcell $plan
        Require $validInput 'PINNED_ARCHIVE_NOT_VERIFIED'
        Require (-not (Test-Path -LiteralPath $stage)) 'INCOMPLETE_STAGE_REQUIRES_ROLLBACK'
        if(Test-Path -LiteralPath $active) {
            $actual = VerifyInstalled $active $plan ([string]$manifest.version)
            ToJson @{phase='apply';result='NOOP_VERIFIED';planSha256=$plan;version=$actual}
            break
        }
        Require ($blocking.Count -eq 0) 'PLAN_BLOCKED'
        [void](New-Item -ItemType Directory -Path $Root -Force)
        [void](New-Item -ItemType Directory -Path $stage)
        # Ownership marker is written BEFORE extraction so interrupted stages
        # can be safely recognized by the exact plan's rollback operation.
        $marker = [ordered]@{schema='qwencode-public-owner/v1';
            workset='public-synthetic-qwen-capsule';plan=$plan;sourceSha256=[string]$entry.sha256;
            cliSha256='PENDING';mode=$Mode}
        [IO.File]::WriteAllText((Join-Path $stage 'owner.json'),(ToJson $marker),(New-Object Text.UTF8Encoding($false)))
        Expand-Archive -LiteralPath $desiredArchive -DestinationPath $stage -Force
        $cli = Join-Path $stage 'qwen-code\lib\cli.js'
        $marker.cliSha256 = ShaFile $cli
        $version = RunVersion $stage ([string]$manifest.version)
        [IO.File]::WriteAllText((Join-Path $stage 'owner.json'),(ToJson $marker),(New-Object Text.UTF8Encoding($false)))
        Move-Item -LiteralPath $stage -Destination $active
        ToJson @{phase='apply';result='APPLIED_GUEST_ONLY';planSha256=$plan;version=$version;synthetic=($Mode -eq 'SyntheticCI')}
        break
    }
    'Verify' {
        Require $validInput 'PINNED_ARCHIVE_NOT_VERIFIED'
        $version = VerifyInstalled $active $plan ([string]$manifest.version)
        ToJson @{phase='verify';result='LOCAL_PAYLOAD_PASS';planSha256=$plan;version=$version;
                 providerRoute='NOT_TESTED';productionAdmission='NOT_TESTED'}
        break
    }
    'Rollback' {
        Require ($ApprovePlanSha256 -ceq $plan) 'PLAN_APPROVAL_MISMATCH'
        RequireWorkcell $plan
        foreach($directory in @($stage,$active)) {
            if(Test-Path -LiteralPath $directory) {
                Require (OwnerMatches $directory $plan) 'REFUSE_REMOVE_UNOWNED_RESOURCE'
                Remove-Item -LiteralPath $directory -Recurse -Force
            }
        }
        ToJson @{phase='rollback';result='OWNED_GENERATION_ABSENT';planSha256=$plan}
        break
    }
}
