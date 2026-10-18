# Public-safe, one-shot Windows native MSVC producer + runtime inventory.
param([string] $OutputDir = (Join-Path $env:RUNNER_TEMP 're-windows-msvc-v0'))
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
$OutputDir = (Resolve-Path $OutputDir).Path
$vswhere = Join-Path ([Environment]::GetFolderPath('ProgramFilesX86')) 'Microsoft Visual Studio\Installer\vswhere.exe'
if (-not (Test-Path $vswhere)) { throw "VSWHERE_NOT_FOUND" }
$vs = (& $vswhere -latest -products '*' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath | Select-Object -First 1)
if (-not $vs) { throw "MSVC_WORKLOAD_NOT_INSTALLED" }
$vsdev = Join-Path $vs 'Common7\Tools\VsDevCmd.bat'
if (-not (Test-Path $vsdev)) { throw "VSDEVCMD_NOT_FOUND" }
$src = Join-Path $PSScriptRoot 'windows_reference.c'
if (-not (Test-Path $src)) { throw "SOURCE_MISSING" }
$obj = Join-Path $OutputDir 'reference.obj'
$lib = Join-Path $OutputDir 'reference_static.lib'
$refdll = Join-Path $OutputDir 'reference_labeled.dll'
$targdll = Join-Path $OutputDir 'target_stripped.dll'
$refpdb = Join-Path $OutputDir 'reference_labeled.pdb'
$targpdb = Join-Path $OutputDir 'target_stripped.pdb'
$batch = @"
@echo off
call "$vsdev" -no_logo -arch=amd64 -host_arch=amd64 >nul
if errorlevel 1 exit /b 10
where cl > "$OutputDir\cl-path.txt"
if errorlevel 1 exit /b 11
where link > "$OutputDir\link-path.txt"
if errorlevel 1 exit /b 12
where lib > "$OutputDir\lib-path.txt"
if errorlevel 1 exit /b 13
where dumpbin > "$OutputDir\dumpbin-path.txt"
if errorlevel 1 exit /b 14
echo VCToolsInstallDir=%VCToolsInstallDir% > "$OutputDir\vc-env.txt"
echo WindowsSdkDir=%WindowsSdkDir% >> "$OutputDir\vc-env.txt"
echo WindowsSDKVersion=%WindowsSDKVersion% >> "$OutputDir\vc-env.txt"
cl /nologo /c /O2 /Gy /GS- /Z7 /Fo"$obj" "$src"
if errorlevel 1 exit /b 21
lib /nologo /OUT:"$lib" "$obj"
if errorlevel 1 exit /b 22
link /nologo /DLL /NOENTRY /NODEFAULTLIB /MACHINE:X64 /INCREMENTAL:NO /OPT:REF /OPT:ICF /DEBUG:FULL /PDB:"$refpdb" /OUT:"$refdll" /EXPORT:re_lib_mix /EXPORT:re_lib_crc /EXPORT:re_lib_scramble /EXPORT:re_lib_unrelated "$obj"
if errorlevel 1 exit /b 23
link /nologo /DLL /NOENTRY /NODEFAULTLIB /MACHINE:X64 /INCREMENTAL:NO /OPT:REF /OPT:ICF /DEBUG:FULL /PDB:"$targpdb" /OUT:"$targdll" "$obj"
if errorlevel 1 exit /b 24
dumpbin /nologo /exports "$refdll" > "$OutputDir\reference-exports.txt"
if errorlevel 1 exit /b 25
dumpbin /nologo /exports "$targdll" > "$OutputDir\target-exports.txt"
if errorlevel 1 exit /b 26
dumpbin /nologo /symbols "$obj" > "$OutputDir\reference-symbols.txt"
if errorlevel 1 exit /b 27
cl /Bv > "$OutputDir\msvc-versions.txt" 2>&1
exit /b 0
"@
$batchPath = Join-Path $OutputDir 'build-msvc.cmd'
Set-Content -LiteralPath $batchPath -Value $batch -Encoding ascii
cmd.exe /d /c ('"' + $batchPath + '"')
if ($LASTEXITCODE -ne 0) { throw "MSVC_NATIVE_BUILD_FAILED:$LASTEXITCODE" }
$toolEnv = @{}
Get-Content (Join-Path $OutputDir 'vc-env.txt') | ForEach-Object {
  if ($_ -match '^(.*?)=(.*)$') { $toolEnv[$Matches[1]] = $Matches[2].Trim() }
}
$vcLibPath = Join-Path $toolEnv['VCToolsInstallDir'] 'lib\x64'
$ucrtLibPath = Join-Path (Join-Path $toolEnv['WindowsSdkDir'] 'Lib') (Join-Path $toolEnv['WindowsSDKVersion'] 'ucrt\x64')
$winLibPath = Join-Path (Join-Path $toolEnv['WindowsSdkDir'] 'Lib') (Join-Path $toolEnv['WindowsSDKVersion'] 'um\x64')
function Get-ArchiveCount($dir) {
  if (-not (Test-Path $dir)) { return -1 }
  return @((Get-ChildItem -LiteralPath $dir -Filter '*.lib' -File)).Count
}
$metadata = @{
  schema_version = 1
  visual_studio_install = $vs
  source = 'self-authored synthetic Windows dispatcher'
  vc_tools_version = $toolEnv['VCToolsInstallDir']
  windows_sdk_version = $toolEnv['WindowsSDKVersion']
  host_image_os = $env:ImageOS
  runner_arch = $env:RUNNER_ARCH
  vc_archives_x64 = Get-ArchiveCount $vcLibPath
  ucrt_archives_x64 = Get-ArchiveCount $ucrtLibPath
  windows_sdk_import_archives_x64 = Get-ArchiveCount $winLibPath
  vc_static_archive_samples = @((Get-ChildItem -LiteralPath $vcLibPath -Filter '*.lib' -File -ErrorAction SilentlyContinue | Select-Object -First 20 -ExpandProperty Name))
  status = 'COMPILATION_ONLY_NO_FID_MATCH_CLAIM'
}
$metadata | ConvertTo-Json -Depth 4 | Set-Content (Join-Path $OutputDir 'msvc-inventory.json') -Encoding utf8
python (Join-Path $PSScriptRoot 'verify_msvc.py') --output $OutputDir
if ($LASTEXITCODE -ne 0) { throw "MSVC_INDEPENDENT_ORACLE_FAILED" }
