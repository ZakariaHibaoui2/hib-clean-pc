# Apps that start with Windows.
#   { mode: 'list' }                         -> [{ id, name, command, path, publisher, enabled, admin, scope, icon, known }]
#   { mode: 'set', id, enabled: bool }      -> { id, enabled }
#
# Uses the same on/off switch as Task Manager's Startup tab (the StartupApproved
# keys), so nothing is deleted and Task Manager shows the same state.
param([string]$Payload = '', [string]$OutFile = '')
. "$PSScriptRoot\_lib.ps1"
trap { Fail $_.Exception.Message }
$a = Get-Args
Add-Type -AssemblyName System.Drawing

$approvedBase = 'Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved'
$sources = @(
    @{ scope = 'user';    hive = 'HKCU'; key = 'Software\Microsoft\Windows\CurrentVersion\Run';             approved = 'Run' }
    @{ scope = 'machine'; hive = 'HKLM'; key = 'SOFTWARE\Microsoft\Windows\CurrentVersion\Run';             approved = 'Run' }
    @{ scope = 'machine'; hive = 'HKLM'; key = 'SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Run'; approved = 'Run32' }
)
$folders = @(
    @{ scope = 'user';    hive = 'HKCU'; path = [Environment]::GetFolderPath('Startup');       approved = 'StartupFolder' }
    @{ scope = 'machine'; hive = 'HKLM'; path = [Environment]::GetFolderPath('CommonStartup'); approved = 'StartupFolder' }
)

# Apps people usually don't need at startup. Shown as a hint, never acted on alone.
$known = @{
    'spotify' = 'Music'; 'discord' = 'Chat'; 'steam' = 'Games'; 'epicgameslauncher' = 'Games'; 'eadesktop' = 'Games';
    'origin' = 'Games'; 'battle.net' = 'Games'; 'ubisoftconnect' = 'Games'; 'teams' = 'Chat'; 'ms-teams' = 'Chat';
    'skype' = 'Chat'; 'zoom' = 'Meetings'; 'whatsapp' = 'Chat'; 'telegram' = 'Chat'; 'opera' = 'Browser';
    'operagx' = 'Browser'; 'browser_assistant' = 'Browser'; 'msedge' = 'Browser'; 'chrome' = 'Browser'; 'brave' = 'Browser';
    'ccleaner' = 'Utility'; 'utorrent' = 'Downloads'; 'qbittorrent' = 'Downloads'; 'idman' = 'Downloads';
    'adobe' = 'Updater'; 'acrotray' = 'Updater'; 'cortana' = 'Assistant'; 'lghub' = 'Accessories'; 'icue' = 'Accessories'
}

function Reg-Root([string]$hive) {
    if ($hive -eq 'HKCU') { return [Microsoft.Win32.Registry]::CurrentUser }
    return [Microsoft.Win32.RegistryKey]::OpenBaseKey('LocalMachine', 'Registry64')
}

# Task Manager's convention: first byte even (2, 6) = on, odd (3, 7) = off.
function Is-Enabled([string]$hive, [string]$approved, [string]$name) {
    $k = (Reg-Root $hive).OpenSubKey("$approvedBase\$approved")
    if (-not $k) { return $true }
    try {
        $v = $k.GetValue($name)
        if ($v -is [byte[]] -and $v.Length -gt 0) { return ($v[0] % 2) -eq 0 }
        return $true
    } finally { $k.Close() }
}

function Exe-From([string]$command) {
    if (-not $command) { return $null }
    $c = [Environment]::ExpandEnvironmentVariables($command.Trim())
    if ($c.StartsWith('"')) {
        $end = $c.IndexOf('"', 1)
        if ($end -gt 1) { return $c.Substring(1, $end - 1) }
    }
    $m = [regex]::Match($c, '^(.+?\.(exe|cmd|bat|com|lnk))(\s|$)', 'IgnoreCase')
    if ($m.Success) { return $m.Groups[1].Value }
    return ($c -split '\s+')[0]
}

function Icon-Data([string]$path) {
    try {
        if (-not $path -or -not (Test-Path -LiteralPath $path -PathType Leaf)) { return $null }
        $icon = [System.Drawing.Icon]::ExtractAssociatedIcon($path)
        $bmp = $icon.ToBitmap()
        $ms = New-Object IO.MemoryStream
        $bmp.Save($ms, [System.Drawing.Imaging.ImageFormat]::Png)
        return 'data:image/png;base64,' + [Convert]::ToBase64String($ms.ToArray())
    } catch { return $null }
}

function New-StartupItem($scope, $hive, $approved, $name, $command, $path) {
    $publisher = $null; $description = $null
    try {
        if ($path -and (Test-Path -LiteralPath $path -PathType Leaf)) {
            $vi = (Get-Item -LiteralPath $path).VersionInfo
            $publisher = $vi.CompanyName; $description = $vi.FileDescription
        }
    } catch { }
    $stem = if ($path) { [IO.Path]::GetFileNameWithoutExtension($path).ToLowerInvariant() } else { '' }
    $hint = $null
    foreach ($k in $known.Keys) { if ($stem -like "*$k*" -or $name.ToLowerInvariant() -like "*$k*") { $hint = $known[$k]; break } }
    return [ordered]@{
        id = "$hive|$approved|$name"
        name = $(if ($description -and $description.Length -lt 60) { $description } else { $name })
        entry = $name
        command = $command
        path = $path
        exists = [bool]($path -and (Test-Path -LiteralPath $path))
        publisher = $publisher
        enabled = Is-Enabled $hive $approved $name
        admin = ($hive -eq 'HKLM')
        scope = $scope
        icon = Icon-Data $path
        hint = $hint
    }
}

function List-Items {
    $items = @()
    foreach ($s in $sources) {
        $k = (Reg-Root $s.hive).OpenSubKey($s.key)
        if (-not $k) { continue }
        try {
            foreach ($name in $k.GetValueNames()) {
                if (-not $name) { continue }
                $cmd = [string]$k.GetValue($name)
                $items += New-StartupItem $s.scope $s.hive $s.approved $name $cmd (Exe-From $cmd)
            }
        } finally { $k.Close() }
    }
    foreach ($f in $folders) {
        if (-not $f.path -or -not (Test-Path -LiteralPath $f.path)) { continue }
        Get-ChildItem -LiteralPath $f.path -File -ErrorAction SilentlyContinue | Where-Object { $_.Name -ne 'desktop.ini' } | ForEach-Object {
            $target = $_.FullName
            if ($_.Extension -eq '.lnk') {
                try { $target = (New-Object -ComObject WScript.Shell).CreateShortcut($_.FullName).TargetPath } catch { }
            }
            $items += New-StartupItem $f.scope $f.hive $f.approved $_.Name $_.FullName $target
        }
    }
    return $items
}

if ($a.mode -eq 'list') {
    Send @(List-Items)
    return
}

if ($a.mode -eq 'set') {
    $parts = ([string]$a.id) -split '\|', 3
    if ($parts.Count -ne 3 -or @('HKCU', 'HKLM') -notcontains $parts[0] -or @('Run', 'Run32', 'StartupFolder') -notcontains $parts[1]) {
        Fail 'Unknown startup item'
    }
    $hive, $approved, $name = $parts
    # Only switch items that really are in the startup list.
    $match = @(List-Items | Where-Object { $_.id -eq $a.id })
    if ($match.Count -eq 0) { Fail 'That app is no longer in the startup list' }
    if ($hive -eq 'HKLM' -and -not (Test-Admin)) { Fail 'needs-admin' }
    $root = Reg-Root $hive
    $k = $root.CreateSubKey("$approvedBase\$approved")
    try {
        $bytes = New-Object byte[] 12
        if ([bool]$a.enabled) {
            $bytes[0] = 2
        } else {
            $bytes[0] = 3
            [BitConverter]::GetBytes([DateTime]::UtcNow.ToFileTimeUtc()).CopyTo($bytes, 4)
        }
        $k.SetValue($name, $bytes, [Microsoft.Win32.RegistryValueKind]::Binary)
    } finally { $k.Close() }
    Send ([ordered]@{ id = $a.id; enabled = (Is-Enabled $hive $approved $name) })
    return
}

Fail 'Unknown mode'
