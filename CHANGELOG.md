# Changelog

## 1.1.0

- **Security check**: a new screen that shows, in plain words, whether Microsoft Defender's real-time protection is on and how old its virus definitions are, the firewall for each kind of network, when Windows Update last installed updates and whether a restart is waiting, drive encryption on C:, Secure Boot, the TPM security chip, SmartScreen and User Account Control. Each item has a button that opens the right Windows Security or Settings page. It needs no administrator rights, and anything Windows won't show without them is marked "Needs permission to check" instead of guessed.
- **Big files**: the 30 largest files (100 MB or more) in Downloads, Desktop, Documents, Videos, Pictures and Music, plus installers and archives in Downloads older than 30 days. "Show in folder" opens Explorer on the file; "Move to Recycle Bin" asks for a second click and only ever moves files to the Recycle Bin, so they can be restored. Files the Recycle Bin can't take (too big, or on a drive without one) are left in place, never deleted for good. Files kept only online in OneDrive aren't counted.
- **Privacy**: which apps used the camera, microphone and location, when, and which are using them right now, with whether access is on, and buttons to the matching Privacy settings pages.
- The health score now counts real-time virus protection being off (10 points) and the firewall being off (8 points). Checks Windows didn't let the app read cost nothing.
- New Home tile and sidebar badge for the security check.
- 3D underwater scene behind the interface, and depth on the main surfaces: they lean slightly toward the pointer like glass under water (off with reduced motion).
- Fixed: the app could fail to start with "access denied on WebView2Loader.dll" when an older copy was still running. Each version now unpacks into its own folder.

## 1.0.0

First release.

- PC health score shown as a 3D glass orb filled with liquid, with the four most useful fixes and a one-click Quick clean.
- Clean up: temporary files, browser caches, Windows Update files, error reports, crash dumps, picture previews and the Recycle Bin.
- Startup apps with Task Manager's on/off switches.
- Windows clean-up: 11 ads and suggestions switched off with undo, restore point first, and removal of pre-installed junk apps.
- Battery: health, drain while asleep, what woke the PC, and devices allowed to wake it.
- App updates in one click through winget.
- Ad blocking for every app through AdGuard DNS, with Quad9, Cloudflare and Automatic.
- Used laptop check with screen, keyboard, camera, microphone and speaker tests, and a PDF report.
- English, French and Arabic.
- Tested for accuracy: every number is checked against an independent source, and the admin features are tested for real and restored.
