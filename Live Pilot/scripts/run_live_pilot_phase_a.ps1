$ErrorActionPreference = "Stop"

$repo = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$test = Join-Path $repo "Live Pilot\tests\run_live_pilot_core_tests.py"
$discovery = Join-Path $repo "Live Pilot\scripts\discover_leg8_app.ps1"

Write-Host "============================================================"
Write-Host "LIVE PILOT V1 - PHASE A: CORE TEST + LEG8 DISCOVERY"
Write-Host "============================================================"
Write-Host "Read-only against the production app source."
Write-Host "No model changes. No UI changes. No broker actions."
Write-Host ""

python $test
if ($LASTEXITCODE -ne 0) {
    throw "Live Pilot core tests failed. UI integration is blocked."
}

Write-Host ""
Write-Host "Core tests PASS. Discovering accepted Leg 8 source..."
powershell -ExecutionPolicy Bypass -File $discovery
if ($LASTEXITCODE -ne 0) {
    throw "Leg 8 discovery failed."
}

Write-Host ""
Write-Host "LIVE PILOT PHASE A COMPLETE."
Write-Host "Copy the console output from the === ROOT === section through the final keyword hits back to ChatGPT."
