$ErrorActionPreference = "Stop"

$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$python = "python"
$test = Join-Path $repo "NextGen Research\tests\run_fundamental_research_v2_phase2a1_tests.py"
$pilot = Join-Path $repo "NextGen Research\scripts\run_fundamental_v2_phase2a1_pilot.py"

Write-Host "Fundamental V2 Phase 2A.1 — SHADOW_ONLY"
Write-Host "No production model changes. No yfinance fundamentals."

& $python $test
if ($LASTEXITCODE -ne 0) { throw "Phase 2A.1 contract tests failed." }

& $python $pilot
if ($LASTEXITCODE -ne 0) { throw "Phase 2A.1 NSE pilot failed with exit code $LASTEXITCODE." }

Write-Host "Pilot complete. Evidence:"
Write-Host (Join-Path $repo "NextGen Research\results\fundamental_v2_phase2a1_pilot")
