<div align="center">

<img src="assets/icon-256.png" width="96" height="96" alt="Hib Clean PC logo">

# Hib Clean PC

**A free, open-source clean-up and health app for Windows 11 and 10.**<br>
One health score for your PC, junk files cleaned, Windows ads removed, battery explained, apps updated and ads blocked in every app. Every change can be undone.

[![Checks](https://img.shields.io/github/actions/workflow/status/ZakariaHibaoui2/hib-clean-pc/ci.yml?branch=main&label=checks&logo=githubactions&logoColor=e4f0ec&labelColor=10272b)](https://github.com/ZakariaHibaoui2/hib-clean-pc/actions/workflows/ci.yml)
[![Latest release](https://img.shields.io/github/v/release/ZakariaHibaoui2/hib-clean-pc?label=release&color=f3b23c&labelColor=10272b)](https://github.com/ZakariaHibaoui2/hib-clean-pc/releases/latest)
[![Downloads](https://img.shields.io/github/downloads/ZakariaHibaoui2/hib-clean-pc/total?color=183a3f&labelColor=10272b)](https://github.com/ZakariaHibaoui2/hib-clean-pc/releases)
[![Platform: Windows 10 | 11](https://img.shields.io/badge/platform-Windows%2010%20%7C%2011-0078d4?logo=windows&logoColor=e4f0ec&labelColor=10272b)](#install)
[![License: GPL-3.0](https://img.shields.io/badge/license-GPL--3.0-e4f0ec?labelColor=10272b)](LICENSE)

[**Install**](#install) · [**Download**](https://github.com/ZakariaHibaoui2/hib-clean-pc/releases/latest/download/HibCleanPC.exe) · [**Website**](https://zakariahibaoui2.github.io/hib-clean-pc/) · [**Changelog**](CHANGELOG.md)

English · Français · العربية

<br>

<img src="assets/screens/home.png" width="820" alt="Hib Clean PC home screen: a health score out of 100 with the four most useful fixes, and tiles for free space, memory, junk files, battery health, app updates and ad blocking">

</div>

## Contents

- [What it does](#what-it-does)
- [Install](#install)
- [Safe by design](#safe-by-design)
- [How it's tested](#how-its-tested)
- [How it's built](#how-its-built)
- [Build from source](#build-from-source)
- [Privacy](#privacy)
- [Contributing and security](#contributing-and-security)
- [License](#license)

## What it does

| | |
|---|---|
| **PC health score** | A 3D glass orb that fills to your score from 0 to 100, the fixes that matter most, and **Quick clean** for the junk that needs no permission. |
| **Clean up** | Temporary files, browser caches, old Windows Update files, error reports, crash dumps, picture previews and the Recycle Bin. Files from the last 24 hours and anything in use are left alone, and your passwords, history and logins stay. |
| **Startup apps** | Every app that starts with Windows, with an on/off switch. It's the same switch Task Manager uses, so nothing is deleted. |
| **Windows clean-up** | Turns off 11 kinds of Windows 11 ads and suggestions (Start, lock screen, Settings, File Explorer, Bing in search, Copilot…), opens the Widgets switch in Settings and removes pre-installed junk apps. Every change can be undone, and it can make a restore point first. |
| **Battery** | Battery health in plain words ("holds 84% of its original charge"), how much it drained in each recent sleep, what woke the laptop, and which devices are allowed to wake it. |
| **App updates** | Updates all your apps in one click with winget, Windows' own installer. |
| **Ad blocking for every app** | One switch sets AdGuard DNS, which blocks ads and trackers in every app and game, not just the browser. Quad9 and Cloudflare are offered too, and "Automatic" puts back exactly what you had. |
| **Used laptop check** | Before buying or selling a laptop: model, processor, RAM slots, SSD health and wear, battery health, Windows activation, plus screen, keyboard, camera, microphone and speaker tests. Then a PDF report to share. |

<table>
<tr>
<td width="50%"><img src="assets/screens/clean.png" alt="The clean-up screen listing temporary files, browser cache, Windows temporary files and other categories with their sizes"><br><sub><b>Clean up</b>: see what each category holds before anything is deleted.</sub></td>
<td width="50%"><img src="assets/screens/windows.png" alt="The Windows clean-up screen listing ads and suggestions to remove, each with a Remove button"><br><sub><b>Windows clean-up</b>: ads and suggestions off, each one undoable.</sub></td>
</tr>
<tr>
<td><img src="assets/screens/battery.png" alt="The battery screen: battery health, current charge, capacity, and battery used during each recent sleep"><br><sub><b>Battery</b>: health in plain words and drain during sleep.</sub></td>
<td><img src="assets/screens/adblock.png" alt="The ad blocking screen offering AdGuard DNS (recommended), Quad9, Cloudflare and Automatic, with an Apply button"><br><sub><b>Ad blocking</b>: AdGuard DNS for every app, and "Automatic" to go back.</sub></td>
</tr>
<tr>
<td><img src="assets/screens/laptop.png" alt="The used laptop check, in French, listing the model, processor, memory, graphics, storage, screen, Windows and battery"><br><sub><b>Used laptop check</b>, shown in French.</sub></td>
<td><img src="assets/screens/home-ar.png" alt="The home screen in Arabic, laid out right to left"><br><sub>Fully translated, including Arabic right to left.</sub></td>
</tr>
</table>

## Install

Needs Windows 10 or 11 with Microsoft Edge WebView2, which Windows 11 already has. No administrator rights are needed to install.

### Option 1: one command (recommended)

Open **PowerShell** (press the Windows key, type `powershell`, press Enter) and paste:

```powershell
irm https://zakariahibaoui2.github.io/hib-clean-pc/install.ps1 | iex
```

It downloads the latest `HibCleanPC.exe` from this repository's [Releases](https://github.com/ZakariaHibaoui2/hib-clean-pc/releases) into `%LOCALAPPDATA%\Programs\Hib Clean PC`, adds Start menu and Desktop shortcuts, and lists Hib Clean PC in **Settings → Apps** so you can uninstall it like any app. You can [read the script](docs/install.ps1) before running it.

### Option 2: download the app

Download **[HibCleanPC.exe](https://github.com/ZakariaHibaoui2/hib-clean-pc/releases/latest/download/HibCleanPC.exe)** from the [latest release](https://github.com/ZakariaHibaoui2/hib-clean-pc/releases/latest) and run it. It works without installing.

> [!NOTE]
> **About the "Windows protected your PC" warning.** The app isn't signed with a paid code-signing certificate, and Microsoft Defender SmartScreen warns about unsigned apps it hasn't seen downloaded many times before. The warning doesn't mean anything harmful was found. Click **More info**, then **Run anyway**.
>
> The one-command install doesn't show this warning because files downloaded by PowerShell aren't marked as coming from the internet the way browser downloads are. That also means the check is up to you: you can read the [install script](docs/install.ps1) and the [source](app/HibCleanPC.cs), and compare the file's SHA-256 with the one listed in each release:
>
> ```powershell
> (Get-FileHash .\HibCleanPC.exe -Algorithm SHA256).Hash
> ```
>
> Every release is built from its tagged source by the [Release workflow](.github/workflows/release.yml) on GitHub Actions.

### Uninstall

Open **Settings → Apps**, find **Hib Clean PC** and click **Uninstall**. The two small undo files are kept, so changes the app made can still be undone if you install it again (see [PRIVACY.md](PRIVACY.md)).

## Safe by design

- **Scans are read-only.** Opening a screen only reads your PC; nothing changes until you click a button that says what it will do.
- **It asks before changing Windows.** The app runs without administrator rights. Actions that change system settings (like cleaning Windows' own folders, ad blocking or widgets) show Windows' own permission prompt (UAC) each time, and nothing changes if you say No.
- **Every Windows change can be undone.** Before changing a setting it saves the old value, and Undo puts exactly that back. DNS "Automatic" restores what your PC used before. Windows clean-up can make a **system restore point** first.
- **It only deletes inside known cache folders.** It never follows shortcuts or junctions out of them, refuses to touch drive or profile roots, and skips files from the last 24 hours and files in use. This is covered by tests in [`tests/test_scripts.py`](tests/test_scripts.py).
- **Apps are removed only for you,** and only from a fixed list of promo apps. Windows' own apps (Store, Calculator…) can't be removed. Each one can be reinstalled from the Microsoft Store.
- **It runs only its own scripts.** The app host runs only the PowerShell scripts bundled inside it, by name, and nothing else. Arguments travel as base64 JSON, never as command-line text.
- **Open source.** Every action is a short PowerShell script in [`scripts/`](scripts) that you can read.

## How it's tested

Six test suites run against the real app, the real scripts and real Windows:

| Suite | What it checks | Checks |
|---|---|---:|
| [`test_scripts.py`](tests/test_scripts.py) | Every script, against a sandbox folder and a throwaway registry key, including the cleaner's safety rules | 38 |
| [`test_accuracy.py`](tests/test_accuracy.py) | Every number the app shows, compared with an independent source (the registry, Python, raw tool output) | 49 |
| [`test_app.py`](tests/test_app.py) | Launches the real app in a read-only mode and visits every screen | 36 |
| [`test_install.py`](tests/test_install.py) | Installs, checks the shortcuts and Settings → Apps entry, then uninstalls | 10 |
| [`test_admin.py`](tests/test_admin.py) | The features that need admin rights, for real, then everything put back exactly as it was | 13 |
| [`score.test.mjs`](tests/score.test.mjs) | The health score: exact results for known situations | |

All passing on the development PC. The tests never leave your settings changed: changes run in a sandbox folder and a throwaway registry key, the app test runs the app in a mode that refuses every action, and the admin test restores everything it touches.

[Continuous integration](.github/workflows/ci.yml) runs on every push and pull request: it checks that the JavaScript and every PowerShell script parse, that all three languages have every string, runs the health score test, builds the app and runs the script tests.

## How it's built

| Part | What it does | Where |
|---|---|---|
| App host | A small C# program that opens a WebView2 window and runs only the bundled scripts. | [`app/HibCleanPC.cs`](app/HibCleanPC.cs) |
| Scripts | One PowerShell script per feature, returning JSON. Written for Windows PowerShell 5.1, which every Windows PC has. | [`scripts/`](scripts) |
| Interface | HTML, CSS and JavaScript with no framework, in English, French and Arabic (right to left). | [`ui/`](ui) |
| Installer | The one-command installer and the website, served by GitHub Pages. | [`docs/`](docs) |

The result is a single `HibCleanPC.exe` with the interface, scripts and WebView2 inside it.

## Build from source

You need Windows 10 or 11, Python 3.12+ and Node.js 22. The build uses the C# compiler built into Windows, so no Visual Studio or .NET SDK is needed.

```sh
python tools/build.py              # dist/HibCleanPC.exe, using the C# compiler built into Windows
node tests/score.test.mjs          # the health score, exact results for known situations
python tests/test_scripts.py       # the scripts, against a sandbox folder and a test registry key
python tests/test_accuracy.py      # every number checked against an independent source
python tests/test_app.py           # launches the real app read-only and visits every screen (needs Playwright)
python tests/test_install.py       # installs, checks shortcuts and Settings > Apps, uninstalls
python tests/test_admin.py         # admin features for real, then everything put back (asks permission once)
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for details, including the C# 5 and PowerShell 5.1 limits.

## Privacy

No account, no analytics, no ads and no servers. The app sends nothing about you or your PC anywhere. The only network use is winget checking for updates when you open App updates, and the one-domain DNS lookup that shows whether ads are blocked. Undo data stays in `%LOCALAPPDATA%\Hib Clean PC`. Full details in [PRIVACY.md](PRIVACY.md).

## Contributing and security

- Found a bug or a wrong number? [Open an issue](https://github.com/ZakariaHibaoui2/hib-clean-pc/issues/new/choose).
- Want to help? Read [CONTRIBUTING.md](CONTRIBUTING.md) and the [Code of Conduct](CODE_OF_CONDUCT.md).
- Found a security problem? Please report it privately, as described in [SECURITY.md](SECURITY.md).

## Also from Hib

**[Hib Remover Ads](https://github.com/ZakariaHibaoui2/hib-remover-ads)**: a free, open-source ad blocker for Chrome, Edge, Brave and Opera.

## License

Made by [Zakaria Hibaoui](https://github.com/ZakariaHibaoui2). Licensed under [GPL-3.0](LICENSE). Fonts: [Bricolage Grotesque](https://github.com/ateliertriay/bricolage) and [Figtree](https://github.com/erikdkennedy/figtree), SIL Open Font License. 3D orb rendered with [three.js](https://threejs.org) (MIT). Uses Microsoft Edge WebView2.

Hib Clean PC is an independent project and isn't affiliated with Microsoft, AdGuard, Quad9 or Cloudflare.
