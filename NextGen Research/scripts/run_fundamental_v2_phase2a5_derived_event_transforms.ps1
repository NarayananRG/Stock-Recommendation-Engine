$ErrorActionPreference = "Stop"

$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$python = "python"
$eligTests = Join-Path $repo "NextGen Research\tests\run_fundamental_research_v2_phase2a5_event_feature_eligibility_tests.py"
$eligRunner = Join-Path $repo "NextGen Research\scripts\run_fundamental_v2_phase2a5_event_feature_eligibility.py"
$tests = Join-Path $repo "NextGen Research\tests\run_fundamental_research_v2_phase2a5_derived_event_transform_tests.py"
$runner = Join-Path $repo "NextGen Research\scripts\run_fundamental_v2_phase2a5_derived_event_transforms.py"

Write-Host "Fundamental V2 Phase 2A.5 - sign-safe derived event transforms"
Write-Host "Offline only. No percent-change clipping. No semantic labels. No market labels. No model training. No production changes."

& $python $eligTests
if ($LASTEXITCODE -ne 0) { throw "Phase 2A.5 eligibility tests failed." }

& $python $eligRunner
if ($LASTEXITCODE -ne 0) { throw "Phase 2A.5 eligibility refresh failed." }

& $python $tests
if ($LASTEXITCODE -ne 0) { throw "Phase 2A.5 derived-event transform tests failed." }

& $python $runner
if ($LASTEXITCODE -ne 0) { throw "Phase 2A.5 derived-event transform audit failed." }

Write-Host "Phase 2A.5 derived-event transform audit complete."
