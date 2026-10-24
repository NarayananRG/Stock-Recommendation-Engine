param(
 [ValidateSet('Inspect','Offline','Official')][string]$Phase = 'Inspect',
 [string]$IsolationAttestation = 'C:\C01Package\VM_ISOLATION_ATTESTATION.json',
 [string]$OfflineReport = ''
)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
if($env:OS -ne 'Windows_NT'){throw 'Windows VM required.'}
if($Phase -eq 'Inspect'){
 Get-CimInstance Win32_ComputerSystem | Select-Object Manufacturer,Model
 Get-CimInstance Win32_ComputerSystemProduct | Select-Object UUID
 Write-Host 'Read-only inspection. Fill the isolation attestation with this VM UUID and verified hypervisor settings. No application started.'
 exit
}
# Validate the copied runtime executable before using it. The Python runner independently validates VM identity BEFORE creating work/app files.
$packet=Get-Content -LiteralPath 'C:\C01Input\input.json' -Raw | ConvertFrom-Json
$runtime='C:\C01Input\runtime\python.exe'
if((Get-FileHash -LiteralPath $runtime -Algorithm SHA256).Hash.ToLowerInvariant() -ne $packet.runtime_files.'python.exe'){throw 'Copied runtime executable hash mismatch.'}
$runnerArgs=@('-I','-S','-B',(Join-Path $PSScriptRoot 'vm_runner.py'),'--phase',$Phase.ToLowerInvariant(),'--attestation',$IsolationAttestation)
if($OfflineReport){$runnerArgs+=@('--offline-report',$OfflineReport)}
& $runtime @runnerArgs
if($LASTEXITCODE -ne 0){throw 'VM staging stopped safely; read the machine report or safe-stop reason. No live application fallback.'}
