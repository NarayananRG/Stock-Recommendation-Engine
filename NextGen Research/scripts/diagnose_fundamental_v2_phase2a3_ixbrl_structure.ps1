$ErrorActionPreference = "Stop"

$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$python = "python"
$diag = Join-Path $repo "NextGen Research\scripts\diagnose_fundamental_v2_phase2a3_ixbrl_structure.py"

Write-Host "Fundamental V2 Phase 2A.3 - inspect only the unresolved iXBRL files"
Write-Host "No full validation rerun. No model training. No production changes."

& $python $diag
if ($LASTEXITCODE -ne 0) { throw "Phase 2A.3 iXBRL structure diagnostic failed." }

Write-Host "Phase 2A.3 iXBRL structure diagnostic complete."
