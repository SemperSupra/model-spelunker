# Bounded one-shot Ghidra official built-in Visual Studio FID matching experiment.
# Uses only our self-authored /MT and /MD PE; no third-party FID creation.
param([string] $OutputDir = (Join-Path $env:RUNNER_TEMP 're-msvc-crt-linkage-v0'), [switch]$IncludeHeldout, [switch]$IncludeDebug)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$OutputDir=(Resolve-Path $OutputDir).Path
if (-not (Test-Path (Join-Path $OutputDir 'crt-linkage-receipt.json'))) {
  throw 'INDEPENDENT_MSVC_PRODUCER_ORACLE_REQUIRED'
}
$asset=Join-Path $OutputDir 'ghidra_12.1.4_PUBLIC_20260921.zip'
$expected='ddac49f903da9d5bac833e5cc79395098b9c33cfd3279be5f31bd00387d2d4db'
$ghidraHome=Join-Path $OutputDir 'ghidra_12.1.4_PUBLIC'
$headless=Join-Path $ghidraHome 'support\analyzeHeadless.bat'
if (-not (Test-Path $headless)) {
  Invoke-WebRequest -Uri 'https://github.com/NationalSecurityAgency/ghidra/releases/download/Ghidra_12.1.4_build/ghidra_12.1.4_PUBLIC_20260921.zip' -OutFile $asset -TimeoutSec 270
  $digest=(Get-FileHash $asset -Algorithm SHA256).Hash.ToLower()
  if ($digest -ne $expected) { throw 'GHIDRA_1214_HASH_MISMATCH' }
  Expand-Archive -Path $asset -DestinationPath $OutputDir
  Remove-Item $asset
}
if (-not (Test-Path $headless)) { throw 'GHIDRA_HEADLESS_MISSING' }
$project=Join-Path $OutputDir 'crt-fid-project'
$logdir=Join-Path $OutputDir 'ghidra-fid'
New-Item -ItemType Directory -Path $project,$logdir -Force | Out-Null
$scripts=(Resolve-Path (Join-Path $PSScriptRoot '..\..\tools\ghidra')).Path
$env:GHIDRA_HEADLESS_MAXMEM='2G'
$records=@(Get-ChildItem (Join-Path $ghidraHome 'Ghidra\Features\FunctionID\data') -Recurse -File |
    Where-Object { $_.Extension -in '.fidbf','.fidb' } |
    ForEach-Object { @{
      name=$_.Name
      bytes=$_.Length
      sha256=(Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLower()
    } })
@{schema=1;ghidra='12.1.4';fid_count=$records.Count;fid=$records} |
  ConvertTo-Json -Depth 5 | Set-Content (Join-Path $OutputDir 'ghidra-shipped-fid-census.json') -Encoding utf8
if ($records.Count -le 0) { throw 'NO_SHIPPED_FID_REFERENCES' }
function Invoke-Ghidra {
  param([string]$Name,[string[]]$Argv)
  $out=Join-Path $logdir ($Name+'.console.log')
  & $headless $project 'RECRTLinkages' @Argv 2>&1 | Tee-Object -FilePath $out
  if ($LASTEXITCODE -ne 0) {throw ("GHIDRA_{0}_EXIT_{1}" -f $Name,$LASTEXITCODE)}
}
$variants=@('static','dynamic')
if ($IncludeHeldout) {
  if (-not (Test-Path (Join-Path $OutputDir 'crt_static_heldout.map'))) {throw 'HELDOUT_MAP_NOT_BUILT'}
  $variants+= 'static_heldout'
}
if ($IncludeDebug) {
  if (-not (Test-Path (Join-Path $OutputDir 'w5-debug-crt-preflight.json'))) {throw 'W5_DEBUG_CRT_PRODUCER_ORACLE_REQUIRED'}
  $variants += 'debug'
}
foreach($flavor in $variants) {
  $image=Join-Path $OutputDir ("crt_"+$flavor+".exe")
  if (-not (Test-Path $image)) { throw 'MISSING_SOURCE_KNOWN_PE' }
  Invoke-Ghidra -Name ("import-"+$flavor) -Argv @(
    '-import',$image,'-max-cpu','2','-analysisTimeoutPerFile','180',
    '-log',(Join-Path $logdir ("import-"+$flavor+".log")),
    '-scriptlog',(Join-Path $logdir ("import-"+$flavor+"-script.log")))
  Invoke-Ghidra -Name ("query-"+$flavor) -Argv @(
    '-process',("crt_"+$flavor+".exe"),'-readOnly','-noanalysis','-max-cpu','2',
    '-scriptPath',$scripts,
    '-postScript','QueryBundledCrtFid.java',$flavor,
    '-log',(Join-Path $logdir ("query-"+$flavor+".log")),
    '-scriptlog',(Join-Path $logdir ("query-"+$flavor+"-script.log")))
}
python (Join-Path $PSScriptRoot 'verify_bundled_crt_fid.py') --root $OutputDir
if ($LASTEXITCODE -ne 0) {throw 'BUNDLED_FID_INDEPENDENT_EVALUATION_FAILED'}
if ($IncludeHeldout -or $IncludeDebug) {
  foreach($flavor in $variants) {
    python (Join-Path $PSScriptRoot 'score_heldout_fid.py') --map (Join-Path $OutputDir ("crt_"+$flavor+".map")) --query-log (Join-Path $logdir ("query-"+$flavor+".console.log")) --treatment $flavor --output (Join-Path $OutputDir ("w4c-score-"+$flavor+".json"))
    if ($LASTEXITCODE -ne 0) {throw ("W4C_ORACLE_FAILED_"+$flavor)}
  }
}
