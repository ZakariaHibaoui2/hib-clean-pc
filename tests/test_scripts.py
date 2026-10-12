"""Tests for the PowerShell scripts that don't need admin rights.

Everything that would change this PC runs in a throwaway sandbox (a fake TEMP
folder, a fake registry key under HKCU\\Software\\HibCleanPCTest) and is
removed afterwards.

Run: python tests/test_scripts.py
"""
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import ps

results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(("PASS " if ok else "FAIL ") + name + (f"  ({detail})" if detail and not ok else ""))


def old(path, days=3):
    t = time.time() - days * 86400
    os.utime(path, (t, t))


def test_junk():
    scan = ps.run("junk", {"mode": "scan"})
    ids = [c["id"] for c in scan]
    check("junk scan lists every category", set(ids) >= {"user-temp", "browser", "thumbnails", "crash-dumps", "win-temp",
                                                      "update-cache", "error-reports", "delivery", "recycle", "windows-old"}, ids)
    check("junk scan sizes are numbers", all(isinstance(c["bytes"], int) and c["bytes"] >= 0 for c in scan))

    base = Path(tempfile.mkdtemp(prefix="hibclean-"))
    try:
        sandbox = base / "sandbox-temp-folder"
        outside = base / "outside-precious"
        (sandbox / "nested" / "deeper").mkdir(parents=True)
        outside.mkdir()
        precious = outside / "precious.txt"
        precious.write_text("keep me")
        old(precious)
        for p in [sandbox / "old.tmp", sandbox / "nested" / "old2.log", sandbox / "nested" / "deeper" / "old3.bin"]:
            p.write_bytes(b"x" * 1000)
            old(p)
        new = sandbox / "fresh.tmp"
        new.write_bytes(b"y" * 500)
        ro = sandbox / "readonly.tmp"
        ro.write_bytes(b"z" * 200)
        old(ro)
        os.chmod(ro, 0o444)
        subprocess.run(["cmd", "/c", "mklink", "/J", str(sandbox / "link-out"), str(outside)], capture_output=True, check=True)

        env = {"TEMP": str(sandbox), "TMP": str(sandbox)}
        scan = {c["id"]: c for c in ps.run("junk", {"mode": "scan"}, env=env)}
        check("sandbox scan counts only old files, not through the junction",
              scan["user-temp"]["files"] == 4 and scan["user-temp"]["bytes"] == 3200, scan["user-temp"])
        res = ps.run("junk", {"mode": "clean", "ids": ["user-temp"]}, env=env)
        check("clean reports what it freed", res["freed"] == 3200 and res["files"] == 4, res)
        check("old files deleted", not (sandbox / "old.tmp").exists() and not (sandbox / "nested" / "deeper" / "old3.bin").exists())
        check("read-only old file deleted", not ro.exists())
        check("file from the last 24 hours kept", new.exists())
        check("file behind a junction untouched", precious.exists() and precious.read_text() == "keep me")
        check("emptied folders removed, root kept", not (sandbox / "nested").exists() and sandbox.exists())
        check("only the asked category was cleaned", [r["id"] for r in res["results"]] == ["user-temp"])

        # Read-only scan: the same guard as clean, without any risk if it failed.
        for bad in ["C:\\", os.environ["USERPROFILE"], os.environ["LOCALAPPDATA"], os.environ["SystemRoot"]]:
            refused = {c["id"]: c for c in ps.run("junk", {"mode": "scan"}, env={"TEMP": bad, "TMP": bad})}
            check(f"refuses {bad} as a temp folder", refused["user-temp"]["files"] == 0, refused["user-temp"])
    finally:
        subprocess.run(["cmd", "/c", "rmdir", str(base / "sandbox-temp-folder" / "link-out")], capture_output=True)
        shutil.rmtree(base, ignore_errors=True)


RUN_KEY = r"HKCU\Software\Microsoft\Windows\CurrentVersion\Run"
APPROVED_KEY = r"HKCU\Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run"


def reg(*args):
    return subprocess.run(["reg", *args], capture_output=True, text=True)


def test_startup():
    items = ps.run("startup", {"mode": "list"})
    check("startup list returns items with ids", isinstance(items, list) and all("id" in i and "enabled" in i for i in items),
          str(items)[:200])
    name = "HibCleanPCTest"
    reg("add", RUN_KEY, "/v", name, "/t", "REG_SZ", "/d", r'"C:\Windows\System32\cmd.exe" /c exit', "/f")
    try:
        items = {i["id"]: i for i in ps.run("startup", {"mode": "list"})}
        item_id = f"HKCU|Run|{name}"
        check("test entry listed and on", item_id in items and items[item_id]["enabled"] is True, list(items)[:5])
        check("test entry has publisher and icon", items.get(item_id, {}).get("publisher") == "Microsoft Corporation"
              and (items.get(item_id, {}).get("icon") or "").startswith("data:image/png"))
        off = ps.run("startup", {"mode": "set", "id": item_id, "enabled": False})
        check("turning off works", off["enabled"] is False)
        q = reg("query", APPROVED_KEY, "/v", name).stdout
        check("stored like Task Manager (03...)", "REG_BINARY    03000000" in q, q.strip())
        on = ps.run("startup", {"mode": "set", "id": item_id, "enabled": True})
        check("turning back on works", on["enabled"] is True)
        try:
            ps.run("startup", {"mode": "set", "id": "HKCU|Run|NotARealEntry123", "enabled": False})
            check("refuses an unknown entry", False)
        except RuntimeError as e:
            check("refuses an unknown entry", "no longer" in str(e), str(e))
        try:
            ps.run("startup", {"mode": "set", "id": r"HKCU|..\Evil|x", "enabled": False})
            check("refuses a made-up key", False)
        except RuntimeError as e:
            check("refuses a made-up key", "Unknown startup item" in str(e), str(e))
    finally:
        reg("delete", RUN_KEY, "/v", name, "/f")
        reg("delete", APPROVED_KEY, "/v", name, "/f")
    check("test entry removed", "HibCleanPCTest" not in reg("query", RUN_KEY).stdout)


TEST_ROOT = r"Software\HibCleanPCTest"


def test_tweaks():
    env = {"HIB_TEST_REG_ROOT": TEST_ROOT}
    base = "HKCU\\" + TEST_ROOT
    adv = base + r"\Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced"
    state = Path(os.environ["LOCALAPPDATA"]) / "Hib Clean PC" / "tweaks-backup-test.json"
    real_state = Path(os.environ["LOCALAPPDATA"]) / "Hib Clean PC" / "tweaks-backup.json"
    real_before = real_state.read_bytes() if real_state.exists() else None
    reg("delete", base, "/f")
    state.unlink(missing_ok=True)
    try:
        # One value exists already with a different setting, one doesn't exist.
        reg("add", adv, "/v", "Start_IrisRecommendations", "/t", "REG_DWORD", "/d", "1", "/f")
        listed = {t["id"]: t for t in ps.run("tweaks", {"mode": "list"}, env=env)}
        check("tweaks list has every tweak", len(listed) == 12 and not listed["start-ads"]["applied"], list(listed))
        res = ps.run("tweaks", {"mode": "apply", "ids": ["start-ads", "widgets"]}, env=env)
        check("apply succeeds", all(r["ok"] for r in res), res)
        q = reg("query", adv).stdout
        check("values set to off", "Start_IrisRecommendations    REG_DWORD    0x0" in q and "Start_AccountNotifications    REG_DWORD    0x0" in q, q)
        listed = {t["id"]: t for t in ps.run("tweaks", {"mode": "list"}, env=env)}
        check("listed as applied, with undo", listed["start-ads"]["applied"] and listed["start-ads"]["undo"])
        # Applying twice must not overwrite the original backup with the changed values.
        ps.run("tweaks", {"mode": "apply", "ids": ["start-ads"]}, env=env)
        res = ps.run("tweaks", {"mode": "undo", "ids": ["start-ads", "widgets"]}, env=env)
        check("undo succeeds", all(r["ok"] for r in res), res)
        q = reg("query", adv).stdout
        check("existing value restored to its old setting", "Start_IrisRecommendations    REG_DWORD    0x1" in q, q)
        check("value that didn't exist is removed again", "Start_AccountNotifications" not in q, q)
        listed = {t["id"]: t for t in ps.run("tweaks", {"mode": "list"}, env=env)}
        check("no undo left after undo", not listed["start-ads"]["undo"])
        res = ps.run("tweaks", {"mode": "undo", "ids": ["tips"]}, env=env)
        check("undo without a backup is refused", res[0]["error"] == "nothing-to-undo", res)
        try:
            ps.run("tweaks", {"mode": "list"}, env={"HIB_TEST_REG_ROOT": r"Software\Microsoft"})
            check("test root limited to the test key", False)
        except RuntimeError:
            check("test root limited to the test key", True)
    finally:
        reg("delete", base, "/f")
        state.unlink(missing_ok=True)
    real_after = real_state.read_bytes() if real_state.exists() else None
    check("real backup file untouched by tests", real_before == real_after)


def test_outfile():
    """Elevated runs can't pipe stdout, so scripts write results (and errors) to -OutFile."""
    import base64, json
    out = Path(tempfile.mkdtemp(prefix="hibclean-out-")) / "result.json"
    try:
        for name, args, ok in [("junk", {"mode": "scan"}, True), ("dns", {"mode": "set", "provider": "evil"}, False),
                               ("tweaks", {"mode": "list"}, True), ("restore", {"mode": "bogus"}, False)]:
            out.unlink(missing_ok=True)
            payload = base64.b64encode(json.dumps(args).encode()).decode()
            r = subprocess.run([str(ps.POWERSHELL), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                                "-File", str(ps.SCRIPTS / f"{name}.ps1"), "-Payload", payload, "-OutFile", str(out)],
                               capture_output=True)
            text = out.read_text(encoding="utf-8") if out.exists() else ""
            if ok:
                check(f"{name}: result written to the out file", r.returncode == 0 and isinstance(json.loads(text), list) and not r.stdout.strip(), text[:80])
            else:
                check(f"{name}: error written to the out file", r.returncode == 1 and text and not text.startswith("[") , text[:80])
    finally:
        shutil.rmtree(out.parent, ignore_errors=True)


if __name__ == "__main__":
    tests = [t for n, t in sorted(globals().items()) if n.startswith("test_")]
    only = sys.argv[1:]
    for t in tests:
        if not only or any(o in t.__name__ for o in only):
            t()
    print(f"\n{sum(results)}/{len(results)} checks passed")
    sys.exit(0 if all(results) else 1)
