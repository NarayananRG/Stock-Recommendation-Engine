$ErrorActionPreference = "Stop"

$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$python = "python"
$tests = Join-Path $repo "NextGen Research\tests\run_fundamental_research_v2_phase2a2_mapping_tests.py"
$audit = Join-Path $repo "NextGen Research\scripts\run_fundamental_v2_phase2a2_mapping_audit.py"

Write-Host "Fundamental V2 Phase 2A.2 - canonical mapping/context audit"
Write-Host "SHADOW_ONLY. No model training. No production changes."

& $python $tests
if ($LASTEXITCODE -ne 0) { throw "Phase 2A.2 mapping tests failed." }

& $python $audit
if ($LASTEXITCODE -ne 0) { throw "Phase 2A.2 canonical mapping audit failed." }

Write-Host "Phase 2A.2 canonical mapping audit complete."
