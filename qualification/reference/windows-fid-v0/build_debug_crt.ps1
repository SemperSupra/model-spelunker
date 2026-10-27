# W-5a source-owned DEBUG CRT (/MTd) vs established release CRT (/MT).
# Native producer-only preflight. Never execute generated Windows PE.
param([string] $OutputDir = (Join-Path $env:RUNNER_TEMP 're-msvc-crt-linkage-v0'))
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$OutputDir = (Resolve-Path $OutputDir).Path
if (-not (Test-Path (Join-Path $OutputDir 'crt-linkage-receipt.json'))) {
  throw 'W5_RELEASE_PRODUCER_ORACLE_REQUIRED'
}
$vswhere=Join-Path ([Environment]::GetFolderPath('ProgramFilesX86')) 'Microsoft Visual Studio\Installer\vswhere.exe'
if (-not (Test-Path $vswhere)) { throw 'W5_VSWHERE_NOT_INSTALLED' }
$vs=(& $vswhere -latest -products '*' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath | Select-Object -First 1)
if (-not $vs) { throw 'W5_MSVC_NOT_INSTALLED' }
$vsdev=Join-Path $vs 'Common7\Tools\VsDevCmd.bat'
$src=Join-Path $PSScriptRoot 'windows_crt_consumer.c'
$batch=@"
@echo off
call "$vsdev" -no_logo -arch=amd64 -host_arch=amd64 >nul
if errorlevel 1 exit /b 10
cl /nologo /c /O2 /Gy /GS- /MTd /Fo"$OutputDir\crt_debug.obj" "$src"
if errorlevel 1 exit /b 11
link /nologo /SUBSYSTEM:CONSOLE /MACHINE:X64 /INCREMENTAL:NO /OPT:REF /OPT:ICF /OUT:"$OutputDir\crt_debug.exe" /MAP:"$OutputDir\crt_debug.map" /VERBOSE:LIB "$OutputDir\crt_debug.obj" > "$OutputDir\crt_debug-link.log" 2>&1
if errorlevel 1 exit /b 12
dumpbin /nologo /imports "$OutputDir\crt_debug.exe" > "$OutputDir\crt_debug-imports.txt"
if errorlevel 1 exit /b 13
exit /b 0
"@
$path=Join-Path $OutputDir 'compile-debug-crt.cmd'
Set-Content $path -Value $batch -Encoding ascii
cmd.exe /d /c ('"' + $path + '"')
if ($LASTEXITCODE -ne 0) { throw ("W5_DEBUG_CRT_NATIVE_BUILD_FAILED:{0}" -f $LASTEXITCODE) }
python (Join-Path $PSScriptRoot 'verify_debug_crt.py') --root $OutputDir
if ($LASTEXITCODE -ne 0) { throw 'W5_DEBUG_CRT_PRODUCER_ORACLE_FAILED' }
