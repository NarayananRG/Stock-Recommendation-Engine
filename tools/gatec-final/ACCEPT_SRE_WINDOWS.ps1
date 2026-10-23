[CmdletBinding()]
param(
 [ValidateSet('Initial','Stopped','AfterRestart','Offline','OnlineRestored','OfficialRefresh')][string]$Stage='Initial',
 [string]$RunDirectory='',
 [switch]$ApproveManualLifecycle,
 [switch]$ApproveManualOffline,
 [switch]$GuiReviewed
)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$here=Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $RunDirectory) {
 if ($Stage -ne 'Initial') { throw 'Supply the SAME -RunDirectory printed by the Initial stage.' }
 $RunDirectory=Join-Path ([Environment]::GetFolderPath('UserProfile')) ('Downloads\SRE-GateC-Acceptance-'+(Get-Date -Format 'yyyyMMdd-HHmmss'))
}
if (-not (Test-Path -LiteralPath $RunDirectory)) { New-Item -ItemType Directory -Path $RunDirectory | Out-Null }
$RunDirectory=(Resolve-Path -LiteralPath $RunDirectory).Path
# Inspect the listener, never launch/stop SRE or expose its command line.
$runtimeExe=''
$processIdentity=''
$portFile=Join-Path $env:LOCALAPPDATA 'StockRecommendationEngine\runtime-port.txt'
if ($Stage -ne 'Stopped' -and (Test-Path -LiteralPath $portFile)) {
 $portNumber=[int](Get-Content -LiteralPath $portFile -Raw).Trim()
 $listeners=@(Get-NetTCPConnection -LocalPort $portNumber -State Listen -ErrorAction SilentlyContinue)
 if ($listeners.Count -gt 0) {
  $listenerPid=$listeners[0].OwningProcess
  $proc=Get-Process -Id $listenerPid -ErrorAction Stop
  $runtimeExe=$proc.Path
  $processIdentity=('{0}:{1:o}' -f $listenerPid,$proc.StartTime.ToUniversalTime())
 }
}
$worker=Join-Path $here 'accept_windows.py'
$argsList=@('-B',$worker,'--stage',$Stage,'--run',$RunDirectory)
# Windows PowerShell5 drops empty native-command arguments; omit absent optional values.
if ($runtimeExe) { $argsList+=@('--runtime',$runtimeExe) }
if ($processIdentity) { $argsList+=@('--pid',$processIdentity) }
if ($ApproveManualLifecycle) { $argsList+='--approve-manual-lifecycle' }
if ($ApproveManualOffline) { $argsList+='--approve-manual-offline' }
if ($GuiReviewed) { $argsList+='--gui-reviewed' }
Write-Host ('Stage: '+$Stage+'. SRE and live databases will not be modified by this runner.')
Write-Host ('Private backup/report directory: '+$RunDirectory)
if (Get-Command py -ErrorAction SilentlyContinue) { & py -3 @argsList }
elseif (Get-Command python -ErrorAction SilentlyContinue) { & python @argsList }
else { throw 'No existing Python available. No dependency installation attempted.' }
if ($LASTEXITCODE -ne 0) { throw 'Acceptance stopped. Preserve the report and private backup. Do not retry blindly.' }
Write-Host ('Machine results: '+(Join-Path $RunDirectory 'GATE_C_MACHINE_RESULTS.json'))
Write-Host 'Read WINDOWS_ACCEPTANCE_GUIDE.md for coordinated manual stages. No replay was requested.'
