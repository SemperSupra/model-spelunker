#requires -Version 5.1
<#
Public-safe read-only host/workcell readiness census.
Never installs, enables, changes, probes remote endpoints, elevates or discloses secrets.
Intended as safe B0 on a native Windows control surface and in hosted CI.
#>
[CmdletBinding()]
param()
Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
function Present([string]$Name) { [bool](Get-Command $Name -ErrorAction SilentlyContinue) }
function Seen([scriptblock]$Probe) {
    try { & $Probe } catch { 'UNKNOWN_OR_DENIED' }
}
$cs = Seen { Get-CimInstance Win32_ComputerSystem -ErrorAction Stop }
$os = Seen { Get-CimInstance Win32_OperatingSystem -ErrorAction Stop }
$vmCount='UNKNOWN'
$switchTypes=@()
if(Present 'Get-VM') {
    try { $vmCount = @(Get-VM -ErrorAction Stop).Count }
    catch { $vmCount = 'DENIED_OR_UNAVAILABLE' }
}
if(Present 'Get-VMSwitch') {
    try {
        $switchTypes=@(Get-VMSwitch -ErrorAction Stop |
          Group-Object -Property SwitchType |
          ForEach-Object { [string]$_.Name })
    } catch { $switchTypes=@('DENIED_OR_UNAVAILABLE') }
}
$feature='UNKNOWN'
if(Present 'Get-WindowsOptionalFeature') {
    try { $feature = [string](Get-WindowsOptionalFeature -Online -FeatureName Microsoft-Hyper-V-All -ErrorAction Stop).State }
    catch { $feature = 'UNKNOWN_OR_DENIED' }
}
$vmms='UNKNOWN'
try { $vmms=[string](Get-Service vmms -ErrorAction Stop).Status } catch {}
$disk='UNKNOWN'
try {
    $drive = Get-PSDrive -Name $env:SystemDrive.Substring(0,1) -PSProvider FileSystem
    $disk = [math]::Floor($drive.Free/1GB)
} catch {}
$ram='UNKNOWN'
try { $ram=[math]::Floor($os.TotalVisibleMemorySize / 1048576) } catch {}
$cpu='UNKNOWN'
try { $cpu=[int]$cs.NumberOfLogicalProcessors } catch {}
[ordered]@{
    schema='qwencode-public-host-census/v1'
    evidence_type='READ_ONLY'
    mutation='NONE'
    platform='windows'
    powershell_major=$PSVersionTable.PSVersion.Major
    os_build=$(try { [string]$os.Version } catch { 'UNKNOWN' })
    cpu_logical=$cpu
    total_ram_gib=$ram
    free_system_drive_gib=$disk
    hyperv_feature=$feature
    hyperv_service=$vmms
    hyperv_management_cmdlets=(Present 'Get-VM')
    hyperv_vms_observed_count=$vmCount
    hyperv_vswitch_types=$switchTypes
    wsl_binary_present=(Present 'wsl.exe')
    git_binary_present=(Present 'git.exe')
    ssh_client_present=(Present 'ssh.exe')
    qwen_binary_present=(Present 'qwen')
    node_binary_present=(Present 'node.exe')
    remote_model_routes='NOT_PROBED'
    privileged_apply='NOT_AUTHORIZED_BY_CENSUS'
    host_identity='REDACTED'
} | ConvertTo-Json -Depth 6
