"""Runs a bundled script the same way the app does: base64 JSON arguments,
JSON on stdout. Used by the tests.
"""
import base64
import json
import os
import subprocess
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
POWERSHELL = Path(os.environ["SystemRoot"]) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"


def run(name, args=None, env=None, timeout=300):
    payload = base64.b64encode(json.dumps(args or {}).encode()).decode()
    proc = subprocess.run(
        [str(POWERSHELL), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
         "-File", str(SCRIPTS / f"{name}.ps1"), "-Payload", payload],
        capture_output=True, timeout=timeout, env={**os.environ, **(env or {})})
    out = proc.stdout.decode("utf-8-sig").strip()
    err = proc.stderr.decode("utf-8", "replace").strip()
    if proc.returncode != 0 or not out:
        raise RuntimeError(f"{name} failed ({proc.returncode}): {err or out}")
    return json.loads(out)
