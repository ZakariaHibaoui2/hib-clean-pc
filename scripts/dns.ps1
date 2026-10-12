# System-wide ad blocking through DNS.
#   { mode: 'status' }                 -> { provider, adapters: [...], blocking }
#   { mode: 'set', provider }          -> status after the change   (admin)
#
# provider: 'adguard' (blocks ads and trackers in every app), 'quad9' (blocks
# malware sites), 'cloudflare' (fast, no filtering) or 'auto' (put back what the
# PC had before Hib Clean PC changed it).
param([string]$Payload = '', [string]$OutFile = '')
. "$PSScriptRoot\_lib.ps1"
trap { Fail $_.Exception.Message }
$a = Get-Args

$providers = [ordered]@{
    adguard    = @('94.140.14.14', '94.140.15.15', '2a10:50c0::ad1:ff', '2a10:50c0::ad2:ff')
    quad9      = @('9.9.9.9', '149.112.112.112', '2620:fe::fe', '2620:fe::9')
    cloudflare = @('1.1.1.1', '1.0.0.1', '2606:4700:4700::1111', '2606:4700:4700::1001')
}

function Adapters {
    @(Get-NetAdapter -Physical -ErrorAction SilentlyContinue | Where-Object { $_.Status -eq 'Up' })
}

function Static-Servers($adapter) {
    $servers = @()
    foreach ($family in @('Tcpip', 'Tcpip6')) {
        $key = "HKLM:\SYSTEM\CurrentControlSet\Services\$family\Parameters\Interfaces\$($adapter.InterfaceGuid)"
        $ns = (Get-ItemProperty -LiteralPath $key -Name NameServer -ErrorAction SilentlyContinue).NameServer
        if ($ns) { $servers += @($ns -split '[,\s]+' | Where-Object { $_ }) }
    }
    return $servers
}

function Current-Servers($adapter) {
    @(Get-DnsClientServerAddress -InterfaceIndex $adapter.ifIndex -ErrorAction SilentlyContinue |
        ForEach-Object { $_.ServerAddresses } | Where-Object { $_ -and $_ -notlike 'fec0:*' })
}

function Provider-Of([string[]]$servers) {
    foreach ($name in $providers.Keys) {
        if ($servers.Count -gt 0 -and @($servers | Where-Object { $providers[$name] -notcontains $_ }).Count -eq 0) { return $name }
    }
    return $null
}

function Status {
    $list = foreach ($ad in (Adapters)) {
        $servers = Current-Servers $ad
        [ordered]@{ index = $ad.ifIndex; name = $ad.Name; description = $ad.InterfaceDescription
                    servers = @($servers); static = (@(Static-Servers $ad).Count -gt 0); provider = (Provider-Of $servers) }
    }
    $list = @($list)
    # 'auto' = the DNS the network hands out (or one the user set), not one of ours.
    $names = @($list | ForEach-Object { if ($_.provider) { $_.provider } else { 'auto' } } | Select-Object -Unique)
    $provider = $(if ($list.Count -eq 0) { $null } elseif ($names.Count -eq 1) { $names[0] } else { 'mixed' })
    # A real check: AdGuard answers 0.0.0.0 for ad servers.
    $blocking = $false
    try {
        $r = Resolve-DnsName -Name 'doubleclick.net' -Type A -DnsOnly -QuickTimeout -ErrorAction Stop | Where-Object { $_.Type -eq 'A' }
        $blocking = [bool]($r | Where-Object { $_.IPAddress -eq '0.0.0.0' })
    } catch { }
    return [ordered]@{ provider = $provider; blocking = $blocking; adapters = $list; changed = [bool](Read-State 'dns-backup') }
}

switch ($a.mode) {
    'status' { Send (Status) }
    'set' {
        $provider = [string]$a.provider
        if ($provider -ne 'auto' -and -not $providers.Contains($provider)) { Fail 'Unknown provider' }
        if (-not (Test-Admin)) { Fail 'needs-admin' }
        $backup = Read-State 'dns-backup'
        $saved = @{}
        if ($backup) { foreach ($p in $backup.PSObject.Properties) { $saved[$p.Name] = $p.Value } }
        foreach ($ad in (Adapters)) {
            $key = [string]$ad.InterfaceGuid
            if ($provider -eq 'auto') {
                $before = $saved[$key]
                if ($before -and $before.static) {
                    Set-DnsClientServerAddress -InterfaceIndex $ad.ifIndex -ServerAddresses @($before.servers)
                } else {
                    Set-DnsClientServerAddress -InterfaceIndex $ad.ifIndex -ResetServerAddresses
                }
                $saved.Remove($key)
                continue
            }
            # Remember what this adapter used before our first change only.
            if (-not $saved.ContainsKey($key)) {
                $static = @(Static-Servers $ad)
                $saved[$key] = [ordered]@{ name = $ad.Name; static = ($static.Count -gt 0); servers = $static }
            }
            $hasV6 = [bool](Get-NetIPAddress -InterfaceIndex $ad.ifIndex -AddressFamily IPv6 -ErrorAction SilentlyContinue | Where-Object { $_.PrefixOrigin -ne 'WellKnown' -and $_.IPAddress -notlike 'fe80*' })
            $servers = @($providers[$provider] | Where-Object { $hasV6 -or $_ -notmatch ':' })
            Set-DnsClientServerAddress -InterfaceIndex $ad.ifIndex -ServerAddresses $servers
        }
        if ($saved.Count -gt 0) { Write-State 'dns-backup' $saved }
        else { Remove-Item -LiteralPath (Join-Path $script:AppData 'dns-backup.json') -ErrorAction SilentlyContinue }
        Clear-DnsClientCache -ErrorAction SilentlyContinue
        Start-Sleep -Milliseconds 500
        Send (Status)
    }
    default { Fail 'Unknown mode' }
}
