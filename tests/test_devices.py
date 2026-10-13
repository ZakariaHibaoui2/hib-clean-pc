"""Any-device test of the real app: small laptops, 4K screens, tablets in portrait,
touch and pen, high DPI, Windows high contrast, reduced motion, keyboard only, and
the Windows on ARM build. Launches dist/HibCleanPC.exe read-only (HIB_READONLY=1)
with its own WebView2 folder, so it can run beside an open copy of the app.

Checks every section at several window sizes, in English, French and Arabic:
nothing scrolls sideways, nothing sticks out of its container, no text is cut off.
Screenshots go to tests/screenshots/devices/.

Run: python tests/test_devices.py           (add --quick for fewer sizes)
"""
import ctypes
import ctypes.wintypes as wt
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
EXE = ROOT / "dist" / "HibCleanPC.exe"
VENDOR = ROOT / "vendor"
SHOTS = ROOT / "tests" / "screenshots" / "devices"
SHOTS.mkdir(parents=True, exist_ok=True)
CSC = Path(r"C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe")
PORT = 9336
QUICK = "--quick" in sys.argv

SECTIONS = ["home", "clean", "bigfiles", "startup", "windows", "security", "privacy", "battery", "updates", "adblock", "laptop"]
# Window content sizes in CSS pixels (what the page gets at any scaling).
SIZES = [
    ("smallest window", 784, 521),       # the window's minimum size, minus its frame
    ("small laptop", 1024, 768),
    ("tablet portrait", 800, 1280),
    ("laptop", 1280, 800),
    ("full HD", 1920, 1080),
    ("QHD", 2560, 1440),
    ("4K at 100%", 3840, 2160),
]
if QUICK:
    SIZES = [SIZES[0], SIZES[2], SIZES[4]]
# Other languages at the sizes where long words hurt most.
LANG_SIZES = [("smallest window", 784, 521), ("tablet portrait", 800, 1280), ("laptop", 1280, 800)]

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + (f"  ({detail})" if detail and not ok else ""))


# ---------------------------------------------------------------- the exe itself

def pe_machine(data):
    """The Machine field of a PE file's COFF header."""
    if data[:2] != b"MZ":
        return None
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    if data[pe:pe + 4] != b"PE\0\0":
        return None
    return struct.unpack_from("<H", data, pe + 4)[0]


def clr_flags(data):
    """The COR20 header flags of a .NET exe (ILONLY, 32BITREQUIRED, 32BITPREFERRED)."""
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    opt = pe + 24
    magic = struct.unpack_from("<H", data, opt)[0]
    dirs = opt + (96 if magic == 0x10B else 112)
    rva, _ = struct.unpack_from("<II", data, dirs + 14 * 8)
    nsect = struct.unpack_from("<H", data, pe + 6)[0]
    sects = opt + struct.unpack_from("<H", data, pe + 20)[0]
    for i in range(nsect):
        _, vsize, vaddr, rawsize, rawptr = struct.unpack_from("<8sIIII", data, sects + i * 40)
        if vaddr <= rva < vaddr + max(vsize, rawsize):
            return struct.unpack_from("<I", data, rva - vaddr + rawptr + 16)[0]
    return None


MACHINES = {"x86": 0x14C, "x64": 0x8664, "arm64": 0xAA64}

HARNESS = r"""
using System;
using System.IO;
using System.Reflection;
static class T {
    static int fails;
    static void Eq(string name, string got, string want) {
        bool ok = got == want; if (!ok) fails++;
        Console.WriteLine((ok ? "PASS " : "FAIL ") + name + (ok ? "" : "  (got " + (got ?? "null") + ", want " + want + ")"));
    }
    static int Main(string[] a) {
        Eq("loader for an x64 PE machine", HibCleanPC.Arch.FromMachine(0x8664), "x64");
        Eq("loader for an ARM64 PE machine", HibCleanPC.Arch.FromMachine(0xAA64), "arm64");
        Eq("loader for an x86 PE machine", HibCleanPC.Arch.FromMachine(0x014c), "x86");
        Eq("no loader for an unknown machine", HibCleanPC.Arch.FromMachine(0x01c4), null);
        Eq("ARM64 process (PROCESSOR_ARCHITECTURE=ARM64) gets the arm64 loader", HibCleanPC.Arch.FromEnvironment("ARM64", 8), "arm64");
        Eq("x64 process, also when emulated on ARM64, gets the x64 loader", HibCleanPC.Arch.FromEnvironment("AMD64", 8), "x64");
        Eq("32-bit process gets the x86 loader", HibCleanPC.Arch.FromEnvironment("x86", 4), "x86");
        Eq("32-bit process on 64-bit Windows gets the x86 loader", HibCleanPC.Arch.FromEnvironment("AMD64", 4), "x86");
        Eq("unknown architecture falls back to x64", HibCleanPC.Arch.FromEnvironment(null, 8), "x64");
        Eq("this PC's process is detected as " + a[1], HibCleanPC.Arch.Current(), a[1]);
        Eq("resource name", HibCleanPC.Arch.Resource("arm64"), "WebView2Loader.arm64.dll");
        // Pull each embedded loader out of the built exe for the PE check in Python.
        var asm = Assembly.LoadFile(a[0]);
        foreach (var arch in new[] { "x86", "x64", "arm64" }) {
            using (var s = asm.GetManifestResourceStream(HibCleanPC.Arch.Resource(arch))) {
                if (s == null) { Console.WriteLine("FAIL exe embeds the " + arch + " loader"); fails++; continue; }
                using (var f = File.Create(Path.Combine(a[2], arch + ".dll"))) s.CopyTo(f);
            }
        }
        return fails;
    }
}
"""


def static_checks():
    data = EXE.read_bytes()
    flags = clr_flags(data)
    check("exe is AnyCPU (IL only, not 32-bit required or preferred), so it runs natively on x64 and ARM64",
          flags is not None and flags & 1 and not flags & 2 and not flags & 0x20000, hex(flags or 0))
    for arch, machine in MACHINES.items():
        f = VENDOR / f"WebView2Loader.{arch}.dll"
        check(f"vendor WebView2Loader.{arch}.dll is built for {arch}", f.exists() and pe_machine(f.read_bytes()) == machine)
    # Compile Arch.cs with a small harness and check its mapping, then what the exe embeds.
    tmp = Path(tempfile.mkdtemp(prefix="hib-arch-"))
    try:
        (tmp / "t.cs").write_text(HARNESS, encoding="utf-8")
        out = tmp / "t.exe"
        r = subprocess.run([str(CSC), "/nologo", "/platform:anycpu", f"/out:{out}", str(tmp / "t.cs"), str(ROOT / "app" / "Arch.cs")],
                           capture_output=True, text=True)
        check("Arch.cs compiles with the C# 5 compiler", r.returncode == 0, r.stdout[-300:])
        if r.returncode == 0:
            native = os.environ.get("PROCESSOR_ARCHITECTURE", "AMD64").upper()
            here = {"AMD64": "x64", "ARM64": "arm64", "X86": "x86"}.get(native, "x64")
            r = subprocess.run([str(out), str(EXE), here, str(tmp)], capture_output=True, text=True)
            for line in r.stdout.splitlines():
                if line.startswith(("PASS ", "FAIL ")):
                    check(line[5:].split("  (")[0], line.startswith("PASS "), line)
            for arch, machine in MACHINES.items():
                f = tmp / f"{arch}.dll"
                check(f"exe embeds the {arch} WebView2 loader, built for {arch}", f.exists() and pe_machine(f.read_bytes()) == machine)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------- the window

user32 = ctypes.windll.user32
# Measure in real pixels: without this, Windows scales what this script sees by the DPI.
try:
    user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
except Exception:
    pass
user32.GetWindowDpiAwarenessContext.restype = ctypes.c_void_p
user32.GetAwarenessFromDpiAwarenessContext.argtypes = [ctypes.c_void_p]
user32.AreDpiAwarenessContextsEqual.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
user32.MonitorFromWindow.restype = ctypes.c_void_p
user32.GetMonitorInfoW.argtypes = [ctypes.c_void_p, ctypes.c_void_p]


def window_of(pid):
    found = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def each(hwnd, _):
        p = wt.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
        if p.value == pid and user32.IsWindowVisible(hwnd) and user32.GetWindowTextLengthW(hwnd):
            found.append(hwnd)
        return True
    user32.EnumWindows(each, 0)
    return found[0] if found else None


def window_checks(proc):
    hwnd = None
    for _ in range(60):
        hwnd = window_of(proc.pid)
        if hwnd:
            break
        time.sleep(0.5)
    check("app window found", hwnd is not None)
    if not hwnd:
        return
    # Per-monitor DPI aware (V2), so Windows never stretches it into a blurry bitmap.
    ctx = user32.GetWindowDpiAwarenessContext(hwnd)
    aware = user32.GetAwarenessFromDpiAwarenessContext(ctx)
    check("window is per-monitor DPI aware", aware == 2, str(aware))
    pmv2 = user32.AreDpiAwarenessContextsEqual(ctx, ctypes.c_void_p(-4))
    check("window uses per-monitor DPI awareness V2", bool(pmv2))
    dpi = user32.GetDpiForWindow(hwnd)
    rect = wt.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    mon = user32.MonitorFromWindow(hwnd, 2)

    class MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", wt.DWORD), ("rcMonitor", wt.RECT), ("rcWork", wt.RECT), ("dwFlags", wt.DWORD)]
    mi = MONITORINFO(cbSize=ctypes.sizeof(MONITORINFO))
    user32.GetMonitorInfoW(mon, ctypes.byref(mi))
    work = mi.rcWork
    w, h = rect.right - rect.left, rect.bottom - rect.top
    ww, wh = work.right - work.left, work.bottom - work.top
    check("window fits the screen's work area", rect.left >= work.left - 8 and rect.right <= work.right + 8
          and rect.top >= work.top - 8 and rect.bottom <= work.bottom + 8, f"{w}x{h} in {ww}x{wh}")
    cx = (rect.left + rect.right) / 2 - (work.left + work.right) / 2
    cy = (rect.top + rect.bottom) / 2 - (work.top + work.bottom) / 2
    check("window opens centred", abs(cx) <= 16 and abs(cy) <= 16, f"off by {cx:.0f},{cy:.0f}")
    logical = (w * 96 / dpi, h * 96 / dpi)
    check("window opens at a comfortable size for this scaling (not tiny, not huge)",
          (logical[0] >= 1100 or w >= ww * 0.9) and logical[0] <= 1300, f"{w}x{h} px at {dpi * 100 // 96}%")
    # Minimum size: try to make it tiny; Windows must stop at about 800x560 logical pixels.
    user32.ShowWindow(hwnd, 9)
    user32.SetWindowPos(hwnd, 0, rect.left, rect.top, 300, 200, 0x0004 | 0x0010)
    time.sleep(0.4)
    small = wt.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(small))
    sw, sh = (small.right - small.left) * 96 / dpi, (small.bottom - small.top) * 96 / dpi
    check("window can't be made smaller than 800x560", sw >= 795 and sh >= 555 or (small.right - small.left) >= ww - 2,
          f"{sw:.0f}x{sh:.0f}")
    user32.SetWindowPos(hwnd, 0, rect.left, rect.top, w, h, 0x0004 | 0x0010)


# ---------------------------------------------------------------- the page

LAYOUT_JS = r"""() => {
  const out = [];
  const name = (el) => {
    let s = el.tagName.toLowerCase() + (el.id ? '#' + el.id : '') + (typeof el.className === 'string' && el.className ? '.' + el.className.trim().split(/\s+/).join('.') : '');
    const txt = (el.textContent || '').trim().slice(0, 30);
    return txt ? `${s} "${txt}"` : s;
  };
  const doc = document.scrollingElement;
  const vw = doc.clientWidth;
  if (doc.scrollWidth > vw + 1) out.push(`page scrolls sideways (${doc.scrollWidth} > ${vw})`);
  for (const box of document.querySelectorAll('#view, .side, #nav')) {
    if (box.scrollWidth > box.clientWidth + 1) out.push(`${name(box)} scrolls sideways (${box.scrollWidth} > ${box.clientWidth})`);
  }
  const skip = '.sr, #report, #screen-test, .skip, .ambient, svg, canvas, option, .orb, .switch span';
  for (const el of document.querySelectorAll('body *')) {
    if (el.closest(skip) || el.closest('[hidden]')) continue;
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden' || cs.display === 'contents') continue;
    const r = el.getBoundingClientRect();
    if (r.width <= 1 || r.height <= 1) continue;   // empty, or visually hidden for screen readers
    if (r.right > vw + 1 || r.left < -1) { out.push(`${name(el)} goes off screen (${Math.round(r.left)}..${Math.round(r.right)} of ${vw})`); continue; }
    const p = el.parentElement;
    if (p && p !== document.body && !p.matches('main')) {
      const q = p.getBoundingClientRect();
      if (r.right > q.right + 1.5 || r.left < q.left - 1.5) out.push(`${name(el)} sticks out of ${name(p)} by ${Math.round(Math.max(r.right - q.right, q.left - r.left))}px`);
    }
    const clips = cs.overflowX !== 'visible';
    const scrolls = cs.overflowX === 'auto' || cs.overflowX === 'scroll';
    if (clips && !scrolls && el.scrollWidth > el.clientWidth + 1) {
      // Cut-off text is only fine when it ends in an ellipsis and the full text is one hover or focus away.
      const ok = cs.textOverflow === 'ellipsis' && el.closest('[title], [aria-label]');
      if (!ok) out.push(`${name(el)} cuts off its content (${el.scrollWidth} > ${el.clientWidth})`);
    }
  }
  return [...new Set(out)].slice(0, 8);
}"""

TARGETS_JS = r"""() => {
  const out = [];
  const sel = 'a[href], button, select, input, [role="switch"], [tabindex]:not([tabindex="-1"])';
  for (const el of document.querySelectorAll(sel)) {
    if (el.closest('[hidden], .sr, #report, #screen-test') || el.matches('.skip')) continue;
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden') continue;
    let r = el.getBoundingClientRect();
    if (r.width < 1 || r.height < 1) continue;
    // A checkbox or radio is tapped through its whole label.
    const label = el.matches('input[type="checkbox"], input[type="radio"]') && el.closest('label');
    if (label) r = label.getBoundingClientRect();
    // Links inside a sentence are exempt (WCAG 2.5.8 inline exception).
    if (el.matches('a') && getComputedStyle(el).display === 'inline') continue;
    if (r.width < 40 - 0.5 || r.height < 40 - 0.5) {
      const txt = (el.textContent || el.getAttribute('aria-label') || '').trim().slice(0, 24);
      out.push(`${el.tagName.toLowerCase()}${el.className && typeof el.className === 'string' ? '.' + el.className.trim().split(/\s+/).join('.') : ''} "${txt}" ${Math.round(r.width)}x${Math.round(r.height)}`);
    }
  }
  return [...new Set(out)].slice(0, 8);
}"""

NAMES_JS = r"""() => {
  const out = [];
  for (const el of document.querySelectorAll('a[href], button, select, input, [role="switch"]')) {
    if (el.closest('[hidden], #report')) continue;
    let name = el.getAttribute('aria-label') || (el.labels && el.labels[0] && el.labels[0].textContent) || el.textContent || el.title || '';
    const lb = el.getAttribute('aria-labelledby');
    if (lb) name = lb.split(' ').map((id) => (document.getElementById(id) || {}).textContent || '').join(' ');
    if (!name.trim()) out.push(el.outerHTML.slice(0, 80));
  }
  return out.slice(0, 5);
}"""


def tap(cdp, page, selector):
    """A real touch tap (touchstart + touchend) in the middle of the element."""
    page.locator(selector).first.scroll_into_view_if_needed()
    box = page.locator(selector).first.bounding_box()
    x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    cdp.send("Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": [{"x": x, "y": y, "radiusX": 6, "radiusY": 6}]})
    cdp.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
    page.wait_for_timeout(250)


def ready(page, timeout=150):
    end = time.time() + timeout
    while time.time() < end:
        try:
            if page.evaluate("() => !!document.querySelector('#view h1') && !document.querySelector('#view .skeleton, #view .loading, #view [aria-busy=\"true\"]')"):
                page.wait_for_timeout(700)   # the entrance animation
                return True
        except Exception:
            pass
        page.wait_for_timeout(300)
    return False


def go(page, section):
    page.evaluate("(s) => { location.hash = s; }", section)
    page.wait_for_function("(s) => document.querySelector('#view').dataset.section === s", arg=section)
    return ready(page)


def big_sandbox():
    root = Path(os.path.realpath(tempfile.mkdtemp(prefix="hibclean-dev-")))
    for name, mb in [("a-very-long-file-name-from-a-camera-export-2026-10-13 final final (2).mkv", 3), ("backup.zip", 2)]:
        (root / name).write_bytes(bytes(int(mb * 2**20)))
        t = time.time() - 90 * 86400
        os.utime(root / name, (t, t))
    return root, {"HIB_TEST_BIGFILES_ROOT": str(root), "HIB_TEST_BIGFILES_MIN": str(2**20)}


def layout_pass(page, label, w, h, lang, shots):
    page.set_viewport_size({"width": w, "height": h})
    bad_sections = []
    for s in SECTIONS:
        loaded = go(page, s)
        page.mouse.move(w - 2, h - 2)   # park the pointer so no hover effect shifts anything
        page.wait_for_timeout(250)
        problems = page.evaluate(LAYOUT_JS) if loaded else ["did not finish loading"]
        if s in shots:
            page.screenshot(path=str(SHOTS / f"{w}x{h}-{lang}-{s}.png"))
        if problems:
            bad_sections.append(f"{s}: " + "; ".join(problems[:4]))
    check(f"{label} {w}x{h} {lang}: every section fits, nothing sticks out or is cut off", not bad_sections, " | ".join(bad_sections)[:900])


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if not EXE.exists():
        print("Build first: python tools/build.py")
        return 1
    static_checks()
    sandbox, big_env = big_sandbox()
    wv = tempfile.mkdtemp(prefix="hib-dev-wv-")
    env = {**os.environ, **big_env, "WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS": f"--remote-debugging-port={PORT}",
           "HIB_READONLY": "1", "HIB_WEBVIEW_DIR": wv}
    proc = subprocess.Popen([str(EXE)], env=env)
    errors = []
    try:
        window_checks(proc)
        with sync_playwright() as p:
            browser = None
            for _ in range(80):
                try:
                    browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{PORT}")
                    break
                except Exception:
                    time.sleep(0.5)
            check("app starts and its page can be reached", browser is not None)
            if not browser:
                return 1
            ctx = browser.contexts[0]
            page = ctx.pages[0] if ctx.pages else ctx.wait_for_event("page", timeout=30000)
            page.wait_for_url("https://app.hibclean/**", timeout=30000)
            page.wait_for_selector("#nav a", timeout=30000)
            page.on("pageerror", lambda e: errors.append(f"{e} {(e.stack or '').splitlines()[1:3]}"))
            page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
            cdp = ctx.new_cdp_session(page)
            page.evaluate("localStorage.setItem('lang', 'en')")
            page.reload()
            page.wait_for_selector("#nav a")

            # Warm every scan once at a normal size, so the layout passes measure finished screens.
            page.set_viewport_size({"width": 1280, "height": 800})
            for s in SECTIONS:
                go(page, s)
            info = page.evaluate("() => new Promise((ok) => { const id = 99100; const on = (e) => { if (e.data && e.data.id === id) { window.chrome.webview.removeEventListener('message', on); ok(e.data.data); } }; window.chrome.webview.addEventListener('message', on); window.chrome.webview.postMessage({ id, cmd: 'host.info', args: {} }); })")
            check("host reports the Windows build and process architecture", isinstance(info.get("build"), int) and info.get("arch") in ("x86", "x64", "arm64"), str(info))

            # 1. Layout at every size, every section.
            for label, w, h in SIZES:
                layout_pass(page, label, w, h, "en", {"home", "windows", "bigfiles", "laptop"} if w in (784, 800, 3840) else set())
            for lang in ("fr", "ar"):
                page.select_option("#lang", lang)
                for label, w, h in LANG_SIZES:
                    layout_pass(page, label, w, h, lang, {"home", "windows", "security"} if w != 1280 else set())
            page.select_option("#lang", "en")

            # 2. Narrow windows: the sidebar becomes a rail of icons that still names every section.
            page.set_viewport_size({"width": 784, "height": 521})
            go(page, "home")
            rail = page.evaluate("() => document.querySelector('.side').getBoundingClientRect().width")
            check("narrow window: sidebar collapses to an icon rail", rail <= 96, f"{rail}px")
            fits = page.evaluate("() => { const s = document.querySelector('.side'); return [s.scrollHeight, s.clientHeight]; }")
            check("smallest window: every section icon fits in the rail without scrolling", fits[0] <= fits[1] + 1, str(fits))
            names = page.evaluate("() => [...document.querySelectorAll('#nav a')].map((a) => [a.title, a.getAttribute('aria-label') || a.textContent.trim()])")
            check("icon rail: every section has a tooltip and an accessible name", all(t and n for t, n in names), str(names[:3]))
            page.click('#nav a[href="#battery"]')
            check("icon rail: tapping an icon opens its section", page.evaluate("() => document.querySelector('#view').dataset.section") == "battery")
            page.set_viewport_size({"width": 1280, "height": 800})
            rail = page.evaluate("() => document.querySelector('.side').getBoundingClientRect().width")
            check("wide window: full sidebar with labels", rail >= 200, f"{rail}px")
            check("wide window: no duplicate tooltips on labelled links", not page.evaluate("() => [...document.querySelectorAll('#nav a')].some((a) => a.title)"))

            # 3. Touch and pen: coarse pointer, no hover.
            cdp.send("Emulation.setTouchEmulationEnabled", {"enabled": True, "maxTouchPoints": 5})
            cdp.send("Emulation.setEmitTouchEventsForMouse", {"enabled": True, "configuration": "mobile"})
            cdp.send("Emulation.setEmulatedMedia", {"features": [{"name": "pointer", "value": "coarse"}, {"name": "hover", "value": "none"},
                                                                 {"name": "any-pointer", "value": "coarse"}, {"name": "any-hover", "value": "none"}]})
            page.reload()
            page.wait_for_selector("#nav a")
            coarse = page.evaluate("() => matchMedia('(pointer: coarse)').matches")
            check("touch emulation reports a coarse pointer", coarse)
            for w, h in [(800, 1280), (1280, 800)]:
                page.set_viewport_size({"width": w, "height": h})
                small = []
                for s in SECTIONS:
                    go(page, s)
                    got = page.evaluate(TARGETS_JS)
                    if got:
                        small.append(f"{s}: " + "; ".join(got[:4]))
                check(f"touch {w}x{h}: every tap target is at least 40x40 px", not small, " | ".join(small)[:900])
                go(page, "home")
                page.screenshot(path=str(SHOTS / f"touch-{w}x{h}-home.png"))
            # Pointer tilt must ignore fingers and pens, and never block scrolling.
            go(page, "home")
            tilt = page.evaluate("""() => { const el = document.querySelector('[data-tilt]:not([hidden])'); if (!el) return 'none';
              const r = el.getBoundingClientRect(); const o = { bubbles: true, clientX: r.left + 5, clientY: r.top + 5, pointerType: 'touch' };
              el.dispatchEvent(new PointerEvent('pointermove', o)); return el.style.getPropertyValue('--rx') || ''; }""")
            page.wait_for_timeout(100)
            check("touch: tilt effect ignores touch moves", tilt in ("", "none"), tilt)
            ta = page.evaluate("() => [...document.querySelectorAll('[data-tilt]')].map((e) => getComputedStyle(e).touchAction)")
            check("touch: tilting surfaces keep normal touch scrolling", all(t in ("auto", "manipulation", "pan-y", "pan-x pan-y") for t in ta), str(ta))
            sel = page.evaluate("() => [...document.querySelectorAll('button, .btn, #nav a, .fix, a.tile, .switch')].filter((e) => getComputedStyle(e).userSelect !== 'none').map((e) => e.outerHTML.slice(0, 60))")
            check("touch: buttons and links don't select text on long press", not sel, str(sel[:3]))
            # Hover effects that move things must not stick after a tap.
            sticky = page.evaluate("""() => { const out = []; for (const sh of document.styleSheets) { let rules; try { rules = sh.cssRules; } catch (e) { continue; }
                const walk = (list, inHover) => { for (const r of list) { if (r.media) { walk(r.cssRules, inHover || /hover:\\s*hover/.test(r.media.mediaText)); continue; }
                  if (r.selectorText && /:hover/.test(r.selectorText) && /transform/.test(r.cssText) && !inHover) out.push(r.selectorText); } };
                walk(rules, false); } return out; }""")
            check("touch: hover-only movement is limited to devices that can hover", not sticky, str(sticky))
            # Two-tap confirm on big files works with taps.
            page.set_viewport_size({"width": 800, "height": 1280})
            go(page, "bigfiles")
            tap(cdp, page, "#big .row input")
            check("touch: tapping a file's checkbox ticks it", page.locator("#big .row input").first.is_checked())
            tap(cdp, page, "#bin")
            check("touch: first tap on Move to Recycle Bin asks to tap again", "again" in page.inner_text("#bin").lower(), page.inner_text("#bin"))
            tap(cdp, page, "#bin")
            told = None
            for _ in range(60):
                told = "read-only" in page.inner_text("#toast")
                if told:
                    break
                page.wait_for_timeout(300)
            check("touch: second tap goes ahead (refused in test mode, file kept)", told and any(sandbox.iterdir()))
            cdp.send("Emulation.setEmulatedMedia", {"features": []})
            cdp.send("Emulation.setEmitTouchEventsForMouse", {"enabled": False})
            cdp.send("Emulation.setTouchEmulationEnabled", {"enabled": False})
            page.reload()
            page.wait_for_selector("#nav a")

            # 4. Keyboard only and screen readers.
            page.set_viewport_size({"width": 1280, "height": 800})
            go(page, "home")
            # The app puts focus on the content when a section opens; Shift+Tab walks back
            # through the sidebar to Skip to content, which must then be visible.
            for _ in range(40):
                page.keyboard.press("Shift+Tab")
                if page.evaluate("() => document.activeElement.id") == "skip":
                    break
            seen = page.evaluate("() => { const r = document.activeElement.getBoundingClientRect(); return document.activeElement.id === 'skip' && r.top >= 0 && r.bottom <= innerHeight; }")
            check("keyboard: Skip to content can be reached and shows when focused", seen)
            page.keyboard.press("Enter")
            check("keyboard: Skip to content moves focus to the main area", page.evaluate("() => document.activeElement.id") == "view")
            page.keyboard.press("Shift+Tab")
            for _ in range(20):
                page.keyboard.press("Shift+Tab")
                if page.evaluate("() => !!document.activeElement.closest('#nav')"):
                    break
            ring = page.evaluate("() => { const s = getComputedStyle(document.activeElement); return s.outlineStyle !== 'none' && parseFloat(s.outlineWidth) >= 2; }")
            check("keyboard: sections in the sidebar can be reached and show a focus ring", ring)
            unnamed, heads = [], []
            for s in SECTIONS:
                go(page, s)
                unnamed += [f"{s}: {x}" for x in page.evaluate(NAMES_JS)]
                n = page.evaluate("() => document.querySelectorAll('#view h1').length")
                if n != 1:
                    heads.append(f"{s}: {n}")
            check("screen reader: every button, link and control has a name", not unnamed, "; ".join(unnamed)[:400])
            check("screen reader: each section has exactly one main heading", not heads, str(heads))
            land = page.evaluate("() => [!!document.querySelector('main'), !!document.querySelector('nav[aria-label]'), document.documentElement.lang]")
            check("screen reader: main and navigation landmarks, page language set", land[0] and land[1] and land[2] == "en", str(land))
            check("screen reader: current section is marked aria-current", page.locator('#nav a[aria-current="page"]').count() == 1)

            # 5. Reduced motion: nothing keeps moving.
            cdp.send("Emulation.setEmulatedMedia", {"features": [{"name": "prefers-reduced-motion", "value": "reduce"}]})
            page.reload()
            page.wait_for_selector("#nav a")
            go(page, "home")
            page.wait_for_timeout(800)
            running = page.evaluate("() => document.getAnimations().filter((a) => a.playState === 'running').length")
            check("reduced motion: no CSS animations run", running == 0, str(running))
            # 6. Windows high contrast (forced colors).
            cdp.send("Emulation.setEmulatedMedia", {"features": [{"name": "forced-colors", "value": "active"}, {"name": "prefers-color-scheme", "value": "dark"}]})
            page.reload()
            page.wait_for_selector("#nav a")
            go(page, "windows")
            hc = page.evaluate("""() => {
              const b = document.querySelector('.btn'); const on = document.querySelector('#nav a.on');
              const bs = getComputedStyle(b); const os = getComputedStyle(on);
              const sw = document.querySelector('.switch');
              return { btn: parseFloat(bs.borderTopWidth) > 0 || bs.outlineStyle !== 'none',
                       current: parseFloat(os.borderInlineStartWidth || os.borderLeftWidth) > 0 || os.outlineStyle !== 'none' || os.textDecorationLine.includes('underline'),
                       forced: matchMedia('(forced-colors: active)').matches };
            }""")
            check("high contrast: forced-colors mode is detected", hc["forced"])
            check("high contrast: buttons keep a visible edge", hc["btn"])
            check("high contrast: the current section stays marked", hc["current"])
            go(page, "startup")
            sw = page.evaluate("""() => { const s = document.querySelector('.switch'); if (!s) return 'none';
              return parseFloat(getComputedStyle(s).borderTopWidth) > 0 ? 'ok' : 'flat'; }""")
            check("high contrast: switches keep an outline", sw in ("ok", "none"), sw)
            page.screenshot(path=str(SHOTS / "high-contrast-startup.png"))
            go(page, "windows")
            page.screenshot(path=str(SHOTS / "high-contrast-windows.png"))
            cdp.send("Emulation.setEmulatedMedia", {"features": []})
            check("no JavaScript errors", not errors, "; ".join(errors)[:300])
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except subprocess.TimeoutExpired:
            proc.kill()
        shutil.rmtree(sandbox, ignore_errors=True)
        shutil.rmtree(wv, ignore_errors=True)
    print(f"\n{sum(results)}/{len(results)} checks passed")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
