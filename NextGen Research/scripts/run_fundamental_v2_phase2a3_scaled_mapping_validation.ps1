$ErrorActionPreference = "Stop"

$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$python = "python"
$tests = Join-Path $repo "NextGen Research\tests\run_fundamental_research_v2_phase2a3_scaled_mapping_tests.py"
$runner = Join-Path $repo "NextGen Research\scripts\run_fundamental_v2_phase2a3_scaled_mapping_validation.py"

Write-Host "Fundamental V2 Phase 2A.3 - scaled 186-company XBRL mapping validation"
Write-Host "SHADOW_ONLY. Checkpointed/resumable. No model training. No production changes."

& $python $tests
if ($LASTEXITCODE -ne 0) { throw "Phase 2A.3 scaled mapping tests failed." }

& $python $runner
if ($LASTEXITCODE -ne 0) { throw "Phase 2A.3 scaled mapping validation stopped with unresolved retrieval or semantic failures. Rerun is resumable." }

Write-Host "Phase 2A.3 scaled mapping validation complete."
