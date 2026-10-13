"""Captures the README and website screenshots from the real app, read-only.
The serial number is replaced with dots before the laptop check is captured.

Run: python tools/screens.py                 -> assets/screens/*.png
     python tools/screens.py --out <folder>  -> somewhere else (to look before replacing them)
"""
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
OUT = Path(sys.argv[sys.argv.index("--out") + 1]) if "--out" in sys.argv else ROOT / "assets" / "screens"
OUT.mkdir(parents=True, exist_ok=True)
PORT = 9334


# The big files screen shows sample files from a sandbox in TEMP rather than your own files.
# They are sparse: they report their size but take almost no space on the disk.
SAMPLES = [("Windows 11 24H2.iso", 5.6, 120), ("Holiday 2025.mp4", 2.3, 12), ("Game recording.mkv", 1.4, 3),
           ("Project backup.zip", 0.85, 75), ("Podcast raw.wav", 0.64, 20), ("VirtualBox-7.1-Win.exe", 0.11, 200),
           ("SteamSetup.exe", 0.0023, 400)]


def samples():
    root = Path(tempfile.mkdtemp(prefix="hibclean-screens-"))
    for name, gb, days in SAMPLES:
        f = root / name
        f.touch()
        subprocess.run(["fsutil", "sparse", "setflag", str(f)], capture_output=True)
        os.truncate(f, int(gb * 2**30))
        t = time.time() - days * 86400
        os.utime(f, (t, t))
    return root


def main():
    sandbox = samples()
    env = {**os.environ, "WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS": f"--remote-debugging-port={PORT}", "HIB_READONLY": "1",
           "HIB_TEST_BIGFILES_ROOT": str(sandbox)}
    proc = subprocess.Popen([str(ROOT / "dist" / "HibCleanPC.exe")], env=env)
    try:
        with sync_playwright() as p:
            browser = None
            for _ in range(60):
                try:
                    browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{PORT}")
                    break
                except Exception:
                    time.sleep(0.5)
            ctx = browser.contexts[0]
            page = ctx.pages[0] if ctx.pages else ctx.wait_for_event("page")
            page.wait_for_url("https://app.hibclean/**")
            page.set_viewport_size({"width": 1240, "height": 820})

            def shot(name, section, ready, lang="en", full=False, before=None):
                page.evaluate(f"localStorage.setItem('lang', '{lang}')")
                page.goto(f"https://app.hibclean/index.html#{section}")
                page.reload()  # a hash change alone doesn't restart the app in the new language
                page.wait_for_selector(ready, timeout=120000)
                if section == "home":
                    page.wait_for_function("document.querySelector('#score').textContent.trim().match(/^\\d+$/)", timeout=120000)
                    page.wait_for_timeout(1700)
                else:
                    page.wait_for_timeout(800)
                if before:
                    page.evaluate(before)
                page.mouse.move(5, 810)
                page.screenshot(path=str(OUT / f"{name}.png"), full_page=full)
                print(name)

            shot("home", "home", "#fixes .fix, #fixes .all-good")
            shot("home-ar", "home", "#fixes .fix, #fixes .all-good", lang="ar")
            shot("home-fr", "home", "#fixes .fix, #fixes .all-good", lang="fr")
            shot("clean", "clean", "#cats li")
            shot("windows", "windows", "#tweaks .row")
            shot("battery", "battery", ".gauge, .empty")
            shot("adblock", "adblock", ".choice")
            hide_serial = """() => {
              for (const dd of document.querySelectorAll('#hw dd')) {
                if (dd.previousElementSibling && /serial|série|التسلسلي/i.test(dd.previousElementSibling.textContent)) dd.textContent = '••••••••••••';
              }
            }"""
            shot("laptop", "laptop", "#hw .kv", before=hide_serial)
            # New in 1.1. Nothing personal beyond file and app names; no serial numbers on these screens.
            shot("security", "security", "#sec .row")
            shot("security-ar", "security", "#sec .row", lang="ar")
            shot("bigfiles", "bigfiles", "#big-card")
            shot("privacy", "privacy", "#priv-summary")
            shot("privacy-fr", "privacy", "#priv-summary", lang="fr")
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except subprocess.TimeoutExpired:
            proc.kill()
        shutil.rmtree(sandbox, ignore_errors=True)


if __name__ == "__main__":
    main()
