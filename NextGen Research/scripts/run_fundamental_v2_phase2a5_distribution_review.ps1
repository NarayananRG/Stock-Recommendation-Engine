$ErrorActionPreference = "Stop"

$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$python = "python"
$tests = Join-Path $repo "NextGen Research\tests\run_fundamental_research_v2_phase2a5_distribution_review_tests.py"
$runner = Join-Path $repo "NextGen Research\scripts\run_fundamental_v2_phase2a5_distribution_review.py"

Write-Host "Fundamental V2 Phase 2A.5 - derived-event distribution + sign-transition review"
Write-Host "Offline only. No semantic labels. No market labels. No model training. No production changes."

& $python $tests
if ($LASTEXITCODE -ne 0) { throw "Phase 2A.5 distribution-review tests failed." }

& $python $runner
if ($LASTEXITCODE -ne 0) { throw "Phase 2A.5 distribution review failed." }

Write-Host "Phase 2A.5 derived-event distribution review complete."
