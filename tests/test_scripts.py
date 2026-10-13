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
        check("tweaks list has every tweak", len(listed) == 11 and not listed["start-ads"]["applied"], list(listed))
        res = ps.run("tweaks", {"mode": "apply", "ids": ["start-ads", "telemetry"]}, env=env)
        check("apply succeeds", all(r["ok"] for r in res), res)
        q = reg("query", adv).stdout
        check("values set to off", "Start_IrisRecommendations    REG_DWORD    0x0" in q and "Start_AccountNotifications    REG_DWORD    0x0" in q, q)
        listed = {t["id"]: t for t in ps.run("tweaks", {"mode": "list"}, env=env)}
        check("listed as applied, with undo", listed["start-ads"]["applied"] and listed["start-ads"]["undo"])
        # Applying twice must not overwrite the original backup with the changed values.
        ps.run("tweaks", {"mode": "apply", "ids": ["start-ads"]}, env=env)
        res = ps.run("tweaks", {"mode": "undo", "ids": ["start-ads", "telemetry"]}, env=env)
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


def recycle_bin_items(folder):
    """Items in the Recycle Bin that were deleted from `folder`, read through Explorer: [(name, size, path in the bin)]."""
    import json
    cmd = ("$bin = (New-Object -ComObject Shell.Application).NameSpace(10); "
           "$out = @(foreach ($i in $bin.Items()) { if ($i.ExtendedProperty('System.Recycle.DeletedFrom') -eq $env:HIB_FOLDER) { "
           "[ordered]@{ size = [long]$i.Size; path = $i.Path } } }); "
           "ConvertTo-Json -InputObject $out -Compress")
    r = subprocess.run([str(ps.POWERSHELL), "-NoProfile", "-Command", cmd], capture_output=True,
                       env={**os.environ, "HIB_FOLDER": str(folder)})
    items = json.loads(r.stdout.decode("utf-8", "replace") or "[]")
    if isinstance(items, dict):
        items = [items]
    # Each $R file has a $I twin recording where it came from (version 2: size, time, then the UTF-16 path).
    for i in items:
        info = Path(i["path"]).with_name("$I" + Path(i["path"]).name[2:])
        raw = info.read_bytes()
        length = int.from_bytes(raw[24:28], "little")
        i["original"] = raw[28:28 + 2 * length].decode("utf-16-le").split(chr(0))[0]
        i["name"] = Path(i["original"]).name
    return items


def restore_from_bin(folder):
    """Puts our own test files back from the Recycle Bin (Explorer's Restore), so the bin is left as it was."""
    cmd = ("$bin = (New-Object -ComObject Shell.Application).NameSpace(10); "
           "foreach ($i in @($bin.Items())) { if ($i.ExtendedProperty('System.Recycle.DeletedFrom') -eq $env:HIB_FOLDER) { $i.InvokeVerb('undelete') } }")
    subprocess.run([str(ps.POWERSHELL), "-NoProfile", "-Command", cmd], capture_output=True, env={**os.environ, "HIB_FOLDER": str(folder)})


def test_bigfiles():
    MB = 2**20
    base = Path(os.path.realpath(tempfile.mkdtemp(prefix="hibclean-big-")))  # long names, as the script reports them
    sandbox = base / "downloads"
    outside = base / "outside-precious"
    try:
        (sandbox / "sub").mkdir(parents=True)
        outside.mkdir()
        files = {"movie.mp4": 3 * MB, "sub/backup.vhdx": 5 * MB, "song.flac": 2 * MB, "note.txt": 10_000,
                 "old-setup.exe": 50_000, "old-image.iso": 1 * MB + 5, "new-setup.msi": 40_000, "old-letter.docx": 30_000}
        for name, size in files.items():
            (sandbox / name).write_bytes(b"\0" * size)
        for name in ["old-setup.exe", "old-image.iso", "old-letter.docx"]:
            old(sandbox / name, 45)
        precious = outside / "precious.bin"
        precious.write_bytes(b"\1" * (4 * MB))
        subprocess.run(["cmd", "/c", "mklink", "/J", str(sandbox / "link-out"), str(outside)], capture_output=True, check=True)

        env = {"HIB_TEST_BIGFILES_ROOT": str(sandbox), "HIB_TEST_BIGFILES_MIN": str(MB)}
        scan = ps.run("bigfiles", {"mode": "scan"}, env=env)
        big = [(Path(f["path"]).relative_to(sandbox).as_posix(), f["size"]) for f in scan["big"]]
        check("big files: only files over the size, biggest first, sizes exact",
              big == [("sub/backup.vhdx", 5 * MB), ("movie.mp4", 3 * MB), ("song.flac", 2 * MB), ("old-image.iso", MB + 5)], big)
        check("big files: nothing listed through a junction", all("precious" not in f["path"] for f in scan["big"] + scan["installers"]))
        inst = sorted(f["name"] for f in scan["installers"])
        check("old installers: only .exe/.msi/.iso/.zip older than 30 days", inst == ["old-image.iso", "old-setup.exe"], inst)
        check("big files: dates are the files' own", all(abs(datetime_from(f["modified"]) - (sandbox / Path(f["path"]).relative_to(sandbox)).stat().st_mtime) < 2
                                                          for f in scan["big"]))

        for bad in [os.environ["USERPROFILE"], "C:\\", str(Path(os.environ["TEMP"]).parent)]:
            try:
                ps.run("bigfiles", {"mode": "scan"}, env={"HIB_TEST_BIGFILES_ROOT": bad})
                check(f"big files: refuses {bad} as a test folder", False)
            except RuntimeError as e:
                check(f"big files: refuses {bad} as a test folder", "inside the TEMP" in str(e), str(e))

        # Recycle: only listed files, and only into the Recycle Bin.
        want = [str(sandbox / "movie.mp4"), str(sandbox / "old-setup.exe"), str(sandbox / "link-out" / "precious.bin"),
                str(sandbox / "note.txt"), str(outside / "precious.bin"), "C:\\Windows\\notepad.exe"]
        res = ps.run("bigfiles", {"mode": "recycle", "paths": want}, env=env)
        by = {r["path"]: r for r in res["results"]}
        check("recycle: listed files moved", by[want[0]]["ok"] and by[want[1]]["ok"], res)
        check("recycle: files not in the scan refused", all(not by[p]["ok"] and by[p]["error"] == "not-listed" for p in want[2:]), res)
        check("recycle: reports what it freed", res["freed"] == 3 * MB + 50_000, res["freed"])
        check("recycle: moved files are gone from the folder", not (sandbox / "movie.mp4").exists() and not (sandbox / "old-setup.exe").exists())
        check("recycle: everything else untouched", precious.exists() and (sandbox / "note.txt").exists() and (sandbox / "song.flac").exists()
              and Path("C:\\Windows\\notepad.exe").exists())
        binned = {i["name"]: i for i in recycle_bin_items(sandbox)}
        check("recycle: files are in the Recycle Bin, not deleted for good",
              binned.get("movie.mp4", {}).get("size") == 3 * MB and binned.get("old-setup.exe", {}).get("size") == 50_000
              and binned["movie.mp4"]["original"].lower() == str(sandbox / "movie.mp4").lower(), binned)
        restore_from_bin(sandbox)
        time.sleep(1)
        check("recycle: restoring from the Recycle Bin brings them back", (sandbox / "movie.mp4").exists() and (sandbox / "old-setup.exe").exists())
        try:
            ps.run("bigfiles", {"mode": "recycle", "paths": []}, env=env)
            check("recycle: refuses an empty request", False)
        except RuntimeError:
            check("recycle: refuses an empty request", True)
    finally:
        restore_from_bin(sandbox)
        subprocess.run(["cmd", "/c", "rmdir", str(sandbox / "link-out")], capture_output=True)
        shutil.rmtree(base, ignore_errors=True)


def datetime_from(iso):
    from datetime import datetime
    return datetime.fromisoformat(iso[:26].rstrip("Z") + "+00:00").timestamp()


def test_new_reports():
    """The read-only reports return what the interface expects."""
    sec = ps.run("security", {"mode": "report"})
    ids = [i["id"] for i in sec["items"]]
    check("security report has every check", ids == ["antivirus", "firewall", "updates", "encryption", "secureboot", "tpm", "smartscreen", "uac"], ids)
    check("security states are known words", all(i["state"] in ("ok", "warn", "info", "unknown") for i in sec["items"]))
    check("security settings links are allowed by the app",
          all(i["url"] is None or i["url"].startswith(("ms-settings:", "windowsdefender://")) for i in sec["items"]))
    priv = ps.run("privacy", {"mode": "report"})
    check("privacy report covers camera, microphone and location", [c["id"] for c in priv["caps"]] == ["webcam", "microphone", "location"])
    check("privacy apps have names", all(a["name"] for c in priv["caps"] for a in c["apps"]))
    for name in ["security", "privacy", "bigfiles"]:
        try:
            ps.run(name, {"mode": "bogus"})
            check(f"{name}: unknown mode refused", False)
        except RuntimeError as e:
            check(f"{name}: unknown mode refused", "Unknown mode" in str(e), str(e))


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
