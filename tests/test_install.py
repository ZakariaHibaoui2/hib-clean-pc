"""Installs the local build with docs/install.ps1, checks shortcuts and the
Settings > Apps entry, then uninstalls and checks everything is gone except the
undo files.

Run: python tests/test_install.py
"""
import os
import subprocess
import sys
import winreg
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(("PASS " if ok else "FAIL ") + name + (f"  ({detail})" if detail and not ok else ""))


def folder(name):
    return Path(subprocess.run(["powershell", "-NoProfile", "-Command", f"[Environment]::GetFolderPath('{name}')"],
                               capture_output=True, text=True).stdout.strip())


def uninstall_entry():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Uninstall\HibCleanPC") as k:
            return {n: winreg.QueryValueEx(k, n)[0] for n in ["DisplayName", "DisplayVersion", "UninstallString", "InstallLocation"]}
    except FileNotFoundError:
        return None


def main():
    app_dir = Path(os.environ["LOCALAPPDATA"]) / "Programs" / "Hib Clean PC"
    data = Path(os.environ["LOCALAPPDATA"]) / "Hib Clean PC"
    start = folder("Programs") / "Hib Clean PC.lnk"
    desk = folder("Desktop") / "Hib Clean PC.lnk"
    marker = data / "test-undo-marker.json"
    data.mkdir(exist_ok=True)
    marker.write_text("{}")
    env = {**os.environ, "HIB_INSTALL_FROM": str(ROOT / "dist" / "HibCleanPC.exe"), "HIB_NO_LAUNCH": "1"}
    r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ROOT / "docs" / "install.ps1")],
                       capture_output=True, text=True, env=env)
    check("installer runs", r.returncode == 0, r.stderr[-300:])
    check("app copied", (app_dir / "HibCleanPC.exe").exists())
    check("Start menu shortcut", start.exists())
    check("Desktop shortcut", desk.exists())
    entry = uninstall_entry()
    check("listed in Settings > Apps", entry is not None and entry["DisplayName"] == "Hib Clean PC" and entry["DisplayVersion"] == "1.0.0", str(entry))
    if entry:
        r = subprocess.run(entry["UninstallString"], shell=True, capture_output=True, text=True)
        check("uninstall runs", r.returncode == 0, r.stderr[-300:])
    check("app folder removed", not app_dir.exists())
    check("shortcuts removed", not start.exists() and not desk.exists())
    check("Settings > Apps entry removed", uninstall_entry() is None)
    check("undo files kept", marker.exists())
    marker.unlink(missing_ok=True)
    print(f"\n{sum(results)}/{len(results)} checks passed")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
