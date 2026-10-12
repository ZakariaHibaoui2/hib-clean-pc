# Pre-installed apps (bloatware) for the current user.
#   { mode: 'list' }                    -> [{ id, name, kind, installed }]   only apps from the list below
#   { mode: 'remove', ids: [...] }      -> [{ id, ok, error? }]
#
# Only packages named in this list can be removed, and only for the current
# user (no admin rights, nothing system-wide). Each one can be reinstalled from
# the Microsoft Store.
param([string]$Payload = '', [string]$OutFile = '')
. "$PSScriptRoot\_lib.ps1"
trap { Fail $_.Exception.Message }
$a = Get-Args

# package name pattern -> display name, kind
#   junk:     promos and apps almost nobody uses
#   optional: useful for some people (shown unticked)
$known = [ordered]@{
    'Microsoft.BingNews'                         = @('Microsoft News', 'junk')
    'Microsoft.BingSearch'                       = @('Bing Search', 'junk')
    'Microsoft.GetHelp'                          = @('Get Help', 'junk')
    'Microsoft.Getstarted'                       = @('Tips', 'junk')
    'Microsoft.MicrosoftSolitaireCollection'     = @('Solitaire Collection', 'junk')
    'Microsoft.MicrosoftOfficeHub'               = @('Microsoft 365 (Office) promo', 'junk')
    'Microsoft.People'                           = @('People', 'junk')
    'Microsoft.WindowsFeedbackHub'               = @('Feedback Hub', 'junk')
    'Microsoft.WindowsMaps'                      = @('Maps', 'junk')
    'Microsoft.MixedReality.Portal'              = @('Mixed Reality Portal', 'junk')
    'Microsoft.SkypeApp'                         = @('Skype', 'junk')
    'Microsoft.549981C3F5F10'                    = @('Cortana', 'junk')
    'Microsoft.PowerAutomateDesktop'             = @('Power Automate', 'junk')
    'Microsoft.Todos'                            = @('Microsoft To Do', 'optional')
    'Clipchamp.Clipchamp'                        = @('Clipchamp', 'junk')
    'MicrosoftTeams'                             = @('Teams (personal)', 'optional')
    'MSTeams'                                    = @('Teams', 'optional')
    'Microsoft.Copilot'                          = @('Copilot', 'optional')
    'Microsoft.BingWeather'                      = @('Weather', 'optional')
    'Microsoft.YourPhone'                        = @('Phone Link', 'optional')
    'Microsoft.OutlookForWindows'                = @('Outlook (new)', 'optional')
    'Microsoft.GamingApp'                        = @('Xbox', 'optional')
    'Microsoft.XboxGamingOverlay'                = @('Xbox Game Bar', 'optional')
    'Microsoft.Windows.DevHome'                  = @('Dev Home', 'junk')
    '7EE7776C.LinkedInforWindows'                = @('LinkedIn', 'junk')
    'SpotifyAB.SpotifyMusic'                     = @('Spotify', 'optional')
    'BytedancePte.Ltd.TikTok'                    = @('TikTok', 'junk')
    'Facebook.Facebook'                          = @('Facebook', 'junk')
    'Facebook.InstagramBeta'                     = @('Instagram', 'junk')
    'Disney.37853FC22B2CE'                       = @('Disney+', 'junk')
    'AmazonVideo.PrimeVideo'                     = @('Prime Video', 'junk')
    '5A894077.McAfeeSecurity'                    = @('McAfee (trial)', 'junk')
    'king.com.CandyCrushSaga'                    = @('Candy Crush Saga', 'junk')
    'king.com.CandyCrushSodaSaga'                = @('Candy Crush Soda Saga', 'junk')
    'king.com.BubbleWitch3Saga'                  = @('Bubble Witch 3', 'junk')
}

$installed = @{}
foreach ($p in @(Get-AppxPackage -ErrorAction SilentlyContinue)) {
    if ($known.Contains($p.Name) -and -not $p.IsFramework -and -not $p.NonRemovable) { $installed[$p.Name] = $p }
}

switch ($a.mode) {
    'list' {
        $out = foreach ($name in $known.Keys) {
            if (-not $installed.ContainsKey($name)) { continue }
            [ordered]@{ id = $name; name = $known[$name][0]; kind = $known[$name][1]; version = [string]$installed[$name].Version }
        }
        Send @($out)
    }
    'remove' {
        $out = foreach ($id in @($a.ids)) {
            if (-not $known.Contains([string]$id)) { [ordered]@{ id = $id; ok = $false; error = 'not-allowed' }; continue }
            if (-not $installed.ContainsKey([string]$id)) { [ordered]@{ id = $id; ok = $true; error = 'already-gone' }; continue }
            try {
                Remove-AppxPackage -Package $installed[[string]$id].PackageFullName -ErrorAction Stop
                [ordered]@{ id = $id; ok = $true }
            } catch { [ordered]@{ id = $id; ok = $false; error = $_.Exception.Message } }
        }
        Send @($out)
    }
    default { Fail 'Unknown mode' }
}
