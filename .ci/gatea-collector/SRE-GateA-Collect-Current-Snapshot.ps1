#requires -Version 5.1
<#
Read-only SRE Gate A snapshot collector. No administrator rights or new software.
Close SRE before running. This script never starts/stops SRE or opens original
databases through SQLite. It locks originals for reading, copies DB + WAL/journal,
and uses Windows' built-in SQLite backup API ONLY on those private copies.
Upload only the ZIP printed after SUCCESS. A failure produces no accepted ZIP.
#>
[CmdletBinding()]
param(
    [string]$AppDataRoot = (Join-Path $env:LOCALAPPDATA 'StockRecommendationEngine'),
    [string]$EngineRoot = '',
    [string]$OutputDirectory = ''
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Get-SreHash([string]$Path) {
    # FileShare.Read also works while the collector holds a read-only DB lock.
    $stream = [IO.File]::Open($Path, 'Open', 'Read', 'Read')
    $sha = [Security.Cryptography.SHA256]::Create()
    try { return ([BitConverter]::ToString($sha.ComputeHash($stream))).Replace('-', '').ToLowerInvariant() }
    finally { $sha.Dispose(); $stream.Dispose() }
}
function Test-SreInside([string]$Path, [string]$Parent) {
    return $Path.Equals($Parent, [StringComparison]::OrdinalIgnoreCase) -or
        $Path.StartsWith($Parent.TrimEnd('\','/') + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)
}
function Test-SreSqliteFile([string]$Path) {
    if ($Path -match '(?i)\.(sqlite|sqlite3|db|db3)$') { return $true }
    if ($Path -match '(?i)-(wal|shm|journal)$') { return $false }
    $stream=[IO.File]::Open($Path,'Open','Read','Read')
    try {
        if ($stream.Length -lt 16) { return $false }
        $header=New-Object byte[] 16
        [void]$stream.Read($header,0,16)
        return [Text.Encoding]::ASCII.GetString($header) -ceq "SQLite format 3`0"
    } finally { $stream.Dispose() }
}
function Assert-SreStopped([string]$DataRoot, [string]$InstallRoot) {
    # Fail closed if the process inventory cannot be read. Do not kill anything.
    $processes = @(Get-CimInstance Win32_Process -ErrorAction Stop)
    foreach ($p in $processes) {
        if ($p.ProcessId -eq $PID) { continue }
        $name = [string]$p.Name
        $exe = [string]$p.ExecutablePath
        $cmd = [string]$p.CommandLine
        $isShell = $name -match '^(powershell|pwsh|cmd|conhost)\.exe$'
        $inInstall = $exe -and ((Test-SreInside $exe $InstallRoot) -or (Test-SreInside $exe $DataRoot))
        $namedApp = $name -match '^(StockRecommendationEngine|stock-recommendation-engine|stock_app_launcher|stock_app_ops_launcher|sre)\.exe$'
        $backend = $name -match '^(python(w)?|uvicorn)(\.exe)?$' -and
            ($cmd -match '(run_modern_ui|stock_app_launcher|stock_app_ops_launcher|modern_ui[./\\:]|uvicorn.+modern_ui)' -or
             ($cmd -and $cmd.IndexOf($InstallRoot, [StringComparison]::OrdinalIgnoreCase) -ge 0))
        if (($inInstall -and -not $isShell) -or $namedApp -or $backend) {
            throw "SRE appears to be running (PID $($p.ProcessId), $name). Close SRE and rerun this script. No process was stopped."
        }
    }
}
function Get-SreFiles([string]$Root, [string]$Label, [string]$SkipRoot, $Excluded) {
    $pending = New-Object 'Collections.Generic.Stack[string]'
    $pending.Push($Root)
    while ($pending.Count) {
        $folder = $pending.Pop()
        foreach ($item in Get-ChildItem -LiteralPath $folder -Force -ErrorAction Stop) {
            $relative = $item.FullName.Substring($Root.Length).TrimStart('\','/')
            if ($SkipRoot -and (Test-SreInside $item.FullName $SkipRoot)) { continue }
            $why = $null
            if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { $why = 'REPARSE_POINT_NOT_FOLLOWED' }
            elseif ($item.PSIsContainer -and $item.Name -match '^(\.git|\.venv|venv|env|node_modules|__pycache__|\.pytest_cache|\.mypy_cache|site-packages|Scripts|Lib|Include|DLLs|tcl|\.tox|\.ruff_cache|\.build|build|dist|target)$') { $why = 'DEPENDENCY_OR_BUILD_DIRECTORY' }
            elseif ($Label -eq 'application-state' -and $item.PSIsContainer -and $item.Name -match '^native-engine-') { $why = 'OTHER_INSTALLED_ENGINE_VERSION' }
            elseif ($item.PSIsContainer -and $item.Name -match '(?i)(^v10[-_].*runtime$|^runtime[-_]?v10$|^private[-_]runtime$|^replay[-_](feature|input)[-_]cache|^historical_replay_(feature|input)_cache|^replay_v10_(features|cache))') { $why = 'PRIVATE_RUNTIME_OR_REPLAY_FEATURE_CACHE' }
            elseif (-not $item.PSIsContainer -and $item.Name -match '(?i)^(\.env($|\.)|credentials?($|\.)|secrets?($|\.)|tokens?($|\.)|id_rsa|id_ed25519|.*\.(pem|pfx|p12|key)$)') { $why = 'CREDENTIAL_FILE' }
            elseif (-not $item.PSIsContainer -and $item.Name -match '(?i)\.(exe|dll|pyd|pyc|pyo|whl|msi|msix|zip|7z|tar|gz|log|dmp|iso|mp4|webm)$') { $why = 'BINARY_DEPENDENCY_ARCHIVE_OR_LOG' }
            elseif (-not $item.PSIsContainer -and $item.Name -match '(?i)^historical_replay_input_cache.*\.(sqlite3?|db)(-wal|-shm|-journal)?$') { $why = 'REGENERABLE_REPLAY_INPUT_CACHE' }
            if ($why) { [void]$Excluded.Add([ordered]@{path="$Label/$($relative.Replace('\','/'))"; reason=$why}); continue }
            if ($item.PSIsContainer) { $pending.Push($item.FullName); continue }
            [pscustomobject]@{source=$item.FullName; relative="$Label/$($relative.Replace('\','/'))"; length=$item.Length; ticks=$item.LastWriteTimeUtc.Ticks}
        }
    }
}
function Initialize-SreSqlite {
    if ('SreGateASnapshotSqlite' -as [type]) { return }
    Add-Type -TypeDefinition @'
using System;
using System.IO;
using System.Text;
using System.Runtime.InteropServices;
using System.Threading;
public static class SreGateASnapshotSqlite {
    const string Dll = "winsqlite3.dll";
    [DllImport(Dll, CallingConvention=CallingConvention.Cdecl)] static extern int sqlite3_open_v2(byte[] p, out IntPtr db, int flags, IntPtr vfs);
    [DllImport(Dll, CallingConvention=CallingConvention.Cdecl)] static extern int sqlite3_close_v2(IntPtr db);
    [DllImport(Dll, CallingConvention=CallingConvention.Cdecl)] static extern IntPtr sqlite3_errmsg(IntPtr db);
    [DllImport(Dll, CallingConvention=CallingConvention.Cdecl)] static extern IntPtr sqlite3_backup_init(IntPtr dst, byte[] dn, IntPtr src, byte[] sn);
    [DllImport(Dll, CallingConvention=CallingConvention.Cdecl)] static extern int sqlite3_backup_step(IntPtr b, int n);
    [DllImport(Dll, CallingConvention=CallingConvention.Cdecl)] static extern int sqlite3_backup_finish(IntPtr b);
    [DllImport(Dll, CallingConvention=CallingConvention.Cdecl)] static extern int sqlite3_prepare_v2(IntPtr db, byte[] sql, int n, out IntPtr st, IntPtr tail);
    [DllImport(Dll, CallingConvention=CallingConvention.Cdecl)] static extern int sqlite3_step(IntPtr st);
    [DllImport(Dll, CallingConvention=CallingConvention.Cdecl)] static extern IntPtr sqlite3_column_text(IntPtr st, int col);
    [DllImport(Dll, CallingConvention=CallingConvention.Cdecl)] static extern int sqlite3_finalize(IntPtr st);
    static byte[] Utf8(string s) { return Encoding.UTF8.GetBytes(s + "\0"); }
    static string Text(IntPtr p) {
        if(p == IntPtr.Zero) return "";
        int n=0; while(Marshal.ReadByte(p,n)!=0) n++;
        byte[] b=new byte[n]; Marshal.Copy(p,b,0,n); return Encoding.UTF8.GetString(b);
    }
    static void Check(int rc, IntPtr db, string stage) { if(rc!=0) throw new IOException(stage+": SQLite "+rc+" "+Text(sqlite3_errmsg(db))); }
    public static string Query(string path, string sql) {
        IntPtr db=IntPtr.Zero, st=IntPtr.Zero;
        try {
            Check(sqlite3_open_v2(Utf8(path),out db,1,IntPtr.Zero),db,"open snapshot read-only");
            Check(sqlite3_prepare_v2(db,Utf8(sql),-1,out st,IntPtr.Zero),db,"prepare verification");
            StringBuilder result=new StringBuilder(); int rc;
            while((rc=sqlite3_step(st))==100) { if(result.Length>0) result.Append("\n"); result.Append(Text(sqlite3_column_text(st,0))); }
            if(rc!=101) Check(rc,db,"verify snapshot"); return result.ToString();
        } finally { if(st!=IntPtr.Zero) sqlite3_finalize(st); if(db!=IntPtr.Zero) sqlite3_close_v2(db); }
    }
    public static void BackupCopy(string capturedSource, string destination) {
        IntPtr src=IntPtr.Zero,dst=IntPtr.Zero,b=IntPtr.Zero;
        try {
            // READWRITE is deliberate: recovery/checkpoint may touch this PRIVATE COPY.
            Check(sqlite3_open_v2(Utf8(capturedSource),out src,2,IntPtr.Zero),src,"open captured DB");
            Check(sqlite3_open_v2(Utf8(destination),out dst,6,IntPtr.Zero),dst,"create backup");
            b=sqlite3_backup_init(dst,Utf8("main"),src,Utf8("main"));
            if(b==IntPtr.Zero) throw new IOException("SQLite backup_init: "+Text(sqlite3_errmsg(dst)));
            var clock=System.Diagnostics.Stopwatch.StartNew(); int rc;
            do { rc=sqlite3_backup_step(b,256); if(rc==5||rc==6) Thread.Sleep(50);
                 if(clock.Elapsed.TotalMinutes>10) throw new IOException("SQLite copy backup timed out");
            } while(rc==0||rc==5||rc==6);
            if(rc!=101) Check(rc,dst,"backup step");
            IntPtr finished=b; b=IntPtr.Zero; Check(sqlite3_backup_finish(finished),dst,"backup finish");
        } finally { if(b!=IntPtr.Zero) sqlite3_backup_finish(b); if(dst!=IntPtr.Zero) sqlite3_close_v2(dst); if(src!=IntPtr.Zero) sqlite3_close_v2(src); }
        if(Query(destination,"PRAGMA integrity_check")!="ok") throw new IOException("Snapshot integrity_check failed: "+destination);
    }
}
'@
}
function Copy-SreLockedStream($Stream, [string]$Destination) {
    [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($Destination)) | Out-Null
    $outStream = [IO.File]::Open($Destination, 'CreateNew', 'Write', 'None')
    try { $Stream.Position=0; $Stream.CopyTo($outStream) } finally { $outStream.Dispose() }
}
function Protect-SreJson([string]$Path) {
    # Only configuration JSON is redacted. Original source hashes are retained.
    $text = [IO.File]::ReadAllText($Path)
    if ($text -notmatch '(?i)"(api[_-]?key|access[_-]?token|refresh[_-]?token|client[_-]?secret|password|secret[_-]?key|authorization)"\s*:') { return $false }
    $obj = $text | ConvertFrom-Json -ErrorAction Stop
    $changed = [ref]$false
    function Clear-SreSecret($Value, $Changed) {
        if ($null -eq $Value -or $Value -is [string] -or $Value.GetType().IsPrimitive) { return }
        if ($Value -is [Collections.IEnumerable] -and $Value -isnot [pscustomobject]) {
            foreach ($v in $Value) { Clear-SreSecret $v $Changed }; return
        }
        foreach ($prop in @($Value.PSObject.Properties)) {
            if ($prop.Name -match '^(?i:api[_-]?key|access[_-]?token|refresh[_-]?token|client[_-]?secret|password|secret[_-]?key|authorization)$') {
                if ($null -ne $prop.Value -and [string]$prop.Value -ne '') { $prop.Value='[REDACTED]'; $Changed.Value=$true }
            } else { Clear-SreSecret $prop.Value $Changed }
        }
    }
    Clear-SreSecret $obj $changed
    if ($changed.Value) { [IO.File]::WriteAllText($Path, ($obj | ConvertTo-Json -Depth 100), (New-Object Text.UTF8Encoding($false))) }
    return $changed.Value
}
function New-SreGateASnapshot([string]$DataRoot, [string]$InstallRoot, [string]$OutputRoot) {
    if ($env:OS -ne 'Windows_NT') { throw 'Run this collector on the Windows computer with SRE installed.' }
    $DataRoot = [IO.Path]::GetFullPath($DataRoot).TrimEnd('\','/')
    if (-not $InstallRoot) { $InstallRoot = Join-Path $DataRoot 'native-engine-0.14.13' }
    $InstallRoot = [IO.Path]::GetFullPath($InstallRoot).TrimEnd('\','/')
    if (-not (Test-Path -LiteralPath (Join-Path $InstallRoot 'modern_ui\api.py') -PathType Leaf) -or
        -not (Test-Path -LiteralPath (Join-Path $InstallRoot 'stock_app\live_decision_v1.py') -PathType Leaf)) { throw "Expected installed SRE source not found: $InstallRoot" }
    if (-not $OutputRoot) { $OutputRoot = [Environment]::GetFolderPath('Desktop'); if (-not $OutputRoot) { $OutputRoot = Join-Path $env:USERPROFILE 'Downloads' } }
    $OutputRoot = [IO.Path]::GetFullPath($OutputRoot)
    if ((Test-SreInside $OutputRoot $DataRoot) -or (Test-SreInside $OutputRoot $InstallRoot)) { throw 'Snapshot output must be outside the SRE installation and application-data directories.' }
    Assert-SreStopped $DataRoot $InstallRoot
    Initialize-SreSqlite
    $excluded = New-Object Collections.ArrayList
    $files = @(Get-SreFiles $InstallRoot 'engine' '' $excluded) + @(Get-SreFiles $DataRoot 'application-state' $InstallRoot $excluded)
    $fileByRelative = @{}; foreach ($f in $files) { $fileByRelative[$f.relative]=$f }
    if ($files.Count -eq 0) { throw 'No source files found.' }
    $dbs = @($files | Where-Object { Test-SreSqliteFile $_.source })
    $dbPaths = @{}; $sidecarPaths = @{}
    foreach ($db in $dbs) {
        $dbPaths[$db.source]=$true
        foreach ($suffix in @('-wal','-shm','-journal')) { $sidecarPaths[$db.source+$suffix]=$true }
    }
    foreach ($required in @('stock_recommendation_engine.sqlite3','phase81_validation.sqlite3')) {
        if (-not @($dbs | Where-Object { [IO.Path]::GetFileName($_.source) -eq $required }).Count) { throw "Required active database not found: $required. No partial snapshot will be accepted." }
    }
    $bytes = ($files | Measure-Object -Property length -Sum).Sum
    $drive = New-Object IO.DriveInfo([IO.Path]::GetPathRoot($OutputRoot))
    $needed = 3 * $bytes + 512MB
    if ($drive.AvailableFreeSpace -lt $needed) { throw ('Insufficient free space: need approximately {0:N2} GB for capture, DB normalization and verified ZIP.' -f ($needed/1GB)) }
    [IO.Directory]::CreateDirectory($OutputRoot) | Out-Null
    $name = 'SRE-GateA-Current-Snapshot-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [Guid]::NewGuid().ToString('N').Substring(0,6)
    $work = Join-Path $OutputRoot ($name + '-working')
    $capture = Join-Path $work 'raw-private-copy'
    $payload = Join-Path $work 'snapshot'
    $zip = Join-Path $OutputRoot ($name + '.zip')
    $partialZip = Join-Path $work 'unverified.zip'
    $locks = @{}
    $records = New-Object Collections.ArrayList
    $recordByRelative = @{}
    $databaseRecords = New-Object Collections.ArrayList
    $finished = $false
    try {
        [IO.Directory]::CreateDirectory($capture) | Out-Null
        [IO.Directory]::CreateDirectory($payload) | Out-Null
        # Lock ALL selected DBs and sidecars together before copying ANY data.
        foreach ($f in $files) {
            if ($dbPaths.ContainsKey($f.source) -or $sidecarPaths.ContainsKey($f.source)) {
                try { $locks[$f.source] = [IO.File]::Open($f.source, 'Open', 'Read', 'Read') }
                catch { throw "Database is in use or unreadable: $($f.relative). Close SRE and rerun. $($_.Exception.Message)" }
            }
        }
        Assert-SreStopped $DataRoot $InstallRoot
        Write-Host ('Capturing {0} files ({1:N1} MB); {2} databases. Keep SRE closed.' -f $files.Count,($bytes/1MB),$dbs.Count)
        foreach ($f in $files) {
            $hash = Get-SreHash $f.source
            $dest = Join-Path $capture $f.relative
            if ($locks.ContainsKey($f.source)) { Copy-SreLockedStream $locks[$f.source] $dest }
            else { [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($dest)) | Out-Null; [IO.File]::Copy($f.source,$dest,$false) }
            if ((Get-SreHash $dest) -ne $hash -or (Get-SreHash $f.source) -ne $hash) { throw "Source changed during capture: $($f.relative). Close SRE and rerun." }
            $r = [ordered]@{path=$f.relative; source_sha256=$hash; source_bytes=$f.length; captured_sha256=$hash; transformed=$false; archive_included=$true}
            [void]$records.Add($r); $recordByRelative[$f.relative]=$r
        }
        $allAfter = @(Get-SreFiles $InstallRoot 'engine' '' (New-Object Collections.ArrayList)) + @(Get-SreFiles $DataRoot 'application-state' $InstallRoot (New-Object Collections.ArrayList))
        if ((@($allAfter.relative | Sort-Object) -join "`n") -cne (@($files.relative | Sort-Object) -join "`n")) { throw 'Source inventory changed during capture. Keep SRE closed and rerun.' }
        foreach ($r in $records) {
            $f = $fileByRelative[$r.path]
            if ((Get-SreHash $f.source) -ne $r.source_sha256) { throw "Source changed before snapshot completion: $($r.path)" }
        }
        Assert-SreStopped $DataRoot $InstallRoot
        # All originals remain read-locked until the complete capture is verified.
        foreach ($handle in $locks.Values) { $handle.Dispose() }; $locks.Clear()
        foreach ($f in $files) {
            if ($sidecarPaths.ContainsKey($f.source)) { $recordByRelative[$f.relative].archive_included=$false; continue }
            $src = Join-Path $capture $f.relative
            $dest = Join-Path $payload $f.relative
            [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($dest)) | Out-Null
            $record = $recordByRelative[$f.relative]
            if ($dbPaths.ContainsKey($f.source)) {
                [SreGateASnapshotSqlite]::BackupCopy($src,$dest)
                $record.transformed=$true
                [void]$databaseRecords.Add([ordered]@{path=$f.relative; integrity_check='ok'; sqlite_backup='WINDOWS_SQLITE_BACKUP_FROM_PRIVATE_DB_AND_SIDECARS'; tables=[SreGateASnapshotSqlite]::Query($dest,"SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")})
            } else {
                [IO.File]::Copy($src,$dest,$false)
                if ([IO.Path]::GetExtension($dest) -eq '.json' -and (Protect-SreJson $dest)) { $record.transformed=$true; $record['redacted_secret_values']=$true }
            }
            $record.captured_sha256=Get-SreHash $dest
        }
        # Sidecars are deliberately absent from the final ZIP: each normalized DB
        # contains their committed state. Preserve their original hashes as evidence.
        $manifest = [ordered]@{
            schema='SRE_GATE_A_CURRENT_SNAPSHOT_V1'; created_utc=[DateTime]::UtcNow.ToString('o')
            source_engine=$InstallRoot; source_application_data=$DataRoot
            powershell=$PSVersionTable.PSVersion.ToString(); platform=[Environment]::OSVersion.VersionString
            original_databases_opened_by_sqlite=$false; original_files_written=$false
            stopped_process_checks='PASS'; stable_source_inventory_and_hashes='PASS'
            source_files=@($records); databases=@($databaseRecords); exclusions=@($excluded)
            notes=@('Source paths and source hashes describe originals; captured hashes describe normalized or redacted files.','Do not interpret a backup hash change as a changed portfolio. Compare table contents.','Replay feature/input caches and dependencies excluded; official price/fundamental and entry evidence retained unless explicitly listed in exclusions.','Snapshots contain private financial portfolio data. Upload privately to the Work task; do not publish to GitHub.')
        }
        [IO.File]::WriteAllText((Join-Path $payload 'snapshot-manifest.json'),($manifest | ConvertTo-Json -Depth 12),(New-Object Text.UTF8Encoding($false)))
        # Release-time collector and instructions are embedded for reproducibility.
        if ($script:CollectorPath -and (Test-Path -LiteralPath $script:CollectorPath)) { [IO.File]::Copy($script:CollectorPath,(Join-Path $payload 'COLLECTOR.ps1'),$false) }
        $checksums = @{}
        foreach ($f in Get-ChildItem -LiteralPath $payload -Recurse -File -Force) { $rel=$f.FullName.Substring($payload.Length+1).Replace('\','/'); $checksums[$rel]=Get-SreHash $f.FullName }
        Add-Type -AssemblyName System.IO.Compression
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        # .NET Framework's CreateFromDirectory uses backslashes in ZIP names.
        # Create explicit forward-slash entries for portable Work/Linux extraction.
        $writer=[IO.Compression.ZipFile]::Open($partialZip,[IO.Compression.ZipArchiveMode]::Create)
        try {
            foreach ($rel in $checksums.Keys) {
                [IO.Compression.ZipFileExtensions]::CreateEntryFromFile($writer,(Join-Path $payload $rel),$rel,[IO.Compression.CompressionLevel]::Optimal) | Out-Null
            }
        } finally { $writer.Dispose() }
        $archive = [IO.Compression.ZipFile]::OpenRead($partialZip)
        $seen = @{}
        try {
            foreach ($entry in $archive.Entries) {
                if ($entry.FullName.EndsWith('/')) { continue }
                if ($seen.ContainsKey($entry.FullName) -or -not $checksums.ContainsKey($entry.FullName)) { throw "Unexpected/duplicate archive entry: $($entry.FullName)" }
                $stream=$entry.Open(); $sha=[Security.Cryptography.SHA256]::Create()
                try { $actual=([BitConverter]::ToString($sha.ComputeHash($stream))).Replace('-','').ToLowerInvariant() } finally { $sha.Dispose(); $stream.Dispose() }
                if ($actual -ne $checksums[$entry.FullName]) { throw "Archive integrity failure: $($entry.FullName)" }
                $seen[$entry.FullName]=$true
            }
            if ($seen.Count -ne $checksums.Count) { throw 'Archive is missing captured files.' }
        } finally { $archive.Dispose() }
        [IO.File]::Move($partialZip,$zip)
        $zipHash=Get-SreHash $zip
        $finished=$true
        Write-Host ''
        Write-Host 'SUCCESS: consistent snapshot captured and every ZIP entry SHA-256 verified.' -ForegroundColor Green
        Write-Host "UPLOAD THIS ONE FILE: $zip"
        Write-Host "ZIP SHA-256: $zipHash"
        return [pscustomobject]@{zip=$zip; sha256=$zipHash; files=$seen.Count; databases=$dbs.Count}
    } finally {
        foreach ($handle in $locks.Values) { $handle.Dispose() }
        if (Test-Path -LiteralPath $work) { Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction SilentlyContinue }
        if (-not $finished -and (Test-Path -LiteralPath $zip)) { Remove-Item -LiteralPath $zip -Force -ErrorAction SilentlyContinue }
        if (-not $finished) { Write-Warning 'Snapshot failed safely. No accepted ZIP was produced. Installation and database originals were not written.' }
    }
}
$script:CollectorPath = $PSCommandPath
if ($MyInvocation.InvocationName -ne '.') {
    try { New-SreGateASnapshot $AppDataRoot $EngineRoot $OutputDirectory | Out-Null }
    catch { Write-Error $_; exit 1 }
}
