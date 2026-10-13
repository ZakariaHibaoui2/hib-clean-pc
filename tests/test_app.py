"""End-to-end test of the real app: launches dist/HibCleanPC.exe, connects to its
WebView2 through the debugging port, visits every section, and checks the data
shown came from the scripts. Read-only: it never clicks a button that changes
the PC. Screenshots go to tests/screenshots/.

Run: python tests/test_app.py
"""
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

import ps

ROOT = Path(__file__).resolve().parent.parent
EXE = ROOT / "dist" / "HibCleanPC.exe"
SHOTS = ROOT / "tests" / "screenshots"
SHOTS.mkdir(parents=True, exist_ok=True)
PORT = 9333

results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(("PASS " if ok else "FAIL ") + name + (f"  ({detail})" if detail and not ok else ""))


SLEEPER = {"page": None}


def wait(fn, timeout=60):
    """Polls fn. Sleeps through Playwright once a page exists, so its events keep flowing."""
    end = time.time() + timeout
    while time.time() < end:
        try:
            v = fn()
            if v:
                return v
        except Exception:
            pass
        if SLEEPER["page"]:
            SLEEPER["page"].wait_for_timeout(300)
        else:
            time.sleep(0.3)
    return None


def launch(extra=None):
    # HIB_READONLY: the app refuses every action that would change this PC.
    env = {**os.environ, "WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS": f"--remote-debugging-port={PORT}", "HIB_READONLY": "1", **(extra or {})}
    return subprocess.Popen([str(EXE)], env=env)


def big_sandbox():
    """Files for the big files screen, in TEMP, so the test never shows or touches your own files."""
    root = Path(os.path.realpath(tempfile.mkdtemp(prefix="hibclean-app-")))
    for name, mb, days in [("film.mkv", 6, 2), ("backup.zip", 4, 90), ("setup.exe", 0.2, 60), ("notes.txt", 0.01, 60)]:
        f = root / name
        f.write_bytes(bytes(int(mb * 2**20)))
        t = time.time() - days * 86400
        os.utime(f, (t, t))
    return root, {"HIB_TEST_BIGFILES_ROOT": str(root), "HIB_TEST_BIGFILES_MIN": str(2**20)}


def main():
    sandbox, big_env = big_sandbox()
    proc = launch(big_env)
    errors = []
    try:
        with sync_playwright() as p:
            browser = wait(lambda: p.chromium.connect_over_cdp(f"http://127.0.0.1:{PORT}"), 40)
            check("app starts and its window opens", browser is not None)
            if not browser:
                return
            ctx = browser.contexts[0]
            page = ctx.pages[0] if ctx.pages else ctx.wait_for_event("page", timeout=30000)
            SLEEPER["page"] = page
            try:
                page.wait_for_url("https://app.hibclean/**", timeout=30000)
                page.wait_for_selector("#nav a", timeout=30000)
                loaded = True
            except Exception:
                loaded = False
            check("interface loads from the app", loaded, page.url)
            if not loaded:
                return
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
            page.on("requestfailed", lambda r: errors.append(f"failed: {r.url[:100]}") if not r.url.startswith("data:") else None)
            page.on("response", lambda r: errors.append(f"{r.status}: {r.url[:100]}") if r.status >= 400 else None)
            page.set_viewport_size({"width": 1240, "height": 820})
            page.evaluate("localStorage.setItem('lang', 'en')")
            page.reload()
            page.wait_for_selector("#nav a")

            # Home: the score appears once every scan has finished.
            score = wait(lambda: page.inner_text("#score") if page.inner_text("#score").strip().isdigit() else None, 120)
            check("home shows a health score", score is not None and 0 <= int(score) <= 100, str(score))
            page.wait_for_timeout(1600)
            fixes = page.locator("#fixes li").count()
            check("home lists fixes or says all good", fixes >= 1)
            check("home shows tiles", page.locator(".tile").count() >= 4, str(page.locator(".tile").count()))
            page.screenshot(path=str(SHOTS / "home.png"))

            def visit(section, ready, name):
                page.click(f'#nav a[href="#{section}"]')
                ok = wait(lambda: page.locator(ready).count() > 0, 120)
                check(f"{name} loads", bool(ok))
                page.wait_for_timeout(500)
                page.screenshot(path=str(SHOTS / f"{section}.png"))

            # The screen shows exactly what the scripts measured.
            truth = {"battery": ps.run("battery", {"mode": "report"}), "startup": ps.run("startup", {"mode": "list"}),
                     "updates": ps.run("updates", {"mode": "list"}), "tweaks": ps.run("tweaks", {"mode": "list"}),
                     "laptop": ps.run("laptop"), "security": ps.run("security", {"mode": "report"}),
                     "privacy": ps.run("privacy", {"mode": "report"}), "bigfiles": ps.run("bigfiles", {"mode": "scan"}, env=big_env)}
            tiles = page.inner_text("#tiles")
            if truth["battery"]["hasBattery"]:
                check("home shows the real battery health", f"{round(truth['battery']['health'])}%" in tiles.replace(",", "."), tiles)
            check("home shows the real number of app updates", str(len(truth["updates"]["apps"])) in tiles, tiles)
            badge = page.inner_text('[data-badge="updates"]') if page.locator('[data-badge="updates"]:not([hidden])').count() else "0"
            check("sidebar badge shows the real number of updates", badge == str(len(truth["updates"]["apps"])), badge)
            showing = sum(1 for x in truth["tweaks"] if not x["applied"])
            wbadge = page.inner_text('[data-badge="windows"]') if page.locator('[data-badge="windows"]:not([hidden])').count() else "0"
            check("sidebar badge shows the real number of Windows ads left", wbadge == str(showing), wbadge)

            visit("clean", "#cats li", "clean-up list")
            check("clean-up shows a size for temp files", "B" in page.inner_text("#cats li:first-child .row-side"))
            visit("startup", "#body .row, #body .empty", "startup apps")
            check("startup screen lists every startup app", page.locator("#body .row").count() == len(truth["startup"]))
            on = sum(1 for i in truth["startup"] if i["enabled"])
            check("startup switches match the real on/off states",
                  page.locator('#body .switch[aria-checked="true"]').count() == on)
            visit("windows", "#tweaks .row", "Windows clean-up")
            check("Windows clean-up lists 11 changes", page.locator("#tweaks .row").count() == 11)
            check("items shown as removed match the registry", page.locator("#tweaks .chip.ok").count() == 11 - showing)
            wait(lambda: page.locator("#apps .row, #apps .empty").count() > 0, 60)
            page.screenshot(path=str(SHOTS / "windows.png"))
            visit("battery", ".gauge, .empty", "battery")
            if truth["battery"]["hasBattery"]:
                want = str(round(truth["battery"]["health"]))
                settled = wait(lambda: page.inner_text("#bat-orb .score") == want, 10)
                check("battery orb settles on the real health", bool(settled), page.inner_text("#bat-orb .score"))
                check("battery screen lists every sleep on battery", page.locator(".card").first.locator(".row").count() == len(truth["battery"]["sleeps"]))
            visit("updates", "#list .row, .result, .empty", "app updates")
            check("update list matches winget", page.locator("#list .row").count() == len(truth["updates"]["apps"]))
            visit("adblock", ".choice", "ad blocking")
            check("ad blocking offers 4 choices", page.locator(".choice").count() == 4)
            # Security check: one row per check, each in the state the script read.
            visit("security", "#sec .row", "security check")
            order = ["antivirus", "firewall", "updates", "encryption", "secureboot", "tpm", "smartscreen", "uac"]
            want = [(i["id"], i["state"]) for i in sorted(truth["security"]["items"], key=lambda i: order.index(i["id"]))]
            got = [tuple(x) for x in page.eval_on_selector_all("#sec .row", "els => els.map((e) => [e.dataset.id, e.dataset.state])")]
            check("security screen shows every check in the state the script read", got == want, f"{got} vs {want}")
            warn = sum(1 for i in truth["security"]["items"] if i["state"] == "warn")
            check("security summary matches", ("warn" in page.get_attribute("#sec-summary", "class")) == (warn > 0))
            links = sum(1 for i in truth["security"]["items"] if i["url"] and i["state"] != "info")
            check("security screen has a settings button for each check", page.locator("#sec [data-url]").count() == links)
            sbadge = page.inner_text('[data-badge="security"]') if page.locator('[data-badge="security"]:not([hidden])').count() else ""
            check("sidebar badge shows the number of security warnings", sbadge == (str(warn) if warn else ""), sbadge)

            # Privacy: the same apps and states as the script.
            visit("privacy", "#priv-summary", "privacy")
            for c in truth["privacy"]["caps"]:
                names = page.eval_on_selector_all(f"#cap-{c['id']} .row b", "els => els.map((e) => e.textContent)")
                check(f"privacy: {c['id']} lists the same apps", names == [a["name"] for a in c["apps"]],
                      f"{names[:3]} vs {[a['name'] for a in c['apps']][:3]}")
                check(f"privacy: {c['id']} access shown {'on' if c['on'] else 'off'}",
                      page.locator(f"#cap-{c['id']} .chip.{'ok' if c['on'] else 'bad'}").count() == 1)
            live = sum(1 for c in truth["privacy"]["caps"] for a in c["apps"] if a["inUse"])
            check("privacy: apps in use now are highlighted", page.locator(".live-row").count() == live)

            # Big files (from a sandbox): the same files, and moving them is refused in test mode.
            visit("bigfiles", "#big-card", "big files")
            bf = truth["bigfiles"]
            shown = page.eval_on_selector_all("#big .row b[title]", "els => els.map((e) => e.textContent)")
            check("big files screen lists the same big files", shown == [f["name"] for f in bf["big"]], shown)
            shown = page.eval_on_selector_all("#inst .row b[title]", "els => els.map((e) => e.textContent)")
            check("big files screen lists the same old installers", shown == [f["name"] for f in bf["installers"]], shown)
            check("big files has a Show in folder button per file", page.locator("[data-reveal]").count() == len(bf["big"]) + len(bf["installers"]))
            page.locator("#big .row input").first.check()
            page.click("#bin")
            check("moving to the Recycle Bin asks for a second click", "again" in page.inner_text("#bin").lower(), page.inner_text("#bin"))
            page.click("#bin")
            told = wait(lambda: "read-only" in page.inner_text("#toast"), 30)
            check("test mode refuses to move files", bool(told) and (sandbox / "film.mkv").exists(), page.inner_text("#toast"))

            visit("laptop", "#hw .kv", "used laptop check")
            check("laptop check shows the real CPU", truth["laptop"]["cpu"]["name"] in page.inner_text("#hw"))
            check("laptop check shows the real BIOS version", truth["laptop"]["bios"]["version"] in page.inner_text("#hw"))
            check("laptop check has 5 tests", page.locator(".test-card").count() == 5)

            # Keyboard test: pressing keys lights them up.
            page.click('[data-start="keyboard"]')
            page.keyboard.press("KeyA")
            page.keyboard.press("Space")
            check("keyboard test lights pressed keys", page.locator(".key.hit").count() == 2)
            page.click('[data-pass="keyboard"]')
            check("marking a test works", "pass" in page.get_attribute("#test-keyboard", "class"))
            page.screenshot(path=str(SHOTS / "laptop-tested.png"), full_page=True)

            # PDF report: made through the app, saved to Documents.
            page.click("#pdf")
            saved = wait(lambda: page.locator("#reveal").count() > 0, 30)
            check("PDF report is saved", bool(saved))

            # Read-only guard: a clean request is refused while testing.
            refused = page.evaluate("""() => new Promise((ok) => {
              const id = 99001;
              const on = (e) => { if (e.data && e.data.id === id) { window.chrome.webview.removeEventListener('message', on); ok(e.data); } };
              window.chrome.webview.addEventListener('message', on);
              window.chrome.webview.postMessage({ id, cmd: 'junk', args: { mode: 'clean', ids: ['user-temp'] } });
            })""")
            check("test mode refuses changes to the PC", refused.get("ok") is False and "read-only" in refused.get("error", ""), str(refused))
            refused = page.evaluate("""(path) => new Promise((ok) => {
              const id = 99002;
              const on = (e) => { if (e.data && e.data.id === id) { window.chrome.webview.removeEventListener('message', on); ok(e.data); } };
              window.chrome.webview.addEventListener('message', on);
              window.chrome.webview.postMessage({ id, cmd: 'bigfiles', args: { mode: 'recycle', paths: [path] } });
            })""", str(sandbox / "backup.zip"))
            check("test mode refuses to recycle files", refused.get("ok") is False and "read-only" in refused.get("error", "")
                  and (sandbox / "backup.zip").exists(), str(refused))

            # French and Arabic.
            for lang, word, direction in [("fr", "Nettoyage", "ltr"), ("ar", "التنظيف", "rtl")]:
                page.select_option("#lang", lang)
                page.wait_for_timeout(300)
                for section, ready in [("security", "#sec .row"), ("privacy", "#priv-summary"), ("bigfiles", "#big-card")]:
                    page.click(f'#nav a[href="#{section}"]')
                    check(f"{section} screen in {lang}", bool(wait(lambda: page.locator(ready).count() > 0, 60)))
                    page.wait_for_timeout(400)
                    page.screenshot(path=str(SHOTS / f"{section}-{lang}.png"))
                check(f"interface in {lang}", word in page.inner_text("#nav") and page.get_attribute("html", "dir") == direction)
                page.click('#nav a[href="#home"]')
                wait(lambda: page.inner_text("#score").strip().isdigit(), 120)
                page.wait_for_timeout(1500)
                page.screenshot(path=str(SHOTS / f"home-{lang}.png"))
            page.select_option("#lang", "en")
            check("no JavaScript errors", not errors, "; ".join(errors)[:300])
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except subprocess.TimeoutExpired:
            proc.kill()
        shutil.rmtree(sandbox, ignore_errors=True)
    docs = Path(subprocess.run(["powershell", "-NoProfile", "-Command", "[Environment]::GetFolderPath('MyDocuments')"],
                               capture_output=True, text=True).stdout.strip())
    pdfs = sorted(docs.glob("Laptop check*.pdf"), key=lambda f: f.stat().st_mtime)
    if pdfs and time.time() - pdfs[-1].stat().st_mtime < 300:
        check("PDF file is a real PDF", pdfs[-1].read_bytes()[:4] == b"%PDF", pdfs[-1].name)
        (SHOTS / "report.pdf").write_bytes(pdfs[-1].read_bytes())
        pdfs[-1].unlink()
    else:
        check("PDF file is a real PDF", False, "not found in Documents")
    print(f"\n{sum(results)}/{len(results)} checks passed")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
