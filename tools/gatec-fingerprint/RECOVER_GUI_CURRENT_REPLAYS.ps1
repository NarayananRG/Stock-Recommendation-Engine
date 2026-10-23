# Keep the actual SRE GUI open. No installation or source patch.
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$worker = Join-Path $here 'RECOVER_GUI_CURRENT_REPLAYS.py'
if (-not (Test-Path -LiteralPath $worker)) { throw 'Extract the complete ZIP before running this script.' }
Write-Host 'Keep SRE open and idle. This runs only missing October 15/19 research sessions through its live API.'
Write-Host 'No dependencies will be installed. A PRIVATE database backup is saved locally; do not upload it.'
if (Get-Command py -ErrorAction SilentlyContinue) { & py -3 $worker }
elseif (Get-Command python -ErrorAction SilentlyContinue) { & python $worker }
else { throw 'No existing Python command found. Nothing changed.' }
if ($LASTEXITCODE -ne 0) { throw 'Recovery stopped. Preserve the report folder; do not retry blindly.' }
