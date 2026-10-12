# Shared by every script. Dot-source it after the param block:
#   param([string]$Payload = '', [string]$OutFile = '')
#   . "$PSScriptRoot\_lib.ps1"
#   trap { Fail $_.Exception.Message }
#
# Arguments arrive as base64 JSON in $Payload. Results go to stdout as JSON,
# or to $OutFile when the script was started elevated (UAC can't pipe stdout).

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Console]::OutputEncoding = [Text.Encoding]::UTF8

$script:Utf8 = New-Object Text.UTF8Encoding $false

function Get-Args {
    if (-not $Payload) { return [pscustomobject]@{} }
    $text = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($Payload))
    $parsed = $text | ConvertFrom-Json
    if ($null -eq $parsed) { return [pscustomobject]@{} }
    return $parsed
}

function Send($Value) {
    $json = ConvertTo-Json -InputObject $Value -Depth 8 -Compress
    if ($OutFile) { [IO.File]::WriteAllText($OutFile, $json, $script:Utf8) }
    else { [Console]::Out.Write($json) }
}

function Fail([string]$Message) {
    if ($OutFile) { [IO.File]::WriteAllText($OutFile, $Message, $script:Utf8) }
    else { [Console]::Error.Write($Message) }
    exit 1
}

# Each script adds this right after loading the library (a trap only covers the
# scope it's written in):  trap { Fail $_.Exception.Message }

function Test-Admin {
    ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)
}

# Console tools like powercfg and netsh print in the old OEM code page, not UTF-8.
function Invoke-Native([scriptblock]$Command) {
    $saved = [Console]::OutputEncoding
    try {
        [Console]::OutputEncoding = [Text.Encoding]::GetEncoding([Globalization.CultureInfo]::CurrentCulture.TextInfo.OEMCodePage)
        return @(& $Command)
    } finally { [Console]::OutputEncoding = $saved }
}

# Where the app keeps undo information and logs.
$script:AppData = Join-Path $env:LOCALAPPDATA 'Hib Clean PC'
if (-not (Test-Path $script:AppData)) { New-Item -ItemType Directory -Path $script:AppData -Force | Out-Null }

function Read-State([string]$Name) {
    $path = Join-Path $script:AppData "$Name.json"
    if (Test-Path $path) { return (Get-Content $path -Raw -Encoding UTF8 | ConvertFrom-Json) }
    return $null
}

function Write-State([string]$Name, $Value) {
    $path = Join-Path $script:AppData "$Name.json"
    [IO.File]::WriteAllText($path, (ConvertTo-Json -InputObject $Value -Depth 8), $script:Utf8)
}
