"""Accuracy: every number the app shows is checked against an independent
source, read a different way (Python, the registry, raw command output).
Read-only: nothing on this PC is changed.

Run: python tests/test_accuracy.py
"""
import ctypes
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import winreg
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

import ps

ROOT = Path(__file__).resolve().parent.parent
results = []
sys.stdout.reconfigure(errors="replace")


def check(name, ok, detail=""):
    results.append(ok)
    print(("PASS " if ok else "FAIL ") + name + (f"  ({detail})" if detail and not ok else ""))


def reg_value(root, path, name, view=0):
    try:
        with winreg.OpenKey(root, path, 0, winreg.KEY_READ | view) as k:
            return winreg.QueryValueEx(k, name)[0]
    except OSError:
        return None


def oem(cmd):
    """Runs a console tool and decodes it in the console's current code page
    (console tools print in it; it's the OEM code page unless something changed it)."""
    cp = ctypes.windll.kernel32.GetConsoleOutputCP() or ctypes.windll.kernel32.GetOEMCP()
    return subprocess.run(cmd, capture_output=True).stdout.decode(f"cp{cp}", "replace")


# ---------- system ----------
def test_system():
    s = ps.run("system")
    du = shutil.disk_usage(os.environ["SystemDrive"] + "\\")
    check("disk total matches Windows", s["drive"]["total"] == du.total, f"{s['drive']['total']} vs {du.total}")
    check("disk free matches Windows (within 500 MB)", abs(s["drive"]["free"] - du.free) < 500 * 2**20, f"{s['drive']['free']} vs {du.free}")

    class MEM(ctypes.Structure):
        _fields_ = [("len", ctypes.c_ulong), ("load", ctypes.c_ulong), ("total", ctypes.c_ulonglong), ("avail", ctypes.c_ulonglong),
                    ("tpf", ctypes.c_ulonglong), ("apf", ctypes.c_ulonglong), ("tv", ctypes.c_ulonglong), ("av", ctypes.c_ulonglong), ("ext", ctypes.c_ulonglong)]
    m = MEM(); m.len = ctypes.sizeof(MEM)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
    check("total memory matches Windows", s["memory"]["total"] == m.total, f"{s['memory']['total']} vs {m.total}")
    check("free memory close to Windows (within 1 GB)", abs(s["memory"]["free"] - m.avail) < 2**30, f"{s['memory']['free']} vs {m.avail}")
    model = reg_value(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\BIOS", "SystemProductName")
    check("model matches the BIOS record", s["model"] == model, f"{s['model']} vs {model}")
    build = reg_value(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion", "CurrentBuild")
    ubr = reg_value(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion", "UBR")
    check("Windows build matches the registry", s["build"] == f"{build}.{ubr}", s["build"])
    up = ctypes.windll.kernel32.GetTickCount64() / 3.6e6
    check("uptime matches (within 0.2 h)", abs(s["uptimeHours"] - up) < 0.2, f"{s['uptimeHours']} vs {up:.2f}")


# ---------- laptop ----------
def test_laptop():
    info = ps.run("laptop")
    cpu = reg_value(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0", "ProcessorNameString")
    check("CPU name matches the registry", info["cpu"]["name"] == (cpu or "").strip(), f"{info['cpu']['name']} vs {cpu}")
    check("thread count matches Windows", info["cpu"]["threads"] == os.cpu_count(), f"{info['cpu']['threads']} vs {os.cpu_count()}")
    bios = reg_value(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\BIOS", "BIOSVersion")
    check("BIOS version matches the registry", info["bios"]["version"] == bios, f"{info['bios']['version']} vs {bios}")
    mods = info["memory"]["modules"]
    check("installed RAM equals the sum of the modules", info["memory"]["installed"] == sum(m["size"] for m in mods))
    check("RAM slots used equals modules found", info["memory"]["used"] == len(mods))
    check("installed RAM ≥ RAM Windows can use", info["memory"]["installed"] >= info["memory"]["total"])
    disks = json.loads(subprocess.run(["powershell", "-NoProfile", "-Command",
                                       "Get-Disk | Select-Object FriendlyName, Size | ConvertTo-Json -Compress"],
                                      capture_output=True, text=True).stdout)
    disks = disks if isinstance(disks, list) else [disks]
    sizes = sorted(d["Size"] for d in disks)
    check("disk sizes match Get-Disk", sorted(d["size"] for d in info["disks"]) == sizes, f"{[d['size'] for d in info['disks']]} vs {sizes}")
    if info["display"]["inches"] is not None:
        check("screen size is a real laptop size", 10 <= info["display"]["inches"] <= 19, str(info["display"]["inches"]))
    edition = reg_value(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion", "DisplayVersion")
    check("Windows version matches the registry", info["windows"]["version"] == edition)


# ---------- battery ----------
def battery_truth():
    path = Path(tempfile.mkdtemp()) / "br.xml"
    subprocess.run(["powercfg", "/batteryreport", "/xml", "/output", str(path)], capture_output=True)
    root = ET.parse(path).getroot()
    shutil.rmtree(path.parent, ignore_errors=True)
    ns = {"b": root.tag.split("}")[0].strip("{")}
    bats = root.findall(".//b:Batteries/b:Battery", ns)
    design = sum(int(b.find("b:DesignCapacity", ns).text) for b in bats)
    full = sum(int(b.find("b:FullChargeCapacity", ns).text) for b in bats)
    sleeps = []
    since = datetime.now(timezone.utc) - timedelta(days=14)
    for e in root.findall(".//b:RecentUsage/b:UsageEntry", ns):
        a = e.attrib
        if a["EntryType"] not in ("Suspend", "ConnectedStandby") or a["Ac"] != "0":
            continue
        start = datetime.fromisoformat(a["Timestamp"].replace("Z", "+00:00"))
        hours = int(a["Duration"]) / 1e7 / 3600
        if start < since or hours < 0.5 or hours > 240:
            continue
        cap = float(a["FullChargeCapacity"]) or full
        drain = max(0.0, float(a["Discharge"]))
        sleeps.append((start, round(hours, 1), round(100 * drain / cap, 1)))
    sleeps.sort(reverse=True)
    return design, full, sleeps[:10]


def test_battery():
    b = ps.run("battery", {"mode": "report"})
    has = bool(subprocess.run(["powershell", "-NoProfile", "-Command", "(Get-CimInstance Win32_Battery | Measure-Object).Count"],
                              capture_output=True, text=True).stdout.strip() not in ("", "0"))
    check("battery presence detected correctly", b["hasBattery"] == has)
    if not has:
        return
    design, full, sleeps = battery_truth()
    check("design capacity matches Windows' battery report", b["design"] == design, f"{b['design']} vs {design}")
    check("full charge capacity matches Windows' battery report", b["full"] == full, f"{b['full']} vs {full}")
    check("health % is computed exactly", b["health"] == round(100 * full / design, 1), f"{b['health']} vs {100 * full / design:.1f}")
    got = [(s["hours"], s["drainPercent"]) for s in b["sleeps"]]
    want = [(h, d) for _, h, d in sleeps]
    check("sleeps on battery and their drain match the report", got == want, f"{got[:3]} vs {want[:3]}")
    armed = [l.strip() for l in oem(["powercfg", "/devicequery", "wake_armed"]).splitlines() if l.strip()]
    armed = [a for a in armed if a.upper() not in ("NONE", "AUCUN", "KEINE", "NINGUNO")]
    check("wake-armed devices match powercfg", b["armed"] == armed, f"{b['armed']} vs {armed}")
    raw = subprocess.run(["wevtutil", "qe", "System", "/q:*[System[Provider[@Name='Microsoft-Windows-Power-Troubleshooter'] and EventID=1 "
                          "and TimeCreated[timediff(@SystemTime) <= 1209600000]]]", "/c:30", "/f:xml"], capture_output=True).stdout
    count = raw.count(b"<Event ")
    check("wake events match the event log", len(b["wakes"]) == count, f"{len(b['wakes'])} vs {count}")


# ---------- junk ----------
def walk_size(root, min_age_h=0, pattern=None):
    """Independent re-implementation: files under root, not crossing junctions."""
    total = count = 0
    cutoff = time.time() - min_age_h * 3600
    stack = [root]
    while stack:
        d = stack.pop()
        try:
            entries = list(os.scandir(d))
        except OSError:
            continue
        for e in entries:
            try:
                if e.is_symlink() or (e.is_dir(follow_symlinks=False) and e.stat(follow_symlinks=False).st_file_attributes & 0x400):
                    continue
                if e.is_dir(follow_symlinks=False):
                    if pattern is None:
                        stack.append(e.path)
                elif pattern is None or Path(e.name).match(pattern):
                    st = e.stat(follow_symlinks=False)
                    if min_age_h == 0 or st.st_mtime < cutoff:
                        total += st.st_size
                        count += 1
            except OSError:
                pass
    return total, count


def test_junk():
    before = {c["id"]: c for c in ps.run("junk", {"mode": "scan"})}
    local = os.environ["LOCALAPPDATA"]
    tmp_bytes, tmp_count = walk_size(os.environ["TEMP"], 24)
    thumbs, _ = walk_size(fr"{local}\Microsoft\Windows\Explorer", 0, "thumbcache_*.db")
    dumps, _ = walk_size(fr"{local}\CrashDumps")
    after = {c["id"]: c for c in ps.run("junk", {"mode": "scan"})}
    # Temp folders change while we measure; accept the truth if it sits between two scans (or within 1%).
    def near(cid, truth):
        lo = min(before[cid]["bytes"], after[cid]["bytes"]) * 0.99 - 4096
        hi = max(before[cid]["bytes"], after[cid]["bytes"]) * 1.01 + 4096
        return lo <= truth <= hi
    check("temporary files size matches an independent walk", near("user-temp", tmp_bytes), f"{after['user-temp']['bytes']} vs {tmp_bytes}")
    check("picture previews size matches", near("thumbnails", thumbs), f"{after['thumbnails']['bytes']} vs {thumbs}")
    check("crash dumps size matches", near("crash-dumps", dumps), f"{after['crash-dumps']['bytes']} vs {dumps}")


# ---------- startup ----------
def test_startup():
    items = ps.run("startup", {"mode": "list"})
    truth = {}
    for hive, root, key, approved in [("HKCU", winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", "Run"),
                                      ("HKLM", winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run", "Run"),
                                      ("HKLM", winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Run", "Run32")]:
        try:
            with winreg.OpenKey(root, key, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as k:
                for i in range(winreg.QueryInfoKey(k)[1]):
                    name = winreg.EnumValue(k, i)[0]
                    if name:
                        truth[f"{hive}|{approved}|{name}"] = (root, approved, name)
        except OSError:
            pass
    for hive, root, folder in [("HKCU", winreg.HKEY_CURRENT_USER, Path(os.environ["APPDATA"]) / r"Microsoft\Windows\Start Menu\Programs\Startup"),
                               ("HKLM", winreg.HKEY_LOCAL_MACHINE, Path(os.environ["ProgramData"]) / r"Microsoft\Windows\Start Menu\Programs\StartUp")]:
        if folder.exists():
            for f in folder.iterdir():
                if f.is_file() and f.name.lower() != "desktop.ini":
                    truth[f"{hive}|StartupFolder|{f.name}"] = (root, "StartupFolder", f.name)
    check("startup list has exactly the registry and Startup folder entries", sorted(i["id"] for i in items) == sorted(truth),
          f"{sorted(set(i['id'] for i in items) ^ set(truth))}")
    wrong = []
    for i in items:
        root, approved, name = truth.get(i["id"], (None, None, None))
        if root is None:
            continue
        v = reg_value(root, rf"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\{approved}", name)
        enabled = True if not isinstance(v, bytes) or not v else v[0] % 2 == 0
        if enabled != i["enabled"]:
            wrong.append(i["name"])
    check("on/off state of every startup app matches Task Manager's", not wrong, str(wrong))


# ---------- Windows clean-up ----------
def test_tweaks():
    listed = {t["id"]: t for t in ps.run("tweaks", {"mode": "list"})}
    source = (ROOT / "scripts" / "tweaks.ps1").read_text(encoding="utf-8")
    consts = {"$adv": r"Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced",
              "$cdm": r"Software\Microsoft\Windows\CurrentVersion\ContentDeliveryManager"}
    wrong = []
    for block in re.finditer(r"@\{ id = '([\w-]+)'.*?values = @\((.*?)\) \}", source, re.S):
        tid, body = block.group(1), block.group(2)
        applied = True
        for hive, path, name, value in re.findall(r"\(V '(HKCU|HKLM)' ('[^']+'|\$\w+) '([^']+)' (\d+)\)", body):
            path = consts.get(path, path.strip("'"))
            root = winreg.HKEY_CURRENT_USER if hive == "HKCU" else winreg.HKEY_LOCAL_MACHINE
            v = reg_value(root, path, name, winreg.KEY_WOW64_64KEY)
            if v != int(value):
                applied = False
        if listed[tid]["applied"] != applied:
            wrong.append(tid)
    check("each Windows clean-up item shows the registry's real state", not wrong and len(listed) == 11, str(wrong))


# ---------- pre-installed apps ----------
def test_apps():
    listed = {a["id"] for a in ps.run("apps", {"mode": "list"})}
    known = set(re.findall(r"^\s+'([\w.]+)'\s+= @\(", (ROOT / "scripts" / "apps.ps1").read_text(encoding="utf-8"), re.M))
    names = set(json.loads(subprocess.run(["powershell", "-NoProfile", "-Command",
                                           "@(Get-AppxPackage | Where-Object { -not $_.IsFramework -and -not $_.NonRemovable } | ForEach-Object Name) | ConvertTo-Json -Compress"],
                                          capture_output=True, text=True).stdout))
    check("pre-installed app list is exactly the installed known apps", listed == known & names, f"{sorted(listed ^ (known & names))}")


# ---------- app updates ----------
def test_updates():
    u = ps.run("updates", {"mode": "list"})
    raw = subprocess.run(["winget", "upgrade", "--accept-source-agreements", "--disable-interactivity"], capture_output=True).stdout.decode("utf-8", "replace")
    footer = re.search(r"(\d+) upgrades? available", raw)
    ids_in_raw = all(re.search(rf"\s{re.escape(a['id'])}\s", raw) for a in u["apps"])
    check("every update listed is in winget's own output", ids_in_raw)
    if footer:
        check("number of updates matches winget's count", len(u["apps"]) == int(footer.group(1)), f"{len(u['apps'])} vs {footer.group(1)}")
    for a in u["apps"]:
        line = next((l for l in raw.splitlines() if re.search(rf"\s{re.escape(a['id'])}\s", l)), "")
        if not (a["version"] in line and a["latest"] in line):
            check(f"versions of {a['id']} match winget", False, line.strip())
            return
    check("installed and new versions match winget for every app", True)


# ---------- ad blocking ----------
def test_dns():
    s = ps.run("dns", {"mode": "status"})
    import socket
    try:
        blocked = socket.gethostbyname("doubleclick.net") == "0.0.0.0"
    except OSError:
        blocked = False
    check("ad blocking status matches a real DNS lookup", s["blocking"] == blocked, f"{s['blocking']} vs {blocked}")
    for a in s["adapters"]:
        guid = subprocess.run(["powershell", "-NoProfile", "-Command", f"(Get-NetAdapter -InterfaceIndex {a['index']}).InterfaceGuid"],
                              capture_output=True, text=True).stdout.strip()
        key = rf"SYSTEM\CurrentControlSet\Services\Tcpip\Parameters\Interfaces\{guid}"
        static = reg_value(winreg.HKEY_LOCAL_MACHINE, key, "NameServer") or ""
        dhcp = reg_value(winreg.HKEY_LOCAL_MACHINE, key, "DhcpNameServer") or ""
        truth = [x for x in re.split(r"[,\s]+", static or dhcp) if x]
        v4 = [x for x in a["servers"] if ":" not in x]
        check(f"DNS servers of {a['name']} match the registry", v4 == truth, f"{v4} vs {truth}")
        check(f"static/automatic DNS of {a['name']} detected correctly", a["static"] == bool(static.strip()))


# ---------- health score ----------
def test_score():
    r = subprocess.run(["node", str(ROOT / "tests" / "score.test.mjs")], capture_output=True, text=True)
    for line in r.stdout.splitlines():
        ok, _, name = line.partition(" ")
        check(f"score: {name}", ok == "PASS")
    if r.returncode != 0 and not r.stdout:
        check("score tests ran", False, r.stderr[-300:])


if __name__ == "__main__":
    tests = [t for n, t in sorted(globals().items()) if n.startswith("test_")]
    only = sys.argv[1:]
    for t in tests:
        if not only or any(o in t.__name__ for o in only):
            t()
    print(f"\n{sum(results)}/{len(results)} checks passed")
    sys.exit(0 if all(results) else 1)
