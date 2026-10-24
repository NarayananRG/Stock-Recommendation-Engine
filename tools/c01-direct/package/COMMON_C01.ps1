Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
function Invoke-C01Patch {
    param([string]$Action,[string]$PythonPath,[string]$EnginePath,[string]$DataPath,[string]$ReceiptPath)
    if ($env:OS -ne 'Windows_NT') { throw 'Windows required.' }
    if (-not $DataPath) { $DataPath = Join-Path $env:LOCALAPPDATA 'StockRecommendationEngine' }
    if (-not $EnginePath) { $EnginePath = Join-Path $DataPath 'native-engine-0.14.13' }
    if (-not (Test-Path -LiteralPath $EnginePath -PathType Container)) { throw 'Installed engine not found; no files changed.' }
    if (-not $PythonPath) {
        $found = @(Get-ChildItem -LiteralPath $DataPath -Filter python.exe -File -Recurse -ErrorAction Stop | Select-Object -ExpandProperty FullName)
        if ($found.Count -ne 1) { throw 'Specify -PythonPath pointing to your existing SRE Python 3.14.3 or 3.12.10 python.exe. No dependencies will be installed.' }
        $PythonPath = $found[0]
    }
    if (-not [IO.Path]::IsPathRooted($PythonPath) -or -not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) { throw 'Existing absolute PythonPath required.' }
    # Verify package bytes in PowerShell BEFORE executing the Python deployment code.
    $hashFile = Join-Path $PSScriptRoot 'PACKAGE_HASHES.json'
    $hashes = Get-Content -LiteralPath $hashFile -Raw | ConvertFrom-Json
    foreach ($property in $hashes.PSObject.Properties) {
        $relative = [string]$property.Name
        if ($relative.Contains('..') -or $relative.Contains(':') -or [IO.Path]::IsPathRooted($relative)) { throw 'Unsafe package path.' }
        $path = Join-Path $PSScriptRoot $relative
        $item = Get-Item -LiteralPath $path -Force
        if ($item -is [IO.FileInfo]) { $cursor = $item.Directory } else { $cursor = $item }
        while ($null -ne $cursor) {
            if (($cursor.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'Reparse point refused.' }
            $cursor = $cursor.Parent
        }
        if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'Reparse point refused.' }
        if ((Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant() -ne [string]$property.Value) { throw "Package hash mismatch: $relative" }
    }
    $arguments = @('-I','-B',(Join-Path $PSScriptRoot 'c01_patch.py'),$Action,'--engine',$EnginePath,'--data',$DataPath)
    if ($ReceiptPath) { $arguments += @('--receipt',$ReceiptPath) }
    & $PythonPath @arguments
    if ($LASTEXITCODE -ne 0) { throw "C01 $Action stopped. Keep SRE closed if a PREPARED/ROLLING_BACK receipt exists. Retain the displayed transaction directory." }
}
