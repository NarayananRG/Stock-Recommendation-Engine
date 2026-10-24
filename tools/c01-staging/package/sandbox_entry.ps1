param([Parameter(Mandatory=$true)][ValidateSet('offline','official')][string]$Phase)
$ErrorActionPreference = 'Stop'
# Never log off a host session if this internal entry point is launched manually.
if ($env:USERNAME -ne 'WDAGUtilityAccount' -or -not (Test-Path -LiteralPath 'C:\C01Input\input.json') -or -not (Test-Path -LiteralPath 'C:\C01Package\sandbox_worker.py') -or -not (Test-Path -LiteralPath 'C:\C01Output' -PathType Container)) {
 throw 'Internal Windows Sandbox entry point only. Use RUN_WINDOWS_STAGING.ps1 on the host.'
}
try {
 New-Item -ItemType Directory -Path 'C:\C01Output\PRIVATE' -Force | Out-Null
 $ErrorActionPreference = 'Continue'
 & 'C:\C01Input\runtime\python.exe' -I -S -B 'C:\C01Package\sandbox_worker.py' --phase $Phase 2>&1 | Out-File -LiteralPath 'C:\C01Output\PRIVATE\bootstrap.log' -Encoding utf8
} finally {
 if (-not (Test-Path -LiteralPath 'C:\C01Output\DONE.json')) {
  @{checks=@{sandbox_bootstrap=@{status='BLOCKED';evidence='Sandbox worker did not produce results. Inspect PRIVATE/bootstrap.log locally.'}};execution_complete=$false;live_installation_modified=$false;historical_replays_run=0} | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath 'C:\C01Output\DONE.json' -Encoding utf8
 }
 shutdown.exe /l
}
