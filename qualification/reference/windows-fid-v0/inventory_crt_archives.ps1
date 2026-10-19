# Inspect installed Visual Studio 18 native CRT/UCRT/WinSDK archives; metadata only.
param([string] $OutputDir = (Join-Path $env:RUNNER_TEMP 're-windows-msvc-v0'))
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$envPath=Join-Path $OutputDir 'vc-env.txt'
if (-not (Test-Path $envPath)) { throw 'MSVC_VSDEV_ENV_NOT_CAPTURED' }
$entries=@{}
Get-Content $envPath | ForEach-Object {
  if ($_ -match '^(.*?)=(.*)$') { $entries[$Matches[1]]=$Matches[2].Trim() }
}
$vc=Join-Path $entries['VCToolsInstallDir'] 'lib\x64'
$ucrt=Join-Path (Join-Path $entries['WindowsSdkDir'] 'Lib') (Join-Path $entries['WindowsSDKVersion'] 'ucrt\x64')
$um=Join-Path (Join-Path $entries['WindowsSdkDir'] 'Lib') (Join-Path $entries['WindowsSDKVersion'] 'um\x64')
$program=Join-Path $PSScriptRoot 'inventory_crt_archives.py'
& python $program --vc-lib $vc --ucrt-lib $ucrt --um-lib $um --output (Join-Path $OutputDir 'crt-archive-receipt.json')
if ($LASTEXITCODE -ne 0) { throw 'CRT_ARCHIVE_INVENTORY_FAILED' }
