param([string]$PythonPath,[string]$EnginePath,[string]$DataPath)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'COMMON_C01.ps1')
Invoke-C01Patch -Action apply -PythonPath $PythonPath -EnginePath $EnginePath -DataPath $DataPath -ReceiptPath ''
