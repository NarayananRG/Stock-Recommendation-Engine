$ErrorActionPreference = "Stop"

$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$python = "python"
$diag = Join-Path $repo "NextGen Research\scripts\inspect_fundamental_v2_phase2a1_edgecases.py"

Write-Host "Phase 2A.1 - inspect remaining NSE PIT edge cases"
& $python $diag
if ($LASTEXITCODE -ne 0) { throw "Edge-case diagnostic failed." }
