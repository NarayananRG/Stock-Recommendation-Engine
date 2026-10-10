$ErrorActionPreference = "Stop"

$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$python = "python"
$tests = Join-Path $repo "NextGen Research\tests\run_fundamental_research_v2_phase2a2_tests.py"
$pilot = Join-Path $repo "NextGen Research\scripts\run_fundamental_v2_phase2a2_xbrl_pilot.py"

Write-Host "Fundamental V2 Phase 2A.2 - official XBRL breadth pilot"
Write-Host "SHADOW_ONLY. No model training. No production changes."

& $python $tests
if ($LASTEXITCODE -ne 0) { throw "Phase 2A.2 XBRL tests failed." }

& $python $pilot
if ($LASTEXITCODE -ne 0) { throw "Phase 2A.2 XBRL pilot failed or is incomplete." }

Write-Host "Phase 2A.2 XBRL pilot PASS."
