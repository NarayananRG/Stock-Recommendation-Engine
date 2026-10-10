$ErrorActionPreference = "Stop"
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$parts = Get-ChildItem -Path $Here -Filter "source.part.*.b64" | Sort-Object Name
if (-not $parts) { throw "No source archive parts found." }
$joined = Join-Path $Here "StockRecommendationEngine_0.8.4_visual_phase1_TEST_SOURCE.zip.b64"
$zip = Join-Path $Here "StockRecommendationEngine_0.8.4_visual_phase1_TEST_SOURCE.zip"
$out = Join-Path $Here "extracted"
(Get-Content $parts.FullName -Raw) | Set-Content -NoNewline -Encoding ASCII $joined
[IO.File]::WriteAllBytes($zip, [Convert]::FromBase64String((Get-Content $joined -Raw)))
$actual = (Get-FileHash -Algorithm SHA256 $zip).Hash.ToLowerInvariant()
$expected = "4e23a25ae25c2c28d3bf7576e677c5345713df49d4a9f7b00ccba55e43c744d8"
if ($actual -ne $expected) { throw "Source ZIP hash mismatch: $actual" }
if (Test-Path $out) { Remove-Item -Recurse -Force $out }
Expand-Archive -Path $zip -DestinationPath $out
Write-Host "0.8.4 visual-phase1 source extracted and verified: $out" -ForegroundColor Green
