"""Builds dist/HibCleanPC.exe: one file with the interface, the scripts and
WebView2 inside it.

Run: python tools/build.py           (Windows, uses the C# compiler built into Windows)
     python tools/build.py --icon    also redraw app/app.ico from ui/mark.svg (needs Pillow and Playwright)
"""
import hashlib
import io
import re
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD, DIST, VENDOR = ROOT / "build", ROOT / "dist", ROOT / "vendor"
CSC = Path(r"C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe")
BUILD.mkdir(exist_ok=True)
DIST.mkdir(exist_ok=True)

MANIFEST = """<?xml version="1.0" encoding="utf-8"?>
<assembly manifestVersion="1.0" xmlns="urn:schemas-microsoft-com:asm.v1">
  <assemblyIdentity version="1.0.0.0" name="HibCleanPC"/>
  <trustInfo xmlns="urn:schemas-microsoft-com:asm.v2">
    <security><requestedPrivileges xmlns="urn:schemas-microsoft-com:asm.v3">
      <requestedExecutionLevel level="asInvoker" uiAccess="false"/>
    </requestedPrivileges></security>
  </trustInfo>
  <compatibility xmlns="urn:schemas-microsoft-com:compatibility.v1">
    <application><supportedOS Id="{8e0f7a12-bfb3-4fe8-b9a5-48fd50a15a9a}"/></application>
  </compatibility>
  <application xmlns="urn:schemas-microsoft-com:asm.v3">
    <windowsSettings>
      <dpiAware xmlns="http://schemas.microsoft.com/SMI/2005/WindowsSettings">true/pm</dpiAware>
      <dpiAwareness xmlns="http://schemas.microsoft.com/SMI/2016/WindowsSettings">PerMonitorV2</dpiAwareness>
    </windowsSettings>
  </application>
</assembly>
"""


def pack(folder, name):
    """Zips a folder deterministically and returns the zip path."""
    out = BUILD / name
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(folder.rglob("*")):
            if p.is_file():
                info = zipfile.ZipInfo(p.relative_to(folder).as_posix(), date_time=(2026, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                z.writestr(info, p.read_bytes())
    return out


WEBVIEW2_VERSION = "1.0.4258.31"


def vendor():
    """Downloads the WebView2 SDK from NuGet once and keeps the three files it needs."""
    need = {"lib/net462/Microsoft.Web.WebView2.Core.dll", "lib/net462/Microsoft.Web.WebView2.WinForms.dll",
            "runtimes/win-x64/native/WebView2Loader.dll"}
    if all((VENDOR / Path(n).name).exists() for n in need):
        return
    VENDOR.mkdir(exist_ok=True)
    url = f"https://www.nuget.org/api/v2/package/Microsoft.Web.WebView2/{WEBVIEW2_VERSION}"
    data = urllib.request.urlopen(url, timeout=120).read()
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for n in need:
            (VENDOR / Path(n).name).write_bytes(z.read(n))


def icon():
    """Draws ui/mark.svg at icon sizes and saves app/app.ico (only with --icon)."""
    from PIL import Image
    from playwright.sync_api import sync_playwright
    svg = (ROOT / "ui" / "mark.svg").read_text(encoding="utf-8")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 256, "height": 256})
        page.set_content(f"<body style='margin:0;background:transparent'>{svg}</body>")
        png = page.screenshot(omit_background=True, clip={"x": 0, "y": 0, "width": 256, "height": 256})
        browser.close()
    img = Image.open(io.BytesIO(png)).convert("RGBA")
    img.save(ROOT / "ui" / "icon-256.png")
    img.save(ROOT / "app" / "app.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])


def main():
    vendor()
    if "--icon" in sys.argv or not (ROOT / "app" / "app.ico").exists():
        icon()
    ico = ROOT / "app" / "app.ico"
    version = re.search(r'Version = "([^"]+)"', (ROOT / "app" / "HibCleanPC.cs").read_text(encoding="utf-8")).group(1)
    cs = (ROOT / "app" / "HibCleanPC.cs").read_text(encoding="utf-8")
    assert f'AssemblyInformationalVersion("{version}")' in cs, "update the [assembly: ...Version] lines to match Program.Version"
    ui = pack(ROOT / "ui", "ui.zip")
    scripts = pack(ROOT / "scripts", "scripts.zip")
    # A content hash, so the app re-extracts its files whenever they change.
    digest = hashlib.sha256(ui.read_bytes() + scripts.read_bytes() + (ROOT / "app" / "HibCleanPC.cs").read_bytes()).hexdigest()[:16]
    (BUILD / "build.txt").write_text(digest, encoding="utf-8")
    (BUILD / "app.manifest").write_text(MANIFEST, encoding="utf-8")
    exe = DIST / "HibCleanPC.exe"
    subprocess.run([
        str(CSC), "/nologo", "/target:winexe", "/platform:x64", "/optimize+", f"/out:{exe}",
        f"/win32icon:{ico}", f"/win32manifest:{BUILD / 'app.manifest'}",
        "/r:System.Web.Extensions.dll", "/r:System.Windows.Forms.dll", "/r:System.Drawing.dll",
        "/r:System.IO.Compression.dll", "/r:System.IO.Compression.FileSystem.dll",
        f"/r:{VENDOR / 'Microsoft.Web.WebView2.Core.dll'}", f"/r:{VENDOR / 'Microsoft.Web.WebView2.WinForms.dll'}",
        f"/resource:{VENDOR / 'Microsoft.Web.WebView2.Core.dll'},Microsoft.Web.WebView2.Core.dll",
        f"/resource:{VENDOR / 'Microsoft.Web.WebView2.WinForms.dll'},Microsoft.Web.WebView2.WinForms.dll",
        f"/resource:{VENDOR / 'WebView2Loader.dll'},WebView2Loader.dll",
        f"/resource:{ui},ui.zip", f"/resource:{scripts},scripts.zip", f"/resource:{BUILD / 'build.txt'},build.txt",
        str(ROOT / "app" / "HibCleanPC.cs"),
    ], check=True)
    print(f"{exe} (version {version}, {exe.stat().st_size // 1024} KB, build {digest})")


if __name__ == "__main__":
    main()
