# Battery health and "why did my battery die overnight?".
#   { mode: 'report' }                       -> battery health, recent sleeps on battery, what woke the PC, wake-armed devices
#   { mode: 'wake', device, allow: bool }    -> { device, allowed }   (admin)
param([string]$Payload = '', [string]$OutFile = '')
. "$PSScriptRoot\_lib.ps1"
trap { Fail $_.Exception.Message }
$a = Get-Args

function Armed-Devices {
    $lines = Invoke-Native { powercfg /devicequery wake_armed 2>$null }
    return @($lines | ForEach-Object { $_.Trim() } | Where-Object { $_ -and $_ -notmatch '^(NONE|AUCUN|KEINE|NINGUNO)$' })
}

if ($a.mode -eq 'wake') {
    $device = [string]$a.device
    if ($a.allow) {
        $programmable = @(Invoke-Native { powercfg /devicequery wake_programmable 2>$null } | ForEach-Object { $_.Trim() })
        if ($programmable -notcontains $device) { Fail 'Unknown device' }
        if (-not (Test-Admin)) { Fail 'needs-admin' }
        powercfg /deviceenablewake "$device" | Out-Null
    } else {
        if ((Armed-Devices) -notcontains $device) { Fail 'Unknown device' }
        if (-not (Test-Admin)) { Fail 'needs-admin' }
        powercfg /devicedisablewake "$device" | Out-Null
    }
    Send ([ordered]@{ device = $device; allowed = ((Armed-Devices) -contains $device) })
    return
}

if ($a.mode -ne 'report') { Fail 'Unknown mode' }

$out = [ordered]@{ hasBattery = $false }
$wmi = @(Get-CimInstance Win32_Battery -ErrorAction SilentlyContinue)
if ($wmi.Count -gt 0) {
    $out.hasBattery = $true
    $out.percent = [int]$wmi[0].EstimatedChargeRemaining
    # BatteryStatus 2 = on AC power; 6-9 = charging
    $out.plugged = @(2, 6, 7, 8, 9) -contains [int]$wmi[0].BatteryStatus
    $run = [int]$wmi[0].EstimatedRunTime
    $out.minutesLeft = $(if ($run -gt 0 -and $run -lt 71582788) { $run } else { $null })

    $xmlPath = Join-Path $env:TEMP ("hibclean-battery-" + [Guid]::NewGuid().ToString('N') + '.xml')
    try {
        powercfg /batteryreport /xml /output "$xmlPath" | Out-Null
        [xml]$report = Get-Content -LiteralPath $xmlPath -Raw -Encoding UTF8
    } finally {
        Remove-Item -LiteralPath $xmlPath -ErrorAction SilentlyContinue
    }
    $batteries = @($report.BatteryReport.Batteries.Battery)
    $design = 0; $full = 0; $cycles = 0
    foreach ($b in $batteries) { $design += [long]$b.DesignCapacity; $full += [long]$b.FullChargeCapacity; $cycles = [Math]::Max($cycles, [int]$b.CycleCount) }
    $out.design = $design
    $out.full = $full
    $out.health = $(if ($design -gt 0) { [Math]::Round(100.0 * $full / $design, 1) } else { $null })
    $out.cycles = $(if ($cycles -gt 0) { $cycles } else { $null })
    $out.chemistry = [string]$batteries[0].Chemistry
    $out.batteries = $batteries.Count

    # Sleep periods on battery in the last 14 days, with how much charge each one cost.
    $since = [DateTime]::UtcNow.AddDays(-14)
    $sleeps = @()
    foreach ($e in @($report.BatteryReport.RecentUsage.UsageEntry)) {
        if (@('Suspend', 'ConnectedStandby') -notcontains $e.EntryType) { continue }
        if ([int]$e.Ac -ne 0) { continue }
        $start = [DateTime]::Parse($e.Timestamp).ToUniversalTime()
        if ($start -lt $since) { continue }
        $hours = [double]$e.Duration / 1e7 / 3600
        if ($hours -lt 0.5 -or $hours -gt 240) { continue }
        $cap = [double]$e.FullChargeCapacity
        if ($cap -le 0) { $cap = $full }
        $drain = [double]$e.Discharge
        if ($drain -lt 0) { $drain = 0 }
        $pct = $(if ($cap -gt 0) { 100.0 * $drain / $cap } else { 0 })
        $sleeps += [ordered]@{
            start = $start.ToString('o')
            hours = [Math]::Round($hours, 1)
            drainPercent = [Math]::Round($pct, 1)
            perHour = [Math]::Round($pct / $hours, 2)
            kind = $(if ($e.EntryType -eq 'Suspend') { 'sleep' } else { 'modern-standby' })
        }
    }
    $out.sleeps = @($sleeps | Sort-Object { $_.start } -Descending | Select-Object -First 10)
}

# What woke the PC (last 14 days). Field names are the same in every Windows language.
$wakes = @()
try {
    $events = @(Get-WinEvent -FilterHashtable @{ LogName = 'System'; ProviderName = 'Microsoft-Windows-Power-Troubleshooter'; Id = 1; StartTime = (Get-Date).AddDays(-14) } -MaxEvents 30 -ErrorAction Stop)
    foreach ($ev in $events) {
        $d = @{}
        foreach ($n in ([xml]$ev.ToXml()).Event.EventData.Data) { $d[$n.Name] = $n.'#text' }
        $source = $d['WakeSourceText']
        if (-not $source -and $d['WakeTimerOwner']) { $source = $d['WakeTimerOwner'] }
        $slept = $null
        try { $slept = [Math]::Round(([DateTime]::Parse($d['WakeTime']) - [DateTime]::Parse($d['SleepTime'])).TotalMinutes) } catch { }
        $wakes += [ordered]@{
            time = $ev.TimeCreated.ToUniversalTime().ToString('o')
            sleptMinutes = $slept
            source = $source
            type = [int]$d['WakeSourceType']
            timer = [bool]$d['WakeTimerOwner']
        }
    }
} catch { }
$out.wakes = @($wakes)
$out.armed = @(Armed-Devices)
$out.isAdmin = Test-Admin
Send $out
