$ErrorActionPreference = "Stop"

$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$python = "python"
$closure = Join-Path $repo "NextGen Research\scripts\close_fundamental_v2_phase2a3.ps1.py"

Write-Host "Fundamental V2 Phase 2A.3 - formal closure from existing evidence"
Write-Host "No network fetch. No full validation rerun. No model training. No production changes."

& $python $closure
if ($LASTEXITCODE -ne 0) { throw "Phase 2A.3 closure evidence gate failed." }

Write-Host "Phase 2A.3 formally closed."
