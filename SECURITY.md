# Security policy

Hib Clean PC changes Windows settings and deletes files, so security reports are taken seriously.

## Supported versions

Only the [latest release](https://github.com/ZakariaHibaoui2/hib-clean-pc/releases/latest) gets fixes. Please check that the problem still happens there before reporting it.

## Reporting a vulnerability

**Please don't open a public issue for a security problem.**

Report it privately through GitHub: open the repository's **Security** tab and click **Report a vulnerability**, or go straight to
<https://github.com/ZakariaHibaoui2/hib-clean-pc/security/advisories/new>.

Helpful details:

- the app version and Windows version;
- what an attacker can do, and what they need first (for example a local account, or a file placed in a certain folder);
- steps or a small proof of concept;

Please remove anything private first (serial numbers, user names, file paths with your name).

You can expect a first reply within a week. Once a fix is released, the advisory is published and you are credited unless you'd rather not be.

## What counts

Examples of problems worth reporting:

- the cleaner deleting anything outside the cache folders it knows, or following a shortcut or junction out of them;
- a way to make the app run a script or command that isn't one of its bundled scripts;
- an action that changes Windows without the Windows permission prompt, or without a way to undo it;
- the installer or the app sending data anywhere not described in [PRIVACY.md](PRIVACY.md);
- a way to tamper with the download or the install script.

## Verifying a download

Every release lists the SHA-256 of `HibCleanPC.exe` in its notes and in `SHA256SUMS.txt`. To check your copy:

```powershell
(Get-FileHash .\HibCleanPC.exe -Algorithm SHA256).Hash
```

Releases are built from the tagged source by the [Release workflow](.github/workflows/release.yml) on GitHub Actions.
