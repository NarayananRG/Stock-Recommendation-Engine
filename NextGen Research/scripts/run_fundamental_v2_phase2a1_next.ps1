$ErrorActionPreference = "Stop"

$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$python = "python"
$tests = Join-Path $repo "NextGen Research\tests\run_fundamental_research_v2_phase2a1_tests.py"
$validate = Join-Path $repo "NextGen Research\scripts\validate_fundamental_v2_phase2a1_pilot.py"
$scale = Join-Path $repo "NextGen Research\scripts\run_fundamental_v2_phase2a1_scaled.py"

Write-Host "Phase 2A.1 - validate pilot PIT chronology"
& $python $tests
if ($LASTEXITCODE -ne 0) { throw "Phase 2A.1 tests failed." }

& $python $validate
if ($LASTEXITCODE -ne 0) { throw "Pilot PIT validation failed. Scale-up blocked." }

Write-Host "Pilot PIT validation PASS. Starting exact 186-company official NSE recovery."
& $python $scale
if ($LASTEXITCODE -ne 0) { throw "Scaled Phase 2A.1 recovery ended with exit code $LASTEXITCODE. Check checkpoint/results." }

Write-Host "Scaled Phase 2A.1 recovery PASS."
