# App updates through winget, Windows' own package manager.
#   { mode: 'list' }            -> { available: bool, apps: [{ id, name, version, latest }] }
#   { mode: 'upgrade', id }     -> { id, ok, code }
param([string]$Payload = '', [string]$OutFile = '')
. "$PSScriptRoot\_lib.ps1"
trap { Fail $_.Exception.Message }
$a = Get-Args

$winget = Get-Command winget -ErrorAction SilentlyContinue
if (-not $winget) { Send ([ordered]@{ available = $false; apps = @() }); return }

function Run-Winget([string[]]$arguments) {
    $saved = [Console]::OutputEncoding
    try {
        [Console]::OutputEncoding = [Text.Encoding]::UTF8
        $text = (& $winget.Source @arguments 2>&1 | Out-String)
        return @{ text = $text; code = $LASTEXITCODE }
    } finally { [Console]::OutputEncoding = $saved }
}

# Reads winget's table. Columns are found from the header line, whose words are
# English in every Windows language; values from the line below the dashes.
function Parse-Table([string]$text) {
    $lines = @($text -split "`r?`n" | ForEach-Object { ($_ -split "`r")[-1] })
    $dash = -1
    for ($i = 1; $i -lt $lines.Count; $i++) { if ($lines[$i] -match '^-{10,}\s*$') { $dash = $i; break } }
    if ($dash -lt 1) { return @() }
    $header = $lines[$dash - 1]
    $starts = @([regex]::Matches($header, '\S+') | ForEach-Object { $_.Index })
    if ($starts.Count -lt 4) { return @() }
    $apps = @()
    for ($i = $dash + 1; $i -lt $lines.Count; $i++) {
        $line = $lines[$i]
        if (-not $line.Trim()) { break }
        if ($line.Length -lt $starts[3]) { break }   # the "N upgrades available." footer
        $cols = @()
        for ($c = 0; $c -lt $starts.Count; $c++) {
            $from = $starts[$c]
            $to = $(if ($c + 1 -lt $starts.Count) { $starts[$c + 1] } else { $line.Length })
            $cols += $(if ($from -lt $line.Length) { $line.Substring($from, [Math]::Min($to, $line.Length) - $from).Trim() } else { '' })
        }
        if ($cols[1] -notmatch '^[\w.+-]{2,100}$') { continue }
        $apps += [ordered]@{ name = $cols[0]; id = $cols[1]; version = $cols[2]; latest = $cols[3] }
    }
    return $apps
}

function List-Updates {
    $r = Run-Winget @('upgrade', '--accept-source-agreements', '--disable-interactivity')
    return @(Parse-Table $r.text)
}

switch ($a.mode) {
    'list' {
        Send ([ordered]@{ available = $true; apps = @(List-Updates) })
    }
    'upgrade' {
        $id = [string]$a.id
        if ($id -notmatch '^[\w.+-]{2,100}$') { Fail 'Unknown app' }
        if (-not (List-Updates | Where-Object { $_.id -eq $id })) { Fail 'No update for that app' }
        $r = Run-Winget @('upgrade', '--id', $id, '--exact', '--silent', '--accept-package-agreements',
                          '--accept-source-agreements', '--disable-interactivity')
        Send ([ordered]@{ id = $id; ok = ($r.code -eq 0); code = $r.code })
    }
    default { Fail 'Unknown mode' }
}
