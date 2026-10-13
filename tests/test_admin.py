"""Tests the features that need administrator rights, for real, and puts every
change back exactly as it was:

  - ad blocking: switch DNS to AdGuard, check ads are blocked, switch back to
    Automatic and check the original DNS settings are restored
  - diagnostic data: apply and undo, check the registry is exactly
    as before (skipped if you already applied them yourself)
  - devices that wake the PC: turn one off, then on again
  - a restore point
  - measuring Windows' own temp folders, and reading SSD wear

It asks Windows for permission once (click Yes). Nothing is deleted.

Run: python tests/test_admin.py
"""
import ctypes
import os
import subprocess
import sys
import tempfile
import time
import winreg
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import ps  # noqa: E402

results = []
lines = []


def check(name, ok, detail=""):
    results.append(ok)
    line = ("PASS " if ok else "FAIL ") + name + (f"  ({detail})" if detail and not ok else "")
    lines.append(line)
    print(line, flush=True)


def reg(path, name):
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as k:
            return winreg.QueryValueEx(k, name)
    except OSError:
        return None


def oem(cmd):
    cp = ctypes.windll.kernel32.GetConsoleOutputCP() or ctypes.windll.kernel32.GetOEMCP()
    return subprocess.run(cmd, capture_output=True).stdout.decode(f"cp{cp}", "replace")


def run_tests():
    # ---- DNS round trip ----
    before = ps.run("dns", {"mode": "status"})
    snap = {a["index"]: (a["servers"], a["static"]) for a in before["adapters"]}
    try:
        on = ps.run("dns", {"mode": "set", "provider": "adguard"})
        check("ad blocking: DNS switched to AdGuard on every adapter", on["provider"] == "adguard", str(on["provider"]))
        time.sleep(1.5)
        on = ps.run("dns", {"mode": "status"})
        check("ad blocking: ad servers are really blocked", on["blocking"] is True)
    finally:
        back = ps.run("dns", {"mode": "set", "provider": "auto"})
    after = {a["index"]: (a["servers"], a["static"]) for a in back["adapters"]}
    check("ad blocking: Automatic restores the exact original DNS", after == snap, f"{after} vs {snap}")
    check("ad blocking: no leftover undo file", not (Path(os.environ["LOCALAPPDATA"]) / "Hib Clean PC" / "dns-backup.json").exists())

    # ---- HKLM tweaks round trip ----
    keys = {"telemetry": (r"SOFTWARE\Policies\Microsoft\Windows\DataCollection", "AllowTelemetry")}
    listed = {t["id"]: t for t in ps.run("tweaks", {"mode": "list"})}
    for tid, (path, name) in keys.items():
        if listed[tid]["applied"] or listed[tid]["undo"]:
            check(f"{tid}: skipped, you already changed it yourself", True)
            continue
        original = reg(path, name)
        res = ps.run("tweaks", {"mode": "apply", "ids": [tid]})
        check(f"{tid}: applied", res[0]["ok"] and reg(path, name) == (0, winreg.REG_DWORD), str(res))
        res = ps.run("tweaks", {"mode": "undo", "ids": [tid]})
        check(f"{tid}: undo puts the registry back exactly", res[0]["ok"] and reg(path, name) == original, f"{reg(path, name)} vs {original}")

    # ---- wake devices round trip ----
    armed = [l.strip() for l in oem(["powercfg", "/devicequery", "wake_armed"]).splitlines() if l.strip()]
    armed = [a for a in armed if a.upper() not in ("NONE", "AUCUN", "KEINE", "NINGUNO")]
    if armed:
        device = armed[0]
        off = ps.run("battery", {"mode": "wake", "device": device, "allow": False})
        check("wake: a device can be stopped from waking the PC", off["allowed"] is False, str(off))
        on = ps.run("battery", {"mode": "wake", "device": device, "allow": True})
        check("wake: and allowed again", on["allowed"] is True, str(on))
        now = [l.strip() for l in oem(["powercfg", "/devicequery", "wake_armed"]).splitlines() if l.strip()]
        check("wake: device list is back to how it was", sorted(now) == sorted(armed))
    else:
        check("wake: no devices can wake this PC (nothing to test)", True)

    # ---- restore point ----
    rp = ps.run("restore", {"mode": "create"})
    # 'off' means System Protection is disabled on this PC; the app reports it instead of failing.
    check("restore point: created, or Windows correctly says it can't (one from the last 24 hours, or protection off)",
          rp["created"] or rp["reason"] in ("recent", "off"), str(rp))

    # ---- admin-only measurements ----
    scan = {c["id"]: c for c in ps.run("junk", {"mode": "scan"})}
    check("Windows' own temp folders can be measured with permission",
          all(scan[i]["readable"] for i in ("win-temp", "update-cache", "error-reports", "delivery")))
    info = ps.run("laptop")
    check("SSD details read with permission", info["admin"] is True)
    nvme = [d for d in info["disks"] if d["bus"] == "NVMe"]
    if nvme:
        check("SSD wear or power-on hours available", any(d["wear"] is not None or d["powerOnHours"] is not None for d in nvme), str(nvme))


def main():
    out = Path(sys.argv[sys.argv.index("--out") + 1]) if "--out" in sys.argv else None
    is_admin = ctypes.windll.shell32.IsUserAnAdmin()
    if not is_admin and out is None:
        out = Path(tempfile.mkdtemp(prefix="hib-admin-")) / "result.txt"
        # Created here, so it keeps this user's permissions when the elevated run writes into it.
        out.write_text("", encoding="utf-8")
        print("Windows will ask for permission. Click Yes.", flush=True)
        r = ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, f'"{__file__}" --out "{out}"', str(HERE), 0)
        if r <= 32:
            print("Permission was not given; nothing was changed.")
            return 1
        text = "no result (timed out)"
        for _ in range(900):
            time.sleep(1)
            try:
                current = out.read_text(encoding="utf-8")
            except OSError:
                continue  # still being written
            if current.rstrip().endswith("DONE"):
                text = current
                break
        print(text.replace("DONE", "").rstrip())
        return 0 if "FAIL" not in text and "DONE" in text else 1
    try:
        run_tests()
    except Exception as e:  # report instead of dying silently in the elevated window
        check("admin tests ran to the end", False, repr(e)[:300])
    summary = f"\n{sum(results)}/{len(results)} checks passed"
    print(summary)
    if out:
        with open(out, "r+", encoding="utf-8") as f:  # write into the existing file to keep its permissions
            f.truncate(0)
            f.write("\n".join(lines) + summary + "\nDONE\n")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
