"""End-to-end test of the real app: launches dist/HibCleanPC.exe, connects to its
WebView2 through the debugging port, visits every section, and checks the data
shown came from the scripts. Read-only: it never clicks a button that changes
the PC. Screenshots go to tests/screenshots/.

Run: python tests/test_app.py
"""
import os
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

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


def launch(lang_page=None):
    # HIB_READONLY: the app refuses every action that would change this PC.
    env = {**os.environ, "WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS": f"--remote-debugging-port={PORT}", "HIB_READONLY": "1"}
    return subprocess.Popen([str(EXE)], env=env)


def main():
    proc = launch()
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

            visit("clean", "#cats li", "clean-up list")
            check("clean-up shows a size for temp files", "B" in page.inner_text("#cats li:first-child .row-side"))
            visit("startup", "#body .row, #body .empty", "startup apps")
            visit("windows", "#tweaks .row", "Windows clean-up")
            check("Windows clean-up lists 12 changes", page.locator("#tweaks .row").count() == 12)
            wait(lambda: page.locator("#apps .row, #apps .empty").count() > 0, 60)
            page.screenshot(path=str(SHOTS / "windows.png"))
            visit("battery", ".gauge, .empty", "battery")
            visit("updates", "#list .row, .result, .empty", "app updates")
            visit("adblock", ".choice", "ad blocking")
            check("ad blocking offers 4 choices", page.locator(".choice").count() == 4)
            visit("laptop", "#hw .kv", "used laptop check")
            check("laptop check shows the CPU", "Intel" in page.inner_text("#hw") or "AMD" in page.inner_text("#hw") or "Qualcomm" in page.inner_text("#hw"))
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

            # French and Arabic.
            for lang, word, direction in [("fr", "Nettoyage", "ltr"), ("ar", "التنظيف", "rtl")]:
                page.select_option("#lang", lang)
                page.wait_for_timeout(300)
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
