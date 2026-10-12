# Hib Clean PC installer.
# Run in PowerShell:  irm https://zakariahibaoui2.github.io/hib-clean-pc/install.ps1 | iex
#
# Downloads the latest HibCleanPC.exe from GitHub into your user folder
# (%LOCALAPPDATA%\Programs\Hib Clean PC), adds Start menu and Desktop shortcuts,
# and registers it in Settings > Apps so it can be uninstalled like any app.
# No administrator rights needed.

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$url = 'https://github.com/ZakariaHibaoui2/hib-clean-pc/releases/latest/download/HibCleanPC.exe'
$dir = Join-Path $env:LOCALAPPDATA 'Programs\Hib Clean PC'
$exe = Join-Path $dir 'HibCleanPC.exe'
$startMenu = Join-Path ([Environment]::GetFolderPath('Programs')) 'Hib Clean PC.lnk'
$desktop = Join-Path ([Environment]::GetFolderPath('Desktop')) 'Hib Clean PC.lnk'
$uninstallKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\HibCleanPC'

Write-Host ''
Write-Host '  Hib Clean PC' -ForegroundColor Yellow
Write-Host '  Free PC clean-up, battery check and ad blocking for Windows' -ForegroundColor DarkGray
Write-Host ''

Get-Process HibCleanPC -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $dir | Out-Null

Write-Host '  Downloading the latest version...'
$tmp = "$exe.download"
# HIB_INSTALL_FROM: tests install a local build instead of the GitHub release.
if ($env:HIB_INSTALL_FROM) { Copy-Item -LiteralPath $env:HIB_INSTALL_FROM -Destination $tmp -Force }
else { Invoke-WebRequest -Uri $url -OutFile $tmp -UseBasicParsing }
Move-Item -LiteralPath $tmp -Destination $exe -Force
$version = (Get-Item -LiteralPath $exe).VersionInfo.ProductVersion

$uninstall = @'
# Removes Hib Clean PC. Keeps its undo files (in %LOCALAPPDATA%\Hib Clean PC\*.json)
# so changes it made can still be undone if you install it again.
$ErrorActionPreference = 'SilentlyContinue'
Get-Process HibCleanPC | Stop-Process -Force
Start-Sleep -Milliseconds 500
Remove-Item -LiteralPath (Join-Path ([Environment]::GetFolderPath('Programs')) 'Hib Clean PC.lnk') -Force
Remove-Item -LiteralPath (Join-Path ([Environment]::GetFolderPath('Desktop')) 'Hib Clean PC.lnk') -Force
Remove-Item -LiteralPath 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\HibCleanPC' -Recurse -Force
$data = Join-Path $env:LOCALAPPDATA 'Hib Clean PC'
Get-ChildItem -LiteralPath $data -Directory | Remove-Item -Recurse -Force
Remove-Item -LiteralPath (Join-Path $env:LOCALAPPDATA 'Programs\Hib Clean PC') -Recurse -Force
'@
[IO.File]::WriteAllText((Join-Path $dir 'uninstall.ps1'), $uninstall, (New-Object Text.UTF8Encoding $true))

$shell = New-Object -ComObject WScript.Shell
foreach ($link in @($startMenu, $desktop)) {
    $s = $shell.CreateShortcut($link)
    $s.TargetPath = $exe
    $s.WorkingDirectory = $dir
    $s.IconLocation = "$exe,0"
    $s.Description = 'Hib Clean PC'
    $s.Save()
}

New-Item -Path $uninstallKey -Force | Out-Null
$sizeKb = [int]((Get-Item -LiteralPath $exe).Length / 1KB)
$values = @{
    DisplayName = 'Hib Clean PC'; DisplayVersion = $version; Publisher = 'Zakaria Hibaoui'
    DisplayIcon = "$exe,0"; InstallLocation = $dir; URLInfoAbout = 'https://github.com/ZakariaHibaoui2/hib-clean-pc'
    UninstallString = "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$dir\uninstall.ps1`""
}
foreach ($k in $values.Keys) { Set-ItemProperty -Path $uninstallKey -Name $k -Value $values[$k] }
Set-ItemProperty -Path $uninstallKey -Name NoModify -Value 1 -Type DWord
Set-ItemProperty -Path $uninstallKey -Name NoRepair -Value 1 -Type DWord
Set-ItemProperty -Path $uninstallKey -Name EstimatedSize -Value $sizeKb -Type DWord

Write-Host "  Installed version $version" -ForegroundColor Green
Write-Host '  Opening Hib Clean PC. It is also in your Start menu and on your Desktop.'
Write-Host ''
if ($env:HIB_NO_LAUNCH -ne '1') { Start-Process -FilePath $exe }
