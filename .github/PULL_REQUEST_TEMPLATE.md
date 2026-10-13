## What this changes

<!-- One or two sentences. Link the issue if there is one: Fixes #123 -->

## Why

## How it was tested

<!-- Tick what you ran. The admin suite changes real settings and puts them back. -->

- [ ] `node tests/score.test.mjs`
- [ ] `python tools/build.py`
- [ ] `python tests/test_scripts.py`
- [ ] `python tests/test_accuracy.py`
- [ ] `python tests/test_app.py`
- [ ] `python tests/test_install.py`
- [ ] `python tests/test_admin.py` (only if admin features changed)

## Checklist

- [ ] Any change to Windows can be undone, and the old value is saved first.
- [ ] Nothing new is sent over the network (or it is explained in PRIVACY.md).
- [ ] New interface text is translated in `ui/i18n.js` for English, French and Arabic.
- [ ] C# still compiles with the built-in C# 5 compiler (no `$"..."`, `?.`, `=>` members).
- [ ] PowerShell works in Windows PowerShell 5.1.
- [ ] CHANGELOG.md is updated for user-visible changes.
- [ ] Screenshots and logs contain nothing private (serial numbers, user names).
