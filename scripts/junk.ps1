# Junk cleaner.
#   { mode: 'scan' }                  -> [{ id, bytes, files, admin, readable }]
#   { mode: 'clean', ids: [...] }     -> { freed, files, skipped, results: [{ id, freed, files, skipped }] }
#
# Only deletes files inside the fixed folders below. Never follows junctions or
# symlinks out of them, skips files changed in the last 24 hours where noted,
# and leaves anything locked by a running program alone.
param([string]$Payload = '', [string]$OutFile = '')
. "$PSScriptRoot\_lib.ps1"
trap { Fail $_.Exception.Message }
. "$PSScriptRoot\_fs.ps1"
$a = Get-Args

$win = $env:windir
$local = $env:LOCALAPPDATA

function Browser-Caches {
    $roots = @()
    foreach ($base in @("$local\Google\Chrome\User Data", "$local\Microsoft\Edge\User Data",
                        "$local\BraveSoftware\Brave-Browser\User Data", "$local\Vivaldi\User Data",
                        "$env:APPDATA\Opera Software\Opera Stable", "$env:APPDATA\Opera Software\Opera GX Stable",
                        "$local\Opera Software\Opera Stable", "$local\Opera Software\Opera GX Stable")) {
        if (-not (Test-Path -LiteralPath $base)) { continue }
        $profiles = @(Get-Item -LiteralPath $base) + @(Get-ChildItem -LiteralPath $base -Directory -ErrorAction SilentlyContinue)
        foreach ($p in $profiles) {
            # Only rebuildable caches. Service-worker storage is left alone: web apps keep offline data there.
            foreach ($c in @('Cache\Cache_Data', 'Code Cache', 'GPUCache')) {
                $dir = Join-Path $p.FullName $c
                if (Test-Path -LiteralPath $dir) { $roots += $dir }
            }
        }
    }
    $ff = "$local\Mozilla\Firefox\Profiles"
    if (Test-Path -LiteralPath $ff) {
        Get-ChildItem -LiteralPath $ff -Directory -ErrorAction SilentlyContinue | ForEach-Object {
            $dir = Join-Path $_.FullName 'cache2'
            if (Test-Path -LiteralPath $dir) { $roots += $dir }
        }
    }
    return $roots
}

# id, folders, minimum age in hours, needs admin
$categories = @(
    @{ id = 'user-temp';    roots = @($env:TEMP);                                   age = 24; admin = $false }
    @{ id = 'browser';      roots = @(Browser-Caches);                              age = 0;  admin = $false }
    @{ id = 'thumbnails';   roots = @("$local\Microsoft\Windows\Explorer");         age = 0;  admin = $false; filter = 'thumbcache_*.db' }
    @{ id = 'crash-dumps';  roots = @("$local\CrashDumps");                         age = 0;  admin = $false }
    @{ id = 'win-temp';     roots = @("$win\Temp");                                 age = 24; admin = $true }
    @{ id = 'update-cache'; roots = @("$win\SoftwareDistribution\Download");        age = 0;  admin = $true }
    @{ id = 'error-reports';roots = @("$env:ProgramData\Microsoft\Windows\WER\ReportArchive",
                                      "$env:ProgramData\Microsoft\Windows\WER\ReportQueue"); age = 0; admin = $true }
    @{ id = 'delivery';     roots = @("$win\ServiceProfiles\NetworkService\AppData\Local\Microsoft\Windows\DeliveryOptimization\Cache"); age = 0; admin = $true }
)

# Refuse anything that isn't clearly a cache folder: a drive root or a profile root would be a disaster.
function Safe-Root([string]$root) {
    if (-not $root -or $root.Length -lt 12) { return $false }
    $full = [IO.Path]::GetFullPath($root).TrimEnd('\')
    $forbidden = @($env:SystemDrive, $env:USERPROFILE, $win, $env:ProgramData, $local, $env:APPDATA,
                   [Environment]::GetFolderPath('MyDocuments'), [Environment]::GetFolderPath('Desktop')) |
        Where-Object { $_ } | ForEach-Object { [IO.Path]::GetFullPath($_).TrimEnd('\') }
    return -not ($forbidden -contains $full) -and (Dir-Exists $full)
}

# False when missing or unreadable, instead of throwing like Test-Path does on "access denied".
function Dir-Exists([string]$path) {
    try { return [IO.Directory]::Exists($path) } catch { return $false }
}

# Walks a folder without crossing junctions or symlinks, at any path length.
function Get-Files([string]$root, [string]$filter) {
    $r = [HibFs]::Scan($root, $filter, [string]::IsNullOrEmpty($filter))
    return @{ files = $r.Files; dirs = $r.Dirs; readable = $r.Readable }
}

function Old-Enough($file, [int]$hours) {
    if ($hours -le 0) { return $true }
    return $file.Write -lt [DateTime]::UtcNow.AddHours(-$hours)
}

function Recycle-Bin-Size {
    $bytes = 0; $count = 0
    try {
        $shell = New-Object -ComObject Shell.Application
        foreach ($item in $shell.Namespace(10).Items()) {
            $count++
            try { $bytes += [long]$item.ExtendedProperty('Size') } catch { }
        }
    } catch { }
    return @{ bytes = $bytes; files = $count }
}

if ($a.mode -eq 'scan') {
    $result = @()
    $isAdmin = Test-Admin
    foreach ($c in $categories) {
        $bytes = [long]0; $count = 0
        # Without admin rights these folders can't be measured; the clean asks for rights.
        $readable = -not ($c.admin -and -not $isAdmin)
        foreach ($root in $c.roots) {
            if (-not (Safe-Root $root)) { continue }
            $found = Get-Files $root $c.filter
            if (-not $found.readable) { $readable = $false }
            foreach ($f in $found.files) {
                if (Old-Enough $f $c.age) { $bytes += $f.Size; $count++ }
            }
        }
        $result += [ordered]@{ id = $c.id; bytes = $bytes; files = $count; admin = $c.admin; readable = $readable }
    }
    $bin = Recycle-Bin-Size
    $result += [ordered]@{ id = 'recycle'; bytes = $bin.bytes; files = $bin.files; admin = $false; readable = $true }
    $old = "$env:SystemDrive\Windows.old"
    $result += [ordered]@{ id = 'windows-old'; bytes = 0; files = 0; admin = $true; readable = $true; present = (Test-Path -LiteralPath $old) }
    Send @($result)
    return
}

if ($a.mode -eq 'clean') {
    $ids = @($a.ids)
    $isAdmin = Test-Admin
    $results = @()
    foreach ($c in $categories) {
        if ($ids -notcontains $c.id) { continue }
        if ($c.admin -and -not $isAdmin) {
            $results += [ordered]@{ id = $c.id; freed = 0; files = 0; skipped = 0; needsAdmin = $true }
            continue
        }
        $freed = [long]0; $done = 0; $skipped = 0
        if ($c.id -eq 'delivery' -and (Get-Command Delete-DeliveryOptimizationCache -ErrorAction SilentlyContinue)) {
            $before = 0
            foreach ($root in $c.roots) { if (Safe-Root $root) { foreach ($f in (Get-Files $root).files) { $before += $f.Size; $done++ } } }
            try { Delete-DeliveryOptimizationCache -Force -ErrorAction Stop; $freed = $before } catch { $skipped = $done; $done = 0 }
            $results += [ordered]@{ id = $c.id; freed = $freed; files = $done; skipped = $skipped }
            continue
        }
        foreach ($root in $c.roots) {
            if (-not (Safe-Root $root)) { continue }
            $found = Get-Files $root $c.filter
            foreach ($f in $found.files) {
                if (-not (Old-Enough $f $c.age)) { continue }
                if ([HibFs]::Delete($f.Path)) { $freed += $f.Size; $done++ } else { $skipped++ }
            }
            # Remove folders the clean emptied, deepest first, but never the root itself.
            if (-not $c.filter) {
                # RemoveIfEmpty only ever removes empty folders.
                $found.dirs | Sort-Object { $_.Length } -Descending | ForEach-Object { [void][HibFs]::RemoveIfEmpty($_) }
            }
        }
        $results += [ordered]@{ id = $c.id; freed = $freed; files = $done; skipped = $skipped }
    }
    if ($ids -contains 'recycle') {
        $bin = Recycle-Bin-Size
        try { Clear-RecycleBin -Force -ErrorAction Stop; $results += [ordered]@{ id = 'recycle'; freed = $bin.bytes; files = $bin.files; skipped = 0 } }
        catch { $results += [ordered]@{ id = 'recycle'; freed = 0; files = 0; skipped = $bin.files } }
    }
    $total = [long]0; $files = 0; $skippedAll = 0
    foreach ($r in $results) { $total += $r.freed; $files += $r.files; $skippedAll += $r.skipped }
    Send ([ordered]@{ freed = $total; files = $files; skipped = $skippedAll; results = @($results) })
    return
}

Fail "Unknown mode"
