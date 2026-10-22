# Native Windows-only, synthetic fixtures; no real application state.
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$base=Join-Path $env:RUNNER_TEMP ('gatea-collector-'+[Guid]::NewGuid().ToString('N'))
$data=Join-Path $base 'app data with spaces'
$engine=Join-Path $data 'native-engine-0.14.13'
$out=Join-Path $base 'output'
$scriptFile=Join-Path $PSScriptRoot 'SRE-GateA-Collect-Current-Snapshot.ps1'
$results=New-Object Collections.ArrayList
function Assert-Check($Name,$Condition) {
    if(-not $Condition){throw "FAIL: $Name"};[void]$results.Add($Name);Write-Host "PASS: $Name"
}
function Assert-Rejected($Name,[scriptblock]$Action) {
    $rejected=$false;try{& $Action|Out-Null}catch{$rejected=$true;Write-Host "Expected rejection: $($_.Exception.Message)"}
    Assert-Check $Name $rejected
}
[IO.Directory]::CreateDirectory((Join-Path $engine 'modern_ui\frontend'))|Out-Null
[IO.Directory]::CreateDirectory((Join-Path $engine 'stock_app'))|Out-Null
[IO.Directory]::CreateDirectory($out)|Out-Null
[IO.File]::WriteAllText((Join-Path $engine 'modern_ui\api.py'),'# synthetic api')
[IO.File]::WriteAllText((Join-Path $engine 'stock_app\live_decision_v1.py'),'# synthetic frozen contract')
[IO.File]::WriteAllText((Join-Path $engine 'modern_ui\frontend\app.js'),'// synthetic frontend')
[IO.File]::WriteAllText((Join-Path $data '.gatea-issue2-receipt.json'),'{"patch":"issue2"}')
[IO.File]::WriteAllText((Join-Path $data 'active_analysis_run.json'),'{"market_session":"2026-10-21","run_id":"synthetic"}')
[IO.File]::WriteAllText((Join-Path $data 'config.json'),'{"ordinary":1,"nested":{"access_token":"DO_NOT_UPLOAD","password":"ALSO_SECRET"}}')
[IO.File]::WriteAllText((Join-Path $data '.env'),'API_KEY=DO_NOT_UPLOAD')
[IO.Directory]::CreateDirectory((Join-Path $engine '.venv'))|Out-Null
[IO.File]::WriteAllText((Join-Path $engine '.venv\excluded.txt'),'dependency')
[IO.Directory]::CreateDirectory((Join-Path $engine 'phase5\filings'))|Out-Null
[IO.File]::WriteAllText((Join-Path $engine 'phase5\filings\entry.json'),'{"evidence_hash":"retained","publication":"2026-10-16"}')
& python (Join-Path $PSScriptRoot 'seed-fixtures.py') $data
if($LASTEXITCODE -ne 0){throw 'Fixture seeding failed'}
. $scriptFile
$before=@{};foreach($f in Get-ChildItem $data -Recurse -File -Force){$before[$f.FullName]=Get-SreHash $f.FullName}
$result=New-SreGateASnapshot $data $engine $out
Assert-Check 'Archive produced and hash reported' ((Test-Path $result.zip) -and (Get-SreHash $result.zip) -eq $result.sha256)
Assert-Check 'All three SQLite databases detected' ($result.databases -eq 3)
$extract=Join-Path $base 'extract'
[IO.Compression.ZipFile]::ExtractToDirectory($result.zip,$extract)
$manifest=Get-Content (Join-Path $extract 'snapshot-manifest.json') -Raw|ConvertFrom-Json
Assert-Check 'Every captured database passes integrity_check' (@($manifest.databases|Where-Object{$_.integrity_check -ne 'ok'}).Count -eq 0)
$snapshotDb=Join-Path $extract 'application-state\phase81_validation.sqlite3'
Assert-Check 'Committed WAL-only records survive backup' ([SreGateASnapshotSqlite]::Query($snapshotDb,'select sum(qty) from positions') -eq '60')
Assert-Check 'Distinct paper and legacy position identities preserved' ([SreGateASnapshotSqlite]::Query($snapshotDb,'select count(*) from positions') -eq '3')
foreach($path in $before.Keys){if((Get-SreHash $path) -ne $before[$path]){throw "Original changed: $path"}}
Assert-Check 'Every original DB, WAL, source and config hash unchanged' $true
Assert-Check 'Frontend, entry evidence and hidden receipts included' ((Test-Path (Join-Path $extract 'engine\modern_ui\frontend\app.js')) -and (Test-Path (Join-Path $extract 'engine\phase5\filings\entry.json')) -and (Test-Path (Join-Path $extract 'application-state\.gatea-issue2-receipt.json')))
Assert-Check 'Dependencies and credential file excluded' (-not (Test-Path (Join-Path $extract 'engine\.venv')) -and -not (Test-Path (Join-Path $extract 'application-state\.env')))
$config=Get-Content (Join-Path $extract 'application-state\config.json') -Raw
Assert-Check 'Nested credential values redacted in captured JSON only' ($config -notmatch 'DO_NOT_UPLOAD|ALSO_SECRET' -and $config -match 'REDACTED' -and $config -match 'ordinary')
Assert-Check 'Source hashes retained for every captured original' (@($manifest.source_files|Where-Object{$_.source_sha256.Length -ne 64}).Count -eq 0)
Assert-Check 'Source WAL accounted for but normalized out of archive' (@($manifest.source_files|Where-Object{$_.path -match '-wal$' -and -not $_.archive_included}).Count -eq 3)
Assert-Check 'No working copies remain after success' (@(Get-ChildItem $out -Directory).Count -eq 0)
Assert-Rejected 'Output inside installation safely refused' {New-SreGateASnapshot $data $engine (Join-Path $data 'bad-output')}
$dbPath=Join-Path $data 'phase81_validation.sqlite3'
$lock=[IO.File]::Open($dbPath,'Open','ReadWrite','None')
try{Assert-Rejected 'Database with an active incompatible handle safely refused' {New-SreGateASnapshot $data $engine $out}}finally{$lock.Dispose()}
$missing=Join-Path $data 'phase81_validation.sqlite3.hidden'
[IO.File]::Move($dbPath,$missing)
try{Assert-Rejected 'Missing required portfolio DB safely refused' {New-SreGateASnapshot $data $engine $out}}finally{[IO.File]::Move($missing,$dbPath)}
[IO.File]::WriteAllText((Join-Path $data 'corrupt.sqlite3'),'not a SQLite database')
Assert-Rejected 'Corrupt additional DB fails safely instead of silently skipping' {New-SreGateASnapshot $data $engine $out}
[IO.File]::Delete((Join-Path $data 'corrupt.sqlite3'))
Assert-Check 'Failed attempts leave no partial ZIP or staging folder' (@(Get-ChildItem $out -File -Filter '*.zip').Count -eq 1 -and @(Get-ChildItem $out -Directory).Count -eq 0)
foreach($path in $before.Keys){if((Get-SreHash $path) -ne $before[$path]){throw "Original changed after negative tests: $path"}}
Assert-Check 'Negative cases also preserve original hashes' $true
[IO.File]::WriteAllText((Join-Path $PSScriptRoot ('test-results-'+$PSVersionTable.PSVersion.Major+'.json')),([ordered]@{status='PASS';passed=$results.Count;failed=0;platform=[Environment]::OSVersion.VersionString;powershell=$PSVersionTable.PSVersion.ToString();checks=@($results)}|ConvertTo-Json -Depth 5))
Write-Host "ALL $($results.Count) NATIVE WINDOWS CHECKS PASSED"
