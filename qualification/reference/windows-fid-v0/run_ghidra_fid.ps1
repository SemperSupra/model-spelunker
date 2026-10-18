# Explicit source-known Windows MSVC Ghidra 12.1.4 FID trial, no unknown binaries.
param([string] $OutputDir = (Join-Path $env:RUNNER_TEMP 're-windows-msvc-v0'))
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$OutputDir = (Resolve-Path $OutputDir).Path
$reference = Join-Path $OutputDir 'reference_labeled.dll'
$target = Join-Path $OutputDir 'target_stripped.dll'
if (-not (Test-Path $reference) -or -not (Test-Path $target)) {
  throw 'SOURCE_KNOWN_WINDOWS_DLLS_NOT_READY'
}
$scriptPath = (Resolve-Path (Join-Path $PSScriptRoot '..\..\tools\ghidra')).Path
$srcFile = Join-Path $PSScriptRoot 'windows_reference.c'
$srcSha = (Get-FileHash $srcFile -Algorithm SHA256).Hash.ToLower()
$asset = Join-Path $OutputDir 'ghidra_12.1.4_PUBLIC_20260921.zip'
$expected = 'ddac49f903da9d5bac833e5cc79395098b9c33cfd3279be5f31bd00387d2d4db'
$url = 'https://github.com/NationalSecurityAgency/ghidra/releases/download/Ghidra_12.1.4_build/ghidra_12.1.4_PUBLIC_20260921.zip'
$ghidraHome = Join-Path $OutputDir 'ghidra_12.1.4_PUBLIC'
$headless = Join-Path $ghidraHome 'support\analyzeHeadless.bat'
if (-not (Test-Path $headless)) {
  Invoke-WebRequest -Uri $url -OutFile $asset -MaximumRedirection 5 -TimeoutSec 270
  $actual = (Get-FileHash $asset -Algorithm SHA256).Hash.ToLower()
  if ($actual -ne $expected) { throw 'GHIDRA_RELEASE_HASH_MISMATCH' }
  Expand-Archive -Path $asset -DestinationPath $OutputDir
  Remove-Item $asset
}
if (-not (Test-Path $headless)) { throw 'GHIDRA_HEADLESS_MISSING' }
$fidHome = Join-Path $ghidraHome 'Ghidra\Features\FunctionID\data'
if (-not (Test-Path $fidHome)) { throw 'GHIDRA_SHIPPED_FID_HOME_MISSING' }
$records = @(
  Get-ChildItem $fidHome -Recurse -File |
  Where-Object { $_.Extension -in '.fidb','.fidbf' } |
  ForEach-Object {
    @{
      name = $_.Name
      relative_path = $_.FullName.Substring($ghidraHome.Length + 1)
      bytes = $_.Length
      sha256 = (Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLower()
    }
  }
)
@{schema_version=1;ghidra='12.1.4';source_sha256=$srcSha;
  archive_count=$records.Count;shipped_fid=$records} |
  ConvertTo-Json -Depth 5 |
  Set-Content (Join-Path $OutputDir 'ghidra-shipped-fid.json') -Encoding utf8
if ($records.Count -lt 1) { throw 'GHIDRA_NO_SHIPPED_FID' }
$project = Join-Path $OutputDir 'ghidra-project'
$ghidraLog = Join-Path $OutputDir 'ghidra-logs'
New-Item -ItemType Directory -Path $project -Force | Out-Null
New-Item -ItemType Directory -Path $ghidraLog -Force | Out-Null
$family = 'windows-msvc-v14-51'
$db = Join-Path $OutputDir 'source-known-windows.fidb'
$env:GHIDRA_HEADLESS_MAXMEM = '2G'
function Invoke-Headless {
  param([string] $Label, [string[]] $Arguments)
  $logPath = Join-Path $ghidraLog ($Label + '.console.log')
  & $headless $project 'REWindowsMSVC' @Arguments 2>&1 | Tee-Object -FilePath $logPath
  if ($LASTEXITCODE -ne 0) {
    throw ("GHIDRA_{0}_FAILED:{1}" -f $Label, $LASTEXITCODE)
  }
}
Invoke-Headless -Label 'import-reference' -Arguments @(
  '-import',$reference,'-max-cpu','2','-analysisTimeoutPerFile','90',
  '-log',(Join-Path $ghidraLog 'import-ref.log'),
  '-scriptlog',(Join-Path $ghidraLog 'import-ref-scripts.log')
)
Invoke-Headless -Label 'create-fid' -Arguments @(
  '-process','reference_labeled.dll','-readOnly','-noanalysis','-max-cpu','2',
  '-scriptPath',$scriptPath,
  '-postScript','BuildSourceKnownFid.java',$db,$family,
  '-log',(Join-Path $ghidraLog 'create-fid.log'),
  '-scriptlog',(Join-Path $ghidraLog 'create-fid-scripts.log')
)
if (-not (Test-Path $db)) { throw 'REFERENCE_FID_NOT_CREATED' }
Invoke-Headless -Label 'import-target' -Arguments @(
  '-import',$target,'-max-cpu','2','-analysisTimeoutPerFile','90',
  '-log',(Join-Path $ghidraLog 'import-target.log'),
  '-scriptlog',(Join-Path $ghidraLog 'import-target-scripts.log')
)
Invoke-Headless -Label 'query-fid' -Arguments @(
  '-process','target_stripped.dll','-readOnly','-noanalysis','-max-cpu','2',
  '-scriptPath',$scriptPath,
  '-postScript','QuerySourceKnownFid.java',$family,$db,
  '-log',(Join-Path $ghidraLog 'query-fid.log'),
  '-scriptlog',(Join-Path $ghidraLog 'query-fid-scripts.log')
)
$created = Get-Content (Join-Path $ghidraLog 'create-fid.console.log') -Raw
$queried = Get-Content (Join-Path $ghidraLog 'query-fid.console.log') -Raw
if ($created -notmatch 'RE_FID_ADDED=(\d+)') { throw 'FID_CREATION_RECEIPT_MISSING' }
$added = [int] $Matches[1]
if ($added -le 0) { throw 'FID_CREATION_EMPTY' }
if ($queried -notmatch 'RE_FID_TARGET_MATCHES=(\d+)') { throw 'FID_QUERY_RECEIPT_MISSING' }
$matched = [int] $Matches[1]
if ($queried -notmatch 'RE_FID_TARGET_DECOY=(\d+)') { throw 'FID_DECOY_RECEIPT_MISSING' }
$decoys = [int] $Matches[1]
if ($decoys -gt 0) { throw ("FID_FALSE_ATTRIBUTION_DECOY:{0}" -f $decoys) }
$receipt = @{
  schema_version = 1
  status = $(if ($matched -gt 0) { 'FID_MATCHES_OBSERVED' } else { 'FID_NO_MATCHES' })
  reference_functions_ingested = $added
  matched_functions = $matched
  decoy_matches = $decoys
  source_sha256 = $srcSha
  reference_pe_sha256 = (Get-FileHash $reference -Algorithm SHA256).Hash.ToLower()
  target_pe_sha256 = (Get-FileHash $target -Algorithm SHA256).Hash.ToLower()
  fid_database_sha256 = (Get-FileHash $db -Algorithm SHA256).Hash.ToLower()
  shipped_fid_databases = $records.Count
  fid_family = $family
  qualified_actor = $false
}
$receipt | ConvertTo-Json -Depth 4 | Set-Content (Join-Path $OutputDir 'fid-msvc-receipt.json') -Encoding utf8
$receipt | ConvertTo-Json -Compress
if ($matched -le 0) { throw 'FID_NO_POSITIVE_TARGET_MATCH' }
