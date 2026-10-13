# Contributing to Hib Clean PC

Thanks for helping. Bug reports, accuracy fixes, translations and small focused improvements are all welcome.

Before you start on something big, please [open an issue](https://github.com/ZakariaHibaoui2/hib-clean-pc/issues/new/choose) so we can agree on the approach. Security problems go to a [private advisory](SECURITY.md), not an issue.

By taking part you agree to follow the [Code of Conduct](CODE_OF_CONDUCT.md).

## Ground rules

Hib Clean PC changes real PCs, so every contribution has to keep these promises:

- **Scans are read-only.** Looking at the PC never changes it.
- **Every Windows change can be undone.** Save the old value before changing it, and make Undo put exactly that back.
- **Administrator rights only through the Windows permission prompt (UAC),** asked for each action that needs them. The app itself runs without admin rights.
- **Delete only inside known cache folders.** Never follow shortcuts or junctions, never touch drive or profile roots, skip files from the last 24 hours and files in use.
- **Nothing is sent anywhere** beyond what [PRIVACY.md](PRIVACY.md) describes.
- **No new dependencies** for the app at run time. It ships as one `.exe` with the scripts and interface inside.

## Project layout

| Folder | What's in it |
|---|---|
| `app/` | The C# host: a WebView2 window that runs only the bundled scripts. |
| `scripts/` | One PowerShell script per feature. Each takes a base64 JSON payload and prints JSON. |
| `ui/` | The interface: plain HTML, CSS and JavaScript, no framework. Text lives in `ui/i18n.js`. |
| `docs/` | The website and `install.ps1`, served by GitHub Pages. |
| `tools/` | `build.py` (builds the app) and `screens.py` (README screenshots). |
| `tests/` | The test suites. |

## What you need

- Windows 10 or 11 with Microsoft Edge WebView2 (Windows 11 has it).
- Python 3.12 or newer. The app test also needs Playwright: `pip install playwright` (it connects to the app's own WebView2, so no browser download is needed).
- Node.js 22 for the health score test and the JavaScript checks.

There is nothing else to install. The build uses the C# compiler that ships with Windows and downloads the WebView2 SDK from NuGet the first time.

## Two limits to know about

- **C# 5 only.** `tools/build.py` compiles with Windows' built-in compiler at `C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe`, which understands C# 5. That means no string interpolation (`$"..."`), no `?.` or `nameof`, no expression-bodied members (`=>`), no `out var`, no tuples and no pattern matching. Use `string.Format` or `+`, and plain `if` checks.
- **Windows PowerShell 5.1.** Scripts run in the PowerShell that comes with Windows, not PowerShell 7. Avoid `??`, `?:`, `&&`/`||` between commands, `ForEach-Object -Parallel` and other 7-only features. Write JSON with `ConvertTo-Json -Depth` set explicitly.

## Build

```sh
python tools/build.py           # makes dist/HibCleanPC.exe
python tools/build.py --icon    # also redraws app/app.ico from ui/mark.svg (needs Pillow and Playwright)
```

## Test

Run the suites that match what you changed. None of them change your settings unless noted.

```sh
node tests/score.test.mjs       # the health score: exact results for known situations
python tests/test_scripts.py    # the scripts, against a sandbox folder and a throwaway registry key
python tests/test_accuracy.py   # every number checked against an independent source (read-only)
python tests/test_app.py        # launches the real app read-only and visits every screen
python tests/test_install.py    # installs with docs/install.ps1, checks shortcuts and Settings > Apps, uninstalls
python tests/test_admin.py      # admin features for real, then everything put back (asks permission once)
```

`test_app.py` runs the app with `HIB_READONLY=1`, which makes it refuse every action that isn't a scan, list, status or report. Only run `test_admin.py` if you changed a feature that needs admin rights; it switches DNS, applies and undoes settings, and makes a restore point, then restores everything.

Continuous integration ([`.github/workflows/ci.yml`](.github/workflows/ci.yml)) checks that the JavaScript and every PowerShell script parse, that all translations are complete, runs the health score test, builds the app and runs the script tests.

## Translations

The interface is in English, French and Arabic (right to left). Every key in `I18N.en` in `ui/i18n.js` must also exist in `fr` and `ar`; CI fails otherwise. If you can't translate a new string, add the English text and say so in the pull request.

## Pull requests

- Keep each pull request to one change, and explain why it's needed.
- Update [CHANGELOG.md](CHANGELOG.md) for anything users will notice.
- Don't include personal data in code, tests, logs or screenshots (serial numbers, user names, paths with your name).
- The pull request template has a checklist; please go through it.

Contributions are licensed under [GPL-3.0](LICENSE), the same as the project.
