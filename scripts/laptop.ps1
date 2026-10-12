# Hardware facts for the used-laptop check and its PDF report.
#   {} -> { device, cpu, memory, gpus, disks, display, windows, bios, admin }
# With admin rights it also reads SSD wear and power-on hours.
param([string]$Payload = '', [string]$OutFile = '')
. "$PSScriptRoot\_lib.ps1"
trap { Fail $_.Exception.Message }

function Try-Get([scriptblock]$s) { try { & $s } catch { $null } }

$cs = Get-CimInstance Win32_ComputerSystem
$bios = Get-CimInstance Win32_BIOS
$prod = Try-Get { Get-CimInstance Win32_ComputerSystemProduct }
$cpu = @(Get-CimInstance Win32_Processor)[0]
$cv = Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion'
$os = Get-CimInstance Win32_OperatingSystem

$sticks = @(Get-CimInstance Win32_PhysicalMemory -ErrorAction SilentlyContinue)
$array = Try-Get { @(Get-CimInstance Win32_PhysicalMemoryArray)[0] }
$memory = [ordered]@{
    total = [long]$cs.TotalPhysicalMemory
    installed = [long](($sticks | Measure-Object Capacity -Sum).Sum)
    slots = $(if ($array) { [int]$array.MemoryDevices } else { $null })
    used = $sticks.Count
    maxBytes = $(if ($array -and $array.MaxCapacityEx) { [long]$array.MaxCapacityEx * 1024 } else { $null })
    speed = $(if ($sticks.Count) { [int]($sticks | Measure-Object Speed -Maximum).Maximum } else { $null })
    modules = @($sticks | ForEach-Object { [ordered]@{ size = [long]$_.Capacity; maker = ([string]$_.Manufacturer).Trim(); slot = $_.DeviceLocator } })
}

$admin = Test-Admin
$disks = foreach ($d in @(Get-PhysicalDisk -ErrorAction SilentlyContinue)) {
    $rel = $null
    if ($admin) { $rel = Try-Get { $d | Get-StorageReliabilityCounter -ErrorAction Stop } }
    [ordered]@{
        name = ([string]$d.FriendlyName).Trim()
        type = [string]$d.MediaType
        bus = [string]$d.BusType
        size = [long]$d.Size
        health = [string]$d.HealthStatus
        wear = $(if ($rel -and $null -ne $rel.Wear) { [int]$rel.Wear } else { $null })
        powerOnHours = $(if ($rel -and $null -ne $rel.PowerOnHours) { [long]$rel.PowerOnHours } else { $null })
        temperature = $(if ($rel -and $rel.Temperature) { [int]$rel.Temperature } else { $null })
        readErrors = $(if ($rel -and $null -ne $rel.ReadErrorsTotal) { [long]$rel.ReadErrorsTotal } else { $null })
    }
}

$gpus = @(Get-CimInstance Win32_VideoController -ErrorAction SilentlyContinue | ForEach-Object {
    [ordered]@{ name = $_.Name; driver = $_.DriverVersion; width = $_.CurrentHorizontalResolution; height = $_.CurrentVerticalResolution; hz = $_.CurrentRefreshRate }
})

# Built-in screen size from the monitor's own data (centimetres).
$screen = Try-Get {
    $m = @(Get-CimInstance -Namespace root/wmi -ClassName WmiMonitorBasicDisplayParams -ErrorAction Stop | Where-Object { $_.Active })[0]
    if ($m -and $m.MaxHorizontalImageSize -gt 0) {
        $inch = [Math]::Sqrt([Math]::Pow($m.MaxHorizontalImageSize, 2) + [Math]::Pow($m.MaxVerticalImageSize, 2)) / 2.54
        [Math]::Round($inch, 1)
    }
}

$activation = Try-Get {
    $p = @(Get-CimInstance SoftwareLicensingProduct -Filter "ApplicationID='55c92734-d682-4d71-983e-d6ec3f16059f' AND PartialProductKey IS NOT NULL" -ErrorAction Stop)
    if ($p.Count) { [int]$p[0].LicenseStatus -eq 1 } else { $false }
}

Send ([ordered]@{
    device = [ordered]@{ manufacturer = $cs.Manufacturer; model = $cs.Model; family = $cs.SystemFamily
                         serial = $(if ($bios.SerialNumber -and $bios.SerialNumber -notmatch 'O\.E\.M|Default|To be filled') { ([string]$bios.SerialNumber).Trim() } else { $null })
                         sku = $(if ($prod) { $prod.SKUNumber } else { $null }) }
    cpu = [ordered]@{ name = ([string]$cpu.Name).Trim(); cores = [int]$cpu.NumberOfCores; threads = [int]$cpu.NumberOfLogicalProcessors; mhz = [int]$cpu.MaxClockSpeed }
    memory = $memory
    gpus = $gpus
    disks = @($disks)
    display = [ordered]@{ inches = $screen }
    windows = [ordered]@{ name = $os.Caption; version = [string]$cv.DisplayVersion; build = "$($cv.CurrentBuild).$($cv.UBR)"
                          activated = $activation; installed = $(if ($os.InstallDate) { $os.InstallDate.ToString('yyyy-MM-dd') } else { $null }) }
    bios = [ordered]@{ version = [string]$bios.SMBIOSBIOSVersion; date = $(if ($bios.ReleaseDate) { $bios.ReleaseDate.ToString('yyyy-MM-dd') } else { $null }) }
    admin = $admin
})
