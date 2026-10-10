$ErrorActionPreference = "Stop"

$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$python = "python"

$p7Tests = Join-Path $repo "NextGen Research\tests\run_fundamental_research_v2_phase2a7_risk_event_builder_tests.py"
$p7Run = Join-Path $repo "NextGen Research\scripts\run_fundamental_v2_phase2a7_risk_event_builder.py"
$p8Tests = Join-Path $repo "NextGen Research\tests\run_fundamental_research_v2_phase2a8_market_outcome_tests.py"
$p8Run = Join-Path $repo "NextGen Research\scripts\run_fundamental_v2_phase2a8_market_outcomes.py"
$p9Tests = Join-Path $repo "NextGen Research\tests\run_fundamental_research_v2_phase2a9_independent_validation_tests.py"
$p9Run = Join-Path $repo "NextGen Research\scripts\run_fundamental_v2_phase2a9_independent_validation.py"

Write-Host "Fundamental Research V2 - FINAL BUNDLED RUN"
Write-Host "Gates: Phase 2A.7 risk profiles -> Phase 2A.8 official-only 21/63/126 outcomes -> Phase 2A.9 independent validation/final decision"
Write-Host "Fail-fast. No yfinance. No model training. No production changes. No promotion."

& $python $p7Tests
if ($LASTEXITCODE -ne 0) { throw "FINAL BUNDLE stopped: Phase 2A.7 tests failed." }
& $python $p7Run
if ($LASTEXITCODE -ne 0) { throw "FINAL BUNDLE stopped: Phase 2A.7 risk-event builder failed." }

& $python $p8Tests
if ($LASTEXITCODE -ne 0) { throw "FINAL BUNDLE stopped: Phase 2A.8 tests failed." }
& $python $p8Run
if ($LASTEXITCODE -ne 0) { throw "FINAL BUNDLE stopped: Phase 2A.8 official market-outcome evaluation failed." }

& $python $p9Tests
if ($LASTEXITCODE -ne 0) { throw "FINAL BUNDLE stopped: Phase 2A.9 tests failed." }
& $python $p9Run
if ($LASTEXITCODE -ne 0) { throw "FINAL BUNDLE stopped: Phase 2A.9 independent validation failed." }

Write-Host "Fundamental Research V2 final bundled run complete."
