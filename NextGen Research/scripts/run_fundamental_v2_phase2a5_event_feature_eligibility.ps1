$ErrorActionPreference = "Stop"

$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$python = "python"
$tests = Join-Path $repo "NextGen Research\tests\run_fundamental_research_v2_phase2a5_event_feature_eligibility_tests.py"
$runner = Join-Path $repo "NextGen Research\scripts\run_fundamental_v2_phase2a5_event_feature_eligibility.py"

Write-Host "Fundamental V2 Phase 2A.5 - event-feature eligibility audit"
Write-Host "Offline only. No derived values. No labels. No model training. No production changes."

& $python $tests
if ($LASTEXITCODE -ne 0) { throw "Phase 2A.5 eligibility tests failed." }

& $python $runner
if ($LASTEXITCODE -ne 0) { throw "Phase 2A.5 event-feature eligibility audit failed." }

Write-Host "Phase 2A.5 event-feature eligibility audit complete."
