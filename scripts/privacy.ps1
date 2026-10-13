# Which apps used the camera, microphone and location, and which are using them now.
# Read-only, from Windows' own record (Settings > Privacy & security shows the same).
#   { mode: 'report' } -> { caps: [ { id, on, user, device, desktopApps, apps: [ app ] } ] }
#   app = { name, ids, packaged, inUse, lastStart, lastStop }   (times in UTC, ISO)
param([string]$Payload = '', [string]$OutFile = '')
. "$PSScriptRoot\_lib.ps1"
trap { Fail $_.Exception.Message }
$a = Get-Args
if ($a.mode -ne 'report') { Fail 'Unknown mode' }

$store = 'Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore'

function Read-Key($Hive, [string]$Path) {
    try { return $Hive.OpenSubKey($Path, $false) } catch { return $null }
}
function Time($v) {
    if ($null -eq $v) { return [long]0 }
    return [long]$v
}
function Iso([long]$ft) { if ($ft -le 0) { return $null }; return [DateTime]::FromFileTimeUtc($ft).ToString('o') }

# Friendly names: Store apps from the Start menu list, desktop apps from their file's description.
$startNames = @{}
try {
    foreach ($s in @(Get-StartApps)) {
        $id = [string]$s.AppID
        if ($id -match '^([^!]+)!') { if (-not $startNames.ContainsKey($Matches[1])) { $startNames[$Matches[1]] = [string]$s.Name } }
    }
} catch { }

function Packaged-Name([string]$Family) {
    if ($startNames.ContainsKey($Family)) { return $startNames[$Family] }
    $n = ($Family -split '_')[0]
    if ($n -match '\.([^.]+)$') { $n = $Matches[1] }
    return ($n -creplace '([a-z])([A-Z])', '$1 $2')
}

function Desktop-Name([string]$Key) {
    $path = $Key.Replace('#', '\')
    try {
        if (Test-Path -LiteralPath $path -PathType Leaf) {
            $vi = [Diagnostics.FileVersionInfo]::GetVersionInfo($path)
            foreach ($n in @($vi.FileDescription, $vi.ProductName)) {
                if ($n -and $n.Trim().Length -gt 1) { return $n.Trim() }
            }
        }
    } catch { }
    return [IO.Path]::GetFileNameWithoutExtension($path)
}

$hkcu = [Microsoft.Win32.Registry]::CurrentUser
$hklm = [Microsoft.Win32.RegistryKey]::OpenBaseKey('LocalMachine', 'Registry64')
$caps = @()
foreach ($cap in @('webcam', 'microphone', 'location')) {
    $user = $null; $device = $null; $desktop = $null
    $k = Read-Key $hkcu "$store\$cap"
    if ($k) { $user = [string]$k.GetValue('Value') }
    $m = Read-Key $hklm "$store\$cap"
    if ($m) { $device = [string]$m.GetValue('Value'); $m.Close() }
    $raw = @()
    if ($k) {
        foreach ($sub in $k.GetSubKeyNames()) {
            if ($sub -eq 'NonPackaged') { continue }
            $s = $k.OpenSubKey($sub)
            if ($s) { $raw += @{ id = $sub; packaged = $true; start = (Time $s.GetValue('LastUsedTimeStart')); stop = (Time $s.GetValue('LastUsedTimeStop')) }; $s.Close() }
        }
        $np = $k.OpenSubKey('NonPackaged')
        if ($np) {
            $desktop = [string]$np.GetValue('Value')
            foreach ($sub in $np.GetSubKeyNames()) {
                $s = $np.OpenSubKey($sub)
                if ($s) { $raw += @{ id = $sub; packaged = $false; start = (Time $s.GetValue('LastUsedTimeStart')); stop = (Time $s.GetValue('LastUsedTimeStop')) }; $s.Close() }
            }
            $np.Close()
        }
        $k.Close()
    }
    # Apps that have used it at least once. In use now: started, not stopped since.
    $byName = [ordered]@{}
    foreach ($r in $raw) {
        if ($r.start -le 0) { continue }
        $inUse = ($r.stop -eq 0) -or ($r.start -gt $r.stop)
        $name = $(if ($r.packaged) { Packaged-Name $r.id } else { Desktop-Name $r.id })
        $key = $name.ToLowerInvariant()
        if (-not $byName.Contains($key)) {
            $byName[$key] = @{ name = $name; ids = @(); packaged = $r.packaged; inUse = $false; start = [long]0; stop = [long]0 }
        }
        $e = $byName[$key]
        $e.ids += $r.id
        if ($inUse) { $e.inUse = $true }
        if ($r.start -gt $e.start) { $e.start = $r.start }
        if ($r.stop -gt $e.stop) { $e.stop = $r.stop }
    }
    $apps = @($byName.Values | Sort-Object @{ Expression = { $_.inUse }; Descending = $true }, @{ Expression = { [Math]::Max($_.start, $_.stop) }; Descending = $true } | ForEach-Object {
        [ordered]@{ name = $_.name; ids = @($_.ids); packaged = $_.packaged; inUse = $_.inUse; lastStart = (Iso $_.start); lastStop = $(if ($_.inUse) { $null } else { Iso $_.stop }) }
    })
    $caps += [ordered]@{
        id = $cap
        on = ($user -ne 'Deny') -and ($device -ne 'Deny')
        user = $user; device = $device
        desktopApps = ($desktop -ne 'Deny')
        apps = $apps
    }
}
Send ([ordered]@{ caps = $caps })
