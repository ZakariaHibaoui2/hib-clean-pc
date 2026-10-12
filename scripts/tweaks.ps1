# Windows clean-up: switches off Windows 11's ads, suggestions and pushed features.
#   { mode: 'list' }                 -> [{ id, applied, admin, restart, undo }]
#   { mode: 'apply', ids: [...] }    -> [{ id, ok, error? }]
#   { mode: 'undo',  ids: [...] }    -> [{ id, ok, error? }]
#   { mode: 'restart-explorer' }     -> true
#
# Every value is backed up before it changes (its old data, or that it didn't
# exist), and Undo puts exactly that back. Only the values listed here are touched.
param([string]$Payload = '', [string]$OutFile = '')
. "$PSScriptRoot\_lib.ps1"
trap { Fail $_.Exception.Message }
$a = Get-Args

$adv = 'Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced'
$cdm = 'Software\Microsoft\Windows\CurrentVersion\ContentDeliveryManager'

function V($hive, $path, $name, $value) { @{ hive = $hive; path = $path; name = $name; value = $value } }

$tweaks = @(
    @{ id = 'start-ads'; restart = 'explorer'; values = @(
        (V 'HKCU' $adv 'Start_IrisRecommendations' 0),
        (V 'HKCU' $adv 'Start_AccountNotifications' 0)) }
    @{ id = 'suggested-apps'; restart = $null; values = @(
        (V 'HKCU' $cdm 'SilentInstalledAppsEnabled' 0),
        (V 'HKCU' $cdm 'PreInstalledAppsEnabled' 0),
        (V 'HKCU' $cdm 'OemPreInstalledAppsEnabled' 0),
        (V 'HKCU' $cdm 'SystemPaneSuggestionsEnabled' 0),
        (V 'HKCU' $cdm 'SubscribedContent-338388Enabled' 0)) }
    @{ id = 'tips'; restart = $null; values = @(
        (V 'HKCU' $cdm 'SoftLandingEnabled' 0),
        (V 'HKCU' $cdm 'SubscribedContent-338389Enabled' 0),
        (V 'HKCU' $cdm 'SubscribedContent-310093Enabled' 0),
        (V 'HKCU' 'Software\Microsoft\Windows\CurrentVersion\UserProfileEngagement' 'ScoobeSystemSettingEnabled' 0)) }
    @{ id = 'settings-ads'; restart = $null; values = @(
        (V 'HKCU' $cdm 'SubscribedContent-338393Enabled' 0),
        (V 'HKCU' $cdm 'SubscribedContent-353694Enabled' 0),
        (V 'HKCU' $cdm 'SubscribedContent-353696Enabled' 0)) }
    @{ id = 'lockscreen-ads'; restart = $null; values = @(
        (V 'HKCU' $cdm 'RotatingLockScreenOverlayEnabled' 0),
        (V 'HKCU' $cdm 'SubscribedContent-338387Enabled' 0)) }
    @{ id = 'explorer-ads'; restart = 'explorer'; values = @(
        (V 'HKCU' $adv 'ShowSyncProviderNotifications' 0)) }
    @{ id = 'ad-id'; restart = $null; values = @(
        (V 'HKCU' 'Software\Microsoft\Windows\CurrentVersion\AdvertisingInfo' 'Enabled' 0),
        (V 'HKCU' 'Software\Microsoft\Windows\CurrentVersion\Privacy' 'TailoredExperiencesWithDiagnosticDataEnabled' 0)) }
    @{ id = 'web-search'; restart = 'explorer'; values = @(
        (V 'HKCU' 'Software\Policies\Microsoft\Windows\Explorer' 'DisableSearchBoxSuggestions' 1)) }
    @{ id = 'copilot'; restart = 'explorer'; values = @(
        (V 'HKCU' $adv 'ShowCopilotButton' 0),
        (V 'HKCU' 'Software\Policies\Microsoft\Windows\WindowsCopilot' 'TurnOffWindowsCopilot' 1)) }
    @{ id = 'feedback'; restart = $null; values = @(
        (V 'HKCU' 'Software\Microsoft\Siuf\Rules' 'NumberOfSIUFInPeriod' 0)) }
    @{ id = 'widgets'; restart = 'explorer'; values = @(
        (V 'HKLM' 'SOFTWARE\Policies\Microsoft\Dsh' 'AllowNewsAndInterests' 0)) }
    @{ id = 'telemetry'; restart = $null; values = @(
        (V 'HKLM' 'SOFTWARE\Policies\Microsoft\Windows\DataCollection' 'AllowTelemetry' 0)) }
)

# Tests point HKCU changes at a throwaway key so this PC's settings stay as they are.
$testRoot = $env:HIB_TEST_REG_ROOT
if ($testRoot -and -not $testRoot.StartsWith('Software\HibCleanPCTest')) { Fail 'Bad test root' }

function Open-Key([string]$hive, [string]$path, [bool]$write) {
    if ($testRoot) { $hive = 'HKCU'; $path = "$testRoot\$path" }
    $base = if ($hive -eq 'HKCU') { [Microsoft.Win32.Registry]::CurrentUser }
            else { [Microsoft.Win32.RegistryKey]::OpenBaseKey('LocalMachine', 'Registry64') }
    if ($write) { return $base.CreateSubKey($path) }
    return $base.OpenSubKey($path)
}

function Read-Value($v) {
    $k = Open-Key $v.hive $v.path $false
    if (-not $k) { return @{ existed = $false } }
    try {
        if ($k.GetValueNames() -notcontains $v.name) { return @{ existed = $false } }
        return @{ existed = $true; kind = [string]$k.GetValueKind($v.name); value = $k.GetValue($v.name, $null, 'DoNotExpandEnvironmentNames') }
    } finally { $k.Close() }
}

function Is-Applied($t) {
    foreach ($v in $t.values) {
        $cur = Read-Value $v
        if (-not $cur.existed -or $cur.kind -ne 'DWord' -or [int]$cur.value -ne $v.value) { return $false }
    }
    return $true
}

function Needs-Admin($t) { return [bool]($t.values | Where-Object { $_.hive -eq 'HKLM' }) -and -not $testRoot }

$stateName = if ($testRoot) { 'tweaks-backup-test' } else { 'tweaks-backup' }
$backup = Read-State $stateName
$store = @{}
if ($backup) { foreach ($p in $backup.PSObject.Properties) { $store[$p.Name] = @($p.Value) } }

function Save-Backup { Write-State $stateName $store }

$wanted = @($a.ids)
function Selected { $tweaks | Where-Object { $wanted -contains $_.id } }

switch ($a.mode) {
    'list' {
        $out = foreach ($t in $tweaks) {
            [ordered]@{ id = $t.id; applied = (Is-Applied $t); admin = (Needs-Admin $t); restart = $t.restart; undo = $store.ContainsKey($t.id) }
        }
        Send @($out)
    }
    'apply' {
        $isAdmin = Test-Admin
        $out = foreach ($t in (Selected)) {
            if ((Needs-Admin $t) -and -not $isAdmin) { [ordered]@{ id = $t.id; ok = $false; error = 'needs-admin' }; continue }
            try {
                if (-not $store.ContainsKey($t.id)) {
                    $saved = foreach ($v in $t.values) {
                        $cur = Read-Value $v
                        [ordered]@{ hive = $v.hive; path = $v.path; name = $v.name; existed = $cur.existed; kind = $cur.kind; value = $cur.value }
                    }
                    $store[$t.id] = @($saved)
                    Save-Backup
                }
                foreach ($v in $t.values) {
                    $k = Open-Key $v.hive $v.path $true
                    try { $k.SetValue($v.name, [int]$v.value, [Microsoft.Win32.RegistryValueKind]::DWord) } finally { $k.Close() }
                }
                [ordered]@{ id = $t.id; ok = $true }
            } catch { [ordered]@{ id = $t.id; ok = $false; error = $_.Exception.Message } }
        }
        Send @($out)
    }
    'undo' {
        $isAdmin = Test-Admin
        $out = foreach ($t in (Selected)) {
            if (-not $store.ContainsKey($t.id)) { [ordered]@{ id = $t.id; ok = $false; error = 'nothing-to-undo' }; continue }
            if ((Needs-Admin $t) -and -not $isAdmin) { [ordered]@{ id = $t.id; ok = $false; error = 'needs-admin' }; continue }
            try {
                foreach ($s in $store[$t.id]) {
                    # Only restore values this tweak owns.
                    if (-not ($t.values | Where-Object { $_.hive -eq $s.hive -and $_.path -eq $s.path -and $_.name -eq $s.name })) { continue }
                    $k = Open-Key $s.hive $s.path $true
                    try {
                        if ($s.existed) {
                            $value = $s.value
                            if ($s.kind -eq 'DWord') { $value = [int]$value }
                            elseif ($s.kind -eq 'QWord') { $value = [long]$value }
                            $k.SetValue($s.name, $value, [Microsoft.Win32.RegistryValueKind]$s.kind)
                        } else {
                            $k.DeleteValue($s.name, $false)
                        }
                    } finally { $k.Close() }
                }
                $store.Remove($t.id)
                Save-Backup
                [ordered]@{ id = $t.id; ok = $true }
            } catch { [ordered]@{ id = $t.id; ok = $false; error = $_.Exception.Message } }
        }
        Send @($out)
    }
    'restart-explorer' {
        if ($testRoot) { Send $true; return }
        Get-Process explorer -ErrorAction SilentlyContinue | Stop-Process -Force
        Start-Sleep -Seconds 2
        if (-not (Get-Process explorer -ErrorAction SilentlyContinue)) { Start-Process explorer.exe }
        Send $true
    }
    default { Fail 'Unknown mode' }
}
