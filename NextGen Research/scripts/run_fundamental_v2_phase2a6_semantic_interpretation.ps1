$ErrorActionPreference = "Stop"

$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$python = "python"
$tests = Join-Path $repo "NextGen Research\tests\run_fundamental_research_v2_phase2a6_semantic_interpretation_tests.py"
$runner = Join-Path $repo "NextGen Research\scripts\run_fundamental_v2_phase2a6_semantic_interpretation.py"

Write-Host "Fundamental V2 Phase 2A.6 - semantic interpretation audit"
Write-Host "Offline only. Candidate semantics only. No signals, scores, market labels, training, or production changes."

& $python $tests
if ($LASTEXITCODE -ne 0) { throw "Phase 2A.6 semantic interpretation tests failed." }

& $python $runner
if ($LASTEXITCODE -ne 0) { throw "Phase 2A.6 semantic interpretation audit failed." }

Write-Host "Phase 2A.6 semantic interpretation audit complete."
