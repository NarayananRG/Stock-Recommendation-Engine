$ErrorActionPreference = "Stop"

$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$python = "python"
$tests = Join-Path $repo "NextGen Research\tests\run_fundamental_research_v2_phase2a1_tests.py"
$revalidate = Join-Path $repo "NextGen Research\scripts\revalidate_fundamental_v2_phase2a1_scaled.py"

Write-Host "Phase 2A.1 - cached 186-company PIT revalidation"
& $python $tests
if ($LASTEXITCODE -ne 0) { throw "Phase 2A.1 regression tests failed." }

& $python $revalidate
if ($LASTEXITCODE -ne 0) { throw "Scaled PIT revalidation still has hard failures." }

Write-Host "Scaled PIT revalidation PASS."
