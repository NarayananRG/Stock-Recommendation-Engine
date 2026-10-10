$ErrorActionPreference = "Stop"

$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$python = "python"
$tests = Join-Path $repo "NextGen Research\tests\run_fundamental_research_v2_phase2a4_continuity_review_tests.py"
$runner = Join-Path $repo "NextGen Research\scripts\run_fundamental_v2_phase2a4_continuity_review.py"

Write-Host "Fundamental V2 Phase 2A.4 - continuity findings review"
Write-Host "Offline only. Descriptive pair-availability audit. No growth calculation. No model training. No production changes."

& $python $tests
if ($LASTEXITCODE -ne 0) { throw "Phase 2A.4 continuity-review tests failed." }

& $python $runner
if ($LASTEXITCODE -ne 0) { throw "Phase 2A.4 continuity findings review failed." }

Write-Host "Phase 2A.4 continuity findings review complete."
