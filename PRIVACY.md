# Privacy

Hib Clean PC has no account, no analytics, no ads and no servers. It doesn't send anything about you or your PC anywhere.

## What stays on your PC

Kept in `%LOCALAPPDATA%\Hib Clean PC`, on your PC only:

- the old values of settings it changed, so Undo can put them back (`tweaks-backup.json`);
- the DNS your PC used before you switched, so "Automatic" can restore it (`dns-backup.json`);
- the app's own files and the WebView2 cache.

Uninstalling removes the app and its files, and keeps the two undo files so changes can still be undone if you reinstall.

## When it uses the internet

- **App updates** asks winget, Windows' own package manager, which apps have updates and downloads them when you click Update. That's the same as running `winget upgrade` yourself.
- **Ad blocking** looks up one ad domain (`doubleclick.net`) through your current DNS to show whether ads are being blocked.
- **The used laptop check** never uploads anything. The camera and microphone tests stay inside the app, and the PDF is saved in your Documents folder.

The app turns off WebView2's online SmartScreen check, because it only ever shows its own local pages.

## Reports you share

The used laptop check PDF includes the laptop's serial number, so a buyer can check the warranty. Delete that line from the PDF, or don't share the file, if you'd rather keep it private.
