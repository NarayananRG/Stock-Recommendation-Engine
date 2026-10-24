param(
 [Parameter(Mandatory=$true)][string]$InitialRun,
 [Parameter(Mandatory=$true)][string]$WorkspaceParent,
 [string]$RuntimePython = ''
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if ($env:OS -ne 'Windows_NT') { throw 'Windows required. No live fallback.' }
$initialPath = (Resolve-Path -LiteralPath $InitialRun).Path
$inventoryPath = Join-Path $initialPath 'PRIVATE_RUNTIME_INVENTORY.json'
if (-not (Test-Path -LiteralPath $inventoryPath -PathType Leaf)) { throw 'Select the existing successful Gate C Initial report directory, containing PRIVATE_RESTORE and PRIVATE_RUNTIME_INVENTORY.json.' }
if (-not $RuntimePython) { $RuntimePython = (Get-Content -LiteralPath $inventoryPath -Raw | ConvertFrom-Json).executable }
if (-not (Test-Path -LiteralPath $RuntimePython -PathType Leaf)) { throw 'Recorded GUI runtime executable is unavailable. No installation attempted.' }
& $RuntimePython -I -S -B (Join-Path $PSScriptRoot 'export_vm_inputs.py') --initial $initialPath --workspace-parent $WorkspaceParent --runtime $RuntimePython
if ($LASTEXITCODE -ne 0) { throw 'Read-only VM export stopped. Read the reported machine-results file or safe-stop reason. Do not apply candidate files manually.' }
