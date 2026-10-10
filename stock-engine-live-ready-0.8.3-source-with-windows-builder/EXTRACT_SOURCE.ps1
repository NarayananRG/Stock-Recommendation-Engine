$ErrorActionPreference = "Stop"
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$parts = Get-ChildItem -Path $Here -Filter "source.part.*.b64" | Sort-Object Name
if (-not $parts) { throw "No source archive parts found." }
$joined = Join-Path $Here "StockRecommendationEngine_0.8.3_live_ready_TEST_SOURCE.zip.b64"
$zip = Join-Path $Here "StockRecommendationEngine_0.8.3_live_ready_TEST_SOURCE.zip"
$out = Join-Path $Here "extracted"
(Get-Content $parts.FullName -Raw) | Set-Content -NoNewline -Encoding ASCII $joined
[IO.File]::WriteAllBytes($zip, [Convert]::FromBase64String((Get-Content $joined -Raw)))
$actual = (Get-FileHash -Algorithm SHA256 $zip).Hash.ToLowerInvariant()
$expected = "1a4179dc4fa99b512ab35edcb34511c2c080439baab12334c161668e2e9b0fe5"
if ($actual -ne $expected) { throw "Source ZIP hash mismatch: $actual" }
if (Test-Path $out) { Remove-Item -Recurse -Force $out }
Expand-Archive -Path $zip -DestinationPath $out
Write-Host "0.8.3 live-ready source extracted and verified: $out" -ForegroundColor Green
