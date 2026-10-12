# Quick facts for the dashboard: disk space, memory, uptime and the busiest apps.
#   {} -> { model, os, drive: { total, free }, memory: { total, free }, uptimeHours, top: [...] }
param([string]$Payload = '', [string]$OutFile = '')
. "$PSScriptRoot\_lib.ps1"
trap { Fail $_.Exception.Message }

$cs = Get-CimInstance Win32_ComputerSystem
$os = Get-CimInstance Win32_OperatingSystem
$drive = Get-CimInstance Win32_LogicalDisk -Filter "DeviceID='$($env:SystemDrive)'"
$cv = Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion'

# Busiest apps by memory, grouped by program (Chrome's many processes count as one).
$top = Get-Process | Where-Object { $_.Id -ne 0 -and $_.ProcessName -ne 'Idle' } |
    Group-Object ProcessName | ForEach-Object {
        $mem = ($_.Group | Measure-Object WorkingSet64 -Sum).Sum
        $first = $_.Group | Where-Object { $_.MainWindowTitle } | Select-Object -First 1
        $desc = $null
        try { $desc = ($_.Group | Select-Object -First 1).MainModule.FileVersionInfo.FileDescription } catch { }
        [ordered]@{ name = $(if ($desc) { $desc } else { $_.Name }); process = $_.Name; memory = [long]$mem; count = $_.Count; window = [bool]$first }
    } | Sort-Object { $_.memory } -Descending | Select-Object -First 6

Send ([ordered]@{
    manufacturer = $cs.Manufacturer
    model = $cs.Model
    os = $os.Caption
    osVersion = [string]$cv.DisplayVersion
    build = "$($cv.CurrentBuild).$($cv.UBR)"
    drive = [ordered]@{ letter = $env:SystemDrive; total = [long]$drive.Size; free = [long]$drive.FreeSpace }
    memory = [ordered]@{ total = [long]$cs.TotalPhysicalMemory; free = [long]$os.FreePhysicalMemory * 1024 }
    uptimeHours = [Math]::Round(((Get-Date) - $os.LastBootUpTime).TotalHours, 1)
    top = @($top)
})
