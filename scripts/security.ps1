# Security check, read-only and without admin rights.
#   { mode: 'report' } -> { items: [ { id, state, ...facts, url } ], isAdmin }
# state: 'ok' (fine), 'warn' (worth a look), 'info' (not available on this PC, nothing to do),
#        'unknown' (Windows didn't let us read it; never guessed).
param([string]$Payload = '', [string]$OutFile = '')
. "$PSScriptRoot\_lib.ps1"
trap { Fail $_.Exception.Message }
$a = Get-Args
if ($a.mode -ne 'report') { Fail 'Unknown mode' }

$admin = Test-Admin
$now = [DateTime]::UtcNow
$items = @()

function Iso($d) { if ($null -eq $d) { return $null }; return ([DateTime]$d).ToUniversalTime().ToString('o') }

# Other security products registered with Windows Security (Security Center).
# productState: bits 12-15 = 1 means on.
function Center([string]$Class) {
    $list = @()
    try {
        foreach ($p in @(Get-CimInstance -Namespace root/SecurityCenter2 -ClassName $Class -ErrorAction Stop)) {
            $list += [ordered]@{ name = [string]$p.displayName; on = ((([int]$p.productState) -shr 12) -band 0xF) -eq 1 }
        }
    } catch { }
    return ,$list
}

# ---------- Antivirus ----------
$av = [ordered]@{ id = 'antivirus'; state = 'unknown'; protected = $null; realtime = $null; defsUpdated = $null; defsAgeDays = $null; others = @(); url = 'windowsdefender://threat' }
$products = Center 'AntiVirusProduct'
$av.others = @($products | Where-Object { $_.name -notmatch 'Windows Defender|Microsoft Defender' -and $_.on } | ForEach-Object { $_.name })
try {
    $mp = Get-MpComputerStatus -ErrorAction Stop
    $av.realtime = [bool]($mp.AMServiceEnabled -and $mp.RealTimeProtectionEnabled)
    if ($mp.AntivirusSignatureLastUpdated -and ([DateTime]$mp.AntivirusSignatureLastUpdated).Year -gt 2000) {
        $updated = ([DateTime]$mp.AntivirusSignatureLastUpdated).ToUniversalTime()
        $av.defsUpdated = $updated.ToString('o')
        $av.defsAgeDays = [int][Math]::Floor(($now - $updated).TotalDays)
    }
} catch { }
if ($av.realtime -eq $true) {
    $av.protected = $true
    $av.state = $(if ($null -ne $av.defsAgeDays -and $av.defsAgeDays -gt 7) { 'warn' } else { 'ok' })
} elseif ($av.others.Count -gt 0) {
    $av.protected = $true; $av.state = 'ok'
} elseif ($av.realtime -eq $false) {
    $av.protected = $false; $av.state = 'warn'
}
$items += $av

# ---------- Firewall ----------
$fw = [ordered]@{ id = 'firewall'; state = 'unknown'; profiles = @(); others = @(); url = 'windowsdefender://network' }
$fw.others = @(Center 'FirewallProduct' | Where-Object { $_.on } | ForEach-Object { $_.name })
try {
    # ActiveStore is what's in force, including group policy.
    foreach ($p in @(Get-NetFirewallProfile -PolicyStore ActiveStore -ErrorAction Stop | Sort-Object Name)) {
        $fw.profiles += [ordered]@{ name = [string]$p.Name; on = ([string]$p.Enabled -eq 'True') }
    }
} catch { }
if ($fw.profiles.Count -gt 0) {
    $off = @($fw.profiles | Where-Object { -not $_.on }).Count
    $fw.state = $(if ($off -eq 0 -or $fw.others.Count -gt 0) { 'ok' } else { 'warn' })
}
$items += $fw

# ---------- Windows Update ----------
$wu = [ordered]@{ id = 'updates'; state = 'unknown'; lastInstall = $null; lastSearch = $null; restartPending = $null; url = 'ms-settings:windowsupdate' }
try {
    $r = (New-Object -ComObject Microsoft.Update.AutoUpdate).Results
    # Windows Update reports these in UTC.
    if ($r.LastInstallationSuccessDate -and ([DateTime]$r.LastInstallationSuccessDate).Year -gt 2000) {
        $wu.lastInstall = [DateTime]::SpecifyKind([DateTime]$r.LastInstallationSuccessDate, 'Utc').ToString('o')
    }
    if ($r.LastSearchSuccessDate -and ([DateTime]$r.LastSearchSuccessDate).Year -gt 2000) {
        $wu.lastSearch = [DateTime]::SpecifyKind([DateTime]$r.LastSearchSuccessDate, 'Utc').ToString('o')
    }
} catch { }
try { $wu.restartPending = [bool](New-Object -ComObject Microsoft.Update.SystemInfo).RebootRequired } catch { }
if ($null -eq $wu.restartPending) {
    $wu.restartPending = (Test-Path 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired') -or
        (Test-Path 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootPending')
}
if ($wu.lastInstall) {
    $age = ($now - [DateTime]::Parse($wu.lastInstall).ToUniversalTime()).TotalDays
    $wu.state = $(if ($wu.restartPending -or $age -gt 45) { 'warn' } else { 'ok' })
} elseif ($wu.restartPending) { $wu.state = 'warn' }
$items += $wu

# ---------- Drive encryption (C:) ----------
# Explorer's own value, readable without admin rights:
# 1 on, 2 off, 3 encrypting, 4 decrypting, 5 suspended, 6 on (locked), 8 waiting for activation; empty/0 = not available.
$enc = [ordered]@{ id = 'encryption'; state = 'unknown'; status = $null; code = $null; url = 'ms-settings:deviceencryption' }
try {
    $drive = $env:SystemDrive
    $v = (New-Object -ComObject Shell.Application).NameSpace("$drive\").Self.ExtendedProperty('System.Volume.BitLockerProtection')
    $code = $(if ($null -eq $v -or "$v" -eq '') { 0 } else { [int]$v })
    $enc.code = $code
    $map = @{ 0 = 'none'; 1 = 'on'; 2 = 'off'; 3 = 'encrypting'; 4 = 'decrypting'; 5 = 'suspended'; 6 = 'on'; 8 = 'waiting' }
    $enc.status = $(if ($map.ContainsKey($code)) { $map[$code] } else { 'unknown' })
    $enc.state = switch ($enc.status) { 'on' { 'ok' } 'encrypting' { 'ok' } 'none' { 'info' } 'unknown' { 'unknown' } default { 'warn' } }
} catch { }
$items += $enc

# ---------- Secure Boot ----------
$sb = [ordered]@{ id = 'secureboot'; state = 'unknown'; on = $null; supported = $null; url = 'windowsdefender://devicesecurity' }
$val = $null
try { $val = (Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\SecureBoot\State' -ErrorAction Stop).UEFISecureBootEnabled } catch { }
if ($null -ne $val) {
    $sb.supported = $true; $sb.on = ([int]$val -eq 1)
} elseif ($admin) {
    try { $sb.on = [bool](Confirm-SecureBootUEFI -ErrorAction Stop); $sb.supported = $true }
    catch { if ($_.Exception.Message -match 'not supported|non pris en charge') { $sb.supported = $false } }
}
if ($sb.supported -eq $false) { $sb.state = 'info' }
elseif ($null -ne $sb.on) { $sb.state = $(if ($sb.on) { 'ok' } else { 'warn' }) }
$items += $sb

# ---------- TPM ----------
# The TPM shows up as a security device; ACPI\MSFT0101 is a TPM 2.0. Get-Tpm needs admin rights.
$tpm = [ordered]@{ id = 'tpm'; state = 'unknown'; present = $null; version = $null; url = 'windowsdefender://devicesecurity' }
try {
    $devs = @(Get-CimInstance Win32_PnPEntity -Filter "PNPClass='SecurityDevices'" -ErrorAction Stop |
        Where-Object { $_.PNPDeviceID -match 'MSFT0101|PNP0C31|TPM' -or $_.Name -match 'TPM|Trusted Platform|plateforme s' })
    $ok = @($devs | Where-Object { $_.Status -eq 'OK' })
    $tpm.present = $ok.Count -gt 0
    if ($tpm.present) {
        $d = $ok[0]
        if ($d.Name -match '(\d\.\d)') { $tpm.version = $Matches[1] }
        elseif ($d.PNPDeviceID -match 'MSFT0101') { $tpm.version = '2.0' }
    }
} catch { }
if ($admin) {
    try {
        $w = Get-CimInstance -Namespace root/cimv2/security/microsofttpm -ClassName Win32_Tpm -ErrorAction Stop
        if ($w) { $tpm.present = $true; $tpm.version = ([string]$w.SpecVersion).Split(',')[0].Trim() }
    } catch { }
}
if ($null -ne $tpm.present) {
    $tpm.state = $(if ($tpm.present -and $tpm.version -and [double]::Parse($tpm.version, [Globalization.CultureInfo]::InvariantCulture) -ge 2) { 'ok' } else { 'warn' })
}
$items += $tpm

# ---------- SmartScreen (check apps and files) ----------
$ss = [ordered]@{ id = 'smartscreen'; state = 'unknown'; on = $null; source = $null; url = 'windowsdefender://appbrowser' }
try {
    $pol = (Get-ItemProperty 'HKLM:\SOFTWARE\Policies\Microsoft\Windows\System' -ErrorAction SilentlyContinue).EnableSmartScreen
    $exp = (Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer' -ErrorAction SilentlyContinue).SmartScreenEnabled
    if ($null -ne $pol) { $ss.on = ([int]$pol -ne 0); $ss.source = 'policy' }
    elseif ($exp) { $ss.on = ([string]$exp -ne 'Off'); $ss.source = 'setting' }
    else { $ss.on = $true; $ss.source = 'default' }   # not set means Windows' default: on
    $ss.state = $(if ($ss.on) { 'ok' } else { 'warn' })
} catch { }
$items += $ss

# ---------- User Account Control ----------
$uac = [ordered]@{ id = 'uac'; state = 'unknown'; on = $null; neverNotify = $null; url = $null }
try {
    $k = Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System' -ErrorAction Stop
    $uac.on = ($null -eq $k.EnableLUA) -or ([int]$k.EnableLUA -ne 0)
    $uac.neverNotify = ($null -ne $k.ConsentPromptBehaviorAdmin) -and ([int]$k.ConsentPromptBehaviorAdmin -eq 0)
    $uac.state = $(if ($uac.on -and -not $uac.neverNotify) { 'ok' } else { 'warn' })
} catch { }
$items += $uac

Send ([ordered]@{ items = $items; isAdmin = $admin })
