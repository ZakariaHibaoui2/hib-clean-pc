# Big files in your own folders, and old installers in Downloads.
#   { mode: 'scan' }              -> { folders: [ { id, path } ], big: [ file ], installers: [ file ], minBytes, installerDays }
#                                    file = { path, name, folder, size, modified }
#   { mode: 'recycle', paths }    -> { results: [ { path, ok, error } ], freed }
# Recycle only moves files to the Recycle Bin, so everything can be put back. It never
# deletes for good: a file the Recycle Bin can't take is refused, not deleted. Only files
# the scan itself would list can be recycled.
# Tests point the scan at a sandbox with HIB_TEST_BIGFILES_ROOT (must be inside TEMP).
param([string]$Payload = '', [string]$OutFile = '')
. "$PSScriptRoot\_lib.ps1"
trap { Fail $_.Exception.Message }
. "$PSScriptRoot\_fs.ps1"
$a = Get-Args

$MinBytes = 100MB
$TopBig = 30
$InstallerDays = 30
$InstallerExt = @('.exe', '.msi', '.iso', '.zip')
# Cloud-only placeholders (OneDrive "free up space") take no room on this PC: 0x1000 offline,
# 0x40000 recall on open, 0x400000 recall on data access.
$CloudOnly = 0x1000 -bor 0x40000 -bor 0x400000

function Full([string]$p) { return [IO.Path]::GetFullPath($p).TrimEnd('\') }

function Folders {
    $test = $env:HIB_TEST_BIGFILES_ROOT
    if ($test) {
        $root = Full $test
        $temps = @((Full $env:TEMP), (Full ([IO.Path]::GetTempPath()))) | Select-Object -Unique
        $inside = $false
        foreach ($t in $temps) { if ($root.StartsWith($t + '\', [StringComparison]::OrdinalIgnoreCase)) { $inside = $true } }
        if (-not $inside) { Fail 'HIB_TEST_BIGFILES_ROOT must be inside the TEMP folder' }
        if ($env:HIB_TEST_BIGFILES_MIN) { $script:MinBytes = [long]$env:HIB_TEST_BIGFILES_MIN }
        return ,@([ordered]@{ id = 'downloads'; path = $root })
    }
    $list = @()
    $downloads = $null
    try { $downloads = (New-Object -ComObject Shell.Application).NameSpace('shell:Downloads').Self.Path } catch { }
    if (-not $downloads) { $downloads = Join-Path $env:USERPROFILE 'Downloads' }
    $list += [ordered]@{ id = 'downloads'; path = $downloads }
    foreach ($pair in @(@('desktop', 'Desktop'), @('documents', 'MyDocuments'), @('videos', 'MyVideos'), @('pictures', 'MyPictures'), @('music', 'MyMusic'))) {
        $p = [Environment]::GetFolderPath($pair[1])
        if ($p) { $list += [ordered]@{ id = $pair[0]; path = $p } }
    }
    # Only real folders inside the profile-like places; never a drive root or the profile itself.
    $out = @()
    foreach ($f in $list) {
        if (-not $f.path -or -not (Test-Path -LiteralPath $f.path -PathType Container)) { continue }
        $full = Full $f.path
        if ($full.Length -le 3 -or $full -ieq (Full $env:USERPROFILE)) { continue }
        $f.path = $full
        $out += $f
    }
    # A folder inside another listed folder (say Documents moved into Desktop) is walked once.
    $keep = @()
    foreach ($f in $out) {
        $nested = $false
        foreach ($g in $out) {
            if ($g -ne $f -and $f.path.StartsWith($g.path + '\', [StringComparison]::OrdinalIgnoreCase)) { $nested = $true }
        }
        $dupe = @($keep | Where-Object { $_.path -ieq $f.path }).Count -gt 0
        if (-not $nested -and -not $dupe) { $keep += $f }
    }
    return ,$keep
}

function Scan {
    $folders = Folders
    $cutoff = [DateTime]::UtcNow.AddDays(-$InstallerDays)
    $big = @(); $installers = @()
    foreach ($f in $folders) {
        $r = [HibFs]::Scan($f.path, $null, $true, $true)
        foreach ($e in $r.Files) {
            if (($e.Attributes -band $CloudOnly) -ne 0) { continue }
            $file = [ordered]@{
                path = $e.Path; name = [IO.Path]::GetFileName($e.Path); folder = $f.id
                size = $e.Size; modified = $e.Write.ToString('o')
            }
            if ($e.Size -ge $MinBytes) { $big += $file }
            if ($f.id -eq 'downloads' -and $e.Write -lt $cutoff -and $InstallerExt -contains [IO.Path]::GetExtension($e.Path).ToLowerInvariant()) {
                $installers += $file
            }
        }
    }
    return [ordered]@{
        folders = @($folders)
        big = @($big | Sort-Object { $_.size } -Descending | Select-Object -First $TopBig)
        installers = @($installers | Sort-Object { $_.size } -Descending)
        minBytes = $MinBytes
        installerDays = $InstallerDays
    }
}

# Can this file go to the Recycle Bin, so it's recoverable? Windows deletes files for good when
# the bin is turned off, too small for the file, or on drives without one (USB sticks, network).
function Recycle-Problem([string]$Path, [long]$Size) {
    $pol = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Policies\Explorer'
    if ((Get-ItemProperty $pol -ErrorAction SilentlyContinue).NoRecycleFiles -eq 1) { return 'recycle-bin-off' }
    $letter = [IO.Path]::GetPathRoot($Path).TrimEnd('\')
    if ($letter -notmatch '^[A-Za-z]:$') { return 'no-recycle-bin' }
    $vol = Get-CimInstance Win32_Volume -Filter "DriveLetter='$letter'" -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $vol -or [int]$vol.DriveType -ne 3) { return 'no-recycle-bin' }
    $max = $null
    if ([string]$vol.DeviceID -match '(\{[0-9a-fA-F-]+\})') {
        $k = Get-ItemProperty "HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\BitBucket\Volume\$($Matches[1])" -ErrorAction SilentlyContinue
        if ($k) {
            if ($k.NukeOnDelete -eq 1) { return 'recycle-bin-off' }
            if ($null -ne $k.MaxCapacity) { $max = [long]$k.MaxCapacity * 1MB }
        }
    }
    if ($null -eq $max) { $max = [long]([double]$vol.Capacity * 0.05) }   # Windows' default size, at least
    if ($Size -ge $max) { return 'too-big-for-bin' }
    return $null
}

if ($a.mode -eq 'scan') { Send (Scan); return }

if ($a.mode -eq 'recycle') {
    $wanted = @($a.paths | ForEach-Object { [string]$_ } | Where-Object { $_ })
    if ($wanted.Count -eq 0) { Fail 'Nothing to recycle' }
    $now = Scan
    $allowed = @{}
    foreach ($f in @($now.big) + @($now.installers)) { $allowed[$f.path.ToLowerInvariant()] = $f }
    Add-Type -AssemblyName Microsoft.VisualBasic
    $results = @(); $freed = 0
    foreach ($p in $wanted) {
        $f = $allowed[$p.ToLowerInvariant()]
        if (-not $f) { $results += [ordered]@{ path = $p; ok = $false; error = 'not-listed' }; continue }
        $item = Get-Item -LiteralPath $f.path -Force -ErrorAction SilentlyContinue
        # A file only (OneDrive files are reparse points too; the scan already left out links).
        if (-not $item -or $item.PSIsContainer) {
            $results += [ordered]@{ path = $p; ok = $false; error = 'not-listed' }; continue
        }
        $problem = Recycle-Problem $f.path $f.size
        if ($problem) { $results += [ordered]@{ path = $p; ok = $false; error = $problem }; continue }
        try {
            [Microsoft.VisualBasic.FileIO.FileSystem]::DeleteFile($f.path,
                [Microsoft.VisualBasic.FileIO.UIOption]::OnlyErrorDialogs,
                [Microsoft.VisualBasic.FileIO.RecycleOption]::SendToRecycleBin,
                [Microsoft.VisualBasic.FileIO.UICancelOption]::DoNothing)
            if (Test-Path -LiteralPath $f.path) { $results += [ordered]@{ path = $p; ok = $false; error = 'in-use' } }
            else { $results += [ordered]@{ path = $p; ok = $true; error = $null }; $freed += $f.size }
        } catch {
            $results += [ordered]@{ path = $p; ok = $false; error = 'in-use' }
        }
    }
    Send ([ordered]@{ results = $results; freed = $freed })
    return
}

Fail 'Unknown mode'
