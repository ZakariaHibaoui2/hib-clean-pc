"""Records the animated README demo from the real app, read-only:
the health orb filling, a tilt with the pointer, then a tour of the screens.
The laptop check (which shows the serial number) is never recorded.

Needs ffmpeg on PATH.  Run: python tools/demo.py   -> assets/demo.webp
"""
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets" / "demo.webp"
PORT = 9335
W, H = 1240, 820


def main():
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise SystemExit("ffmpeg is needed: winget install Gyan.FFmpeg")
    frames = Path(tempfile.mkdtemp(prefix="hib-demo-"))
    env = {**os.environ, "WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS": f"--remote-debugging-port={PORT}", "HIB_READONLY": "1",
           "HIB_WEBVIEW_DIR": tempfile.mkdtemp(prefix="hib-demo-wv-")}
    proc = subprocess.Popen([str(ROOT / "dist" / "HibCleanPC.exe")], env=env)
    stamps = []
    try:
        with sync_playwright() as p:
            browser = None
            for _ in range(120):
                try:
                    browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{PORT}")
                    break
                except Exception as e:
                    error = e
                    time.sleep(0.5)
            if browser is None:
                raise SystemExit(f"could not reach the app: {error}")
            ctx = browser.contexts[0]
            page = ctx.pages[0] if ctx.pages else ctx.wait_for_event("page")
            page.wait_for_url("https://app.hibclean/**")
            page.set_viewport_size({"width": W, "height": H})
            page.evaluate("localStorage.setItem('lang', 'en')")
            # Warm up once so every scan is cached, then restart on Home to film the orb filling.
            page.goto("https://app.hibclean/index.html#home")
            page.reload()
            page.wait_for_selector("#fixes .fix, #fixes .all-good", timeout=120000)

            def grab(seconds, move=None):
                end = time.perf_counter() + seconds
                while time.perf_counter() < end:
                    if move:
                        move(1 - (end - time.perf_counter()) / seconds)
                    path = frames / f"{len(stamps):04d}.png"
                    page.screenshot(path=str(path))
                    stamps.append(time.perf_counter())

            def go(section, ready, seconds=2.6):
                item = page.locator(f'a[href="#{section}"]').first
                box = item.bounding_box()
                if box:
                    page.mouse.move(box["x"] + 40, box["y"] + box["height"] / 2, steps=8)
                    item.click()
                else:
                    page.evaluate(f"location.hash = '#{section}'")
                page.wait_for_selector(ready, timeout=60000)
                grab(seconds)

            page.mouse.move(W - 10, H - 10)
            page.evaluate("location.hash = '#clean'")
            page.wait_for_selector("#cats li", timeout=60000)
            page.evaluate("location.hash = '#home'")
            page.wait_for_selector("#gauge", timeout=60000)
            grab(3.2)  # the orb fills to the score
            orb = page.locator("#gauge").bounding_box()
            cx, cy = orb["x"] + orb["width"] / 2, orb["y"] + orb["height"] / 2
            import math
            grab(3.0, lambda t: page.mouse.move(cx + math.cos(t * 6.28) * 260, cy + math.sin(t * 6.28) * 160))
            go("clean", "#cats li")
            go("windows", "#tweaks .row")
            go("battery", ".gauge, .empty", 3.0)
            go("adblock", ".choice")
            go("home", "#fixes .fix, #fixes .all-good", 2.4)
    finally:
        proc.terminate()

    # Each frame lasts until the next one was taken, so the GIF plays at real speed.
    listing = frames / "list.txt"
    with open(listing, "w", encoding="utf-8") as f:
        for i in range(len(stamps)):
            dur = (stamps[i + 1] - stamps[i]) if i + 1 < len(stamps) else 1.5
            f.write(f"file '{(frames / f'{i:04d}.png').as_posix()}'\nduration {dur:.3f}\n")
        f.write(f"file '{(frames / f'{len(stamps) - 1:04d}.png').as_posix()}'\n")
    # Animated WebP: a fraction of a GIF's size for the moving water, and GitHub plays it.
    subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(listing),
                    "-vf", "fps=15,scale=960:-1:flags=lanczos", "-c:v", "libwebp_anim", "-quality", "72",
                    "-compression_level", "6", "-loop", "0", str(OUT)], check=True)
    shutil.rmtree(frames, ignore_errors=True)
    print(f"{OUT}  {len(stamps)} frames  {OUT.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
