param([Parameter(Mandatory=$true)][string]$InputCsv,[Parameter(Mandatory=$true)][string]$MarketManifest)
$repo = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$env:PYTHONPATH = Join-Path $repo "Stage 4A.3"
python -m stage4a3.prospective_runner --repo-root $repo --input $InputCsv --market-manifest $MarketManifest
