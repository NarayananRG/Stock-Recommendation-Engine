$ErrorActionPreference = "Stop"

$repo = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$preferred = Join-Path $repo "stock-engine-leg7-source-with-windows-builder"

Write-Host "Live Pilot V1 - read-only Leg 8 app discovery"
Write-Host "No files will be modified."

$candidates = @()
if (Test-Path $preferred) {
    $candidates += Get-Item $preferred
}
$candidates += Get-ChildItem -Path $repo -Directory -ErrorAction SilentlyContinue |
    Where-Object {
        $_.Name -match "stock.*engine|leg7|leg8|windows.*builder"
    }

$candidates = $candidates | Sort-Object FullName -Unique

if (-not $candidates) {
    throw "LEG8_SOURCE_FOLDER_NOT_FOUND_UNDER_REPO"
}

foreach ($root in $candidates) {
    Write-Host ""
    Write-Host "=== ROOT ==="
    Write-Host $root.FullName

    $files = Get-ChildItem -Path $root.FullName -Recurse -File -Include *.py,*.cmd,*.ps1,*.json |
        Where-Object {
            $_.FullName -notmatch "\\dist|\\build|\\__pycache__|\\.venv|\\venv"
        }

    Write-Host "--- likely UI/runtime files ---"
    $files |
        Where-Object { $_.Name -match "main|app|ui|window|settings|health|backup|support|pipeline" } |
        Select-Object -First 80 -ExpandProperty FullName

    Write-Host "--- keyword hits ---"
    $patterns = @(
        "Update & Analyze",
        "Capital Plan",
        "Health",
        "Backup",
        "Support Bundle",
        "0.8.0-leg8",
        "sqlite",
        "recommendation"
    )
    foreach ($pattern in $patterns) {
        Write-Host ""
        Write-Host "### $pattern"
        Select-String -Path ($files.FullName) -Pattern $pattern -SimpleMatch -ErrorAction SilentlyContinue |
            Select-Object -First 30 Path,LineNumber,Line |
            Format-Table -AutoSize -Wrap
    }
}
