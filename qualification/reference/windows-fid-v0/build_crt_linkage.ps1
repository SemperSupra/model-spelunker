# Source-known CRT consumer compiled with native Microsoft cl/link /MT vs /MD.
# Never execute either PE. Validate link-map and import evidence independently.
param([string] $OutputDir = (Join-Path $env:RUNNER_TEMP 're-msvc-crt-linkage-v0'))
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
$OutputDir=(Resolve-Path $OutputDir).Path
$vswhere = Join-Path ([Environment]::GetFolderPath('ProgramFilesX86')) 'Microsoft Visual Studio\Installer\vswhere.exe'
if (-not (Test-Path $vswhere)) { throw 'VSWHERE_MISSING' }
$vs=(& $vswhere -latest -products '*' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath | Select-Object -First 1)
if (-not $vs) { throw 'MSVC_NOT_INSTALLED' }
$vsdev=Join-Path $vs 'Common7\Tools\VsDevCmd.bat'
$src=Join-Path $PSScriptRoot 'windows_crt_consumer.c'
$batch = @"
@echo off
call "$vsdev" -no_logo -arch=amd64 -host_arch=amd64 >nul
if errorlevel 1 exit /b 10
cl /nologo /c /O2 /Gy /GS- /MT /Fo"$OutputDir\crt_static.obj" "$src"
if errorlevel 1 exit /b 11
link /nologo /SUBSYSTEM:CONSOLE /MACHINE:X64 /INCREMENTAL:NO /OPT:REF /OPT:ICF /OUT:"$OutputDir\crt_static.exe" /MAP:"$OutputDir\crt_static.map" /VERBOSE:LIB "$OutputDir\crt_static.obj" > "$OutputDir\crt_static-link.log" 2>&1
if errorlevel 1 exit /b 12
cl /nologo /c /O2 /Gy /GS- /MD /Fo"$OutputDir\crt_dynamic.obj" "$src"
if errorlevel 1 exit /b 13
link /nologo /SUBSYSTEM:CONSOLE /MACHINE:X64 /INCREMENTAL:NO /OPT:REF /OPT:ICF /OUT:"$OutputDir\crt_dynamic.exe" /MAP:"$OutputDir\crt_dynamic.map" /VERBOSE:LIB "$OutputDir\crt_dynamic.obj" > "$OutputDir\crt_dynamic-link.log" 2>&1
if errorlevel 1 exit /b 14
dumpbin /nologo /imports "$OutputDir\crt_static.exe" > "$OutputDir\crt_static-imports.txt"
if errorlevel 1 exit /b 15
dumpbin /nologo /imports "$OutputDir\crt_dynamic.exe" > "$OutputDir\crt_dynamic-imports.txt"
if errorlevel 1 exit /b 16
dumpbin /nologo /dependents "$OutputDir\crt_static.exe" > "$OutputDir\crt_static-dependents.txt"
if errorlevel 1 exit /b 17
dumpbin /nologo /dependents "$OutputDir\crt_dynamic.exe" > "$OutputDir\crt_dynamic-dependents.txt"
if errorlevel 1 exit /b 18
exit /b 0
"@
$path=Join-Path $OutputDir 'compile-variants.cmd'
Set-Content $path -Value $batch -Encoding ascii
cmd.exe /d /c ('"' + $path + '"')
if ($LASTEXITCODE -ne 0) { throw ("CRT_VARIANT_NATIVE_BUILD_FAILED:{0}" -f $LASTEXITCODE) }
python (Join-Path $PSScriptRoot 'verify_crt_linkage.py') --root $OutputDir
if ($LASTEXITCODE -ne 0) { throw 'CRT_LINKAGE_ORACLE_FAILED' }
