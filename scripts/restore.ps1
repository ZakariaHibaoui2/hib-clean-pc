# System restore point before bigger changes.
#   { mode: 'create' }   -> { created, reason? }   (admin)
# Windows allows one new restore point per 24 hours by default; if one was made
# recently it says so instead of failing.
param([string]$Payload = '', [string]$OutFile = '')
. "$PSScriptRoot\_lib.ps1"
trap { Fail $_.Exception.Message }
$a = Get-Args

if ($a.mode -ne 'create') { Fail 'Unknown mode' }
if (-not (Test-Admin)) { Fail 'needs-admin' }

$before = @(Get-ComputerRestorePoint -ErrorAction SilentlyContinue).Count
try {
    Checkpoint-Computer -Description 'Hib Clean PC' -RestorePointType 'MODIFY_SETTINGS' -WarningAction SilentlyContinue -ErrorAction Stop
} catch {
    # Usually: System Protection is turned off for the system drive.
    Send ([ordered]@{ created = $false; reason = 'off'; detail = $_.Exception.Message })
    return
}
$after = @(Get-ComputerRestorePoint -ErrorAction SilentlyContinue).Count
Send ([ordered]@{ created = ($after -gt $before); reason = $(if ($after -gt $before) { $null } else { 'recent' }) })
