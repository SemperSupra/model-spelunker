# W-4c held-out native MSVC /O1 static CRT variant.
# The native PE is never executed or published. /O2 and /MD references come
# from build_crt_linkage.ps1; independent MAP is for the evaluator only.
param([string]$OutputDir=(Join-Path $env:RUNNER_TEMP 're-msvc-crt-linkage-v0'))
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$OutputDir=(Resolve-Path $OutputDir).Path
if (-not (Test-Path (Join-Path $OutputDir 'crt-linkage-receipt.json'))) {
  throw 'W4C_PRODUCER_ORACLE_PREREQUISITE_MISSING'
}
$vswhere=Join-Path ([Environment]::GetFolderPath('ProgramFilesX86')) 'Microsoft Visual Studio\Installer\vswhere.exe'
$vs=(& $vswhere -latest -products '*' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath | Select-Object -First 1)
if (-not $vs) { throw 'MSVC_NOT_INSTALLED' }
$vsdev=Join-Path $vs 'Common7\Tools\VsDevCmd.bat'
$src=Join-Path $PSScriptRoot 'windows_crt_consumer.c'
$batch=@"
@echo off
call "$vsdev" -no_logo -arch=amd64 -host_arch=amd64 >nul
if errorlevel 1 exit /b 10
cl /nologo /c /O1 /Gy /GS- /MT /Fo"$OutputDir\crt_static_heldout.obj" "$src"
if errorlevel 1 exit /b 11
link /nologo /SUBSYSTEM:CONSOLE /MACHINE:X64 /INCREMENTAL:NO /OPT:REF /OPT:ICF /OUT:"$OutputDir\crt_static_heldout.exe" /MAP:"$OutputDir\crt_static_heldout.map" /VERBOSE:LIB "$OutputDir\crt_static_heldout.obj" > "$OutputDir\crt_static_heldout-link.log" 2>&1
if errorlevel 1 exit /b 12
exit /b 0
"@
$path=Join-Path $OutputDir 'compile-heldout.cmd'
Set-Content -Path $path -Value $batch -Encoding ascii
cmd.exe /d /c ('"' + $path + '"')
if ($LASTEXITCODE -ne 0) { throw ("W4C_HELDOUT_COMPILE_FAIL_{0}" -f $LASTEXITCODE) }
python -c "import sys,pathlib; sys.path.insert(0,sys.argv[1]); from verify_msvc import pe_identity; x=pe_identity(pathlib.Path(sys.argv[2])); assert x['machine']=='AMD64' if isinstance(x['machine'],str) else True" $PSScriptRoot (Join-Path $OutputDir 'crt_static_heldout.exe')
if ($LASTEXITCODE -ne 0) { throw 'W4C_HELDOUT_PE_ORACLE_FAIL' }
Write-Output "W4C_HELDOUT_PRODUCED=/O1 /MT; separate /O2 /MT and /MD controls retained"
