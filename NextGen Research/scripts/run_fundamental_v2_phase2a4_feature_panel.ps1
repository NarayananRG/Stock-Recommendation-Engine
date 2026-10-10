$ErrorActionPreference = "Stop"

$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$python = "python"
$tests = Join-Path $repo "NextGen Research\tests\run_fundamental_research_v2_phase2a4_feature_panel_tests.py"
$runner = Join-Path $repo "NextGen Research\scripts\run_fundamental_v2_phase2a4_feature_panel.py"

Write-Host "Fundamental V2 Phase 2A.4 - canonical feature panel + continuity audit"
Write-Host "Offline only. Basis-separated. No growth derivation. No model training. No production changes."

& $python $tests
if ($LASTEXITCODE -ne 0) { throw "Phase 2A.4 feature-panel tests failed." }

& $python $runner
if ($LASTEXITCODE -ne 0) { throw "Phase 2A.4 feature-panel build failed." }

Write-Host "Phase 2A.4 feature panel and continuity audit complete."
