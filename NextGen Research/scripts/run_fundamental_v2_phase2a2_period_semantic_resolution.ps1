$ErrorActionPreference = "Stop"

$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$python = "python"
$tests = Join-Path $repo "NextGen Research\tests\run_fundamental_research_v2_phase2a2_period_semantic_tests.py"
$audit = Join-Path $repo "NextGen Research\scripts\run_fundamental_v2_phase2a2_period_semantic_resolution.py"

Write-Host "Fundamental V2 Phase 2A.2 - period-aware semantic resolution"
Write-Host "SHADOW_ONLY. No mapping freeze. No model training. No production changes."

& $python $tests
if ($LASTEXITCODE -ne 0) { throw "Phase 2A.2 period-semantic tests failed." }

& $python $audit
if ($LASTEXITCODE -ne 0) { throw "Phase 2A.2 period-semantic resolution failed." }

Write-Host "Phase 2A.2 period-semantic resolution complete."
