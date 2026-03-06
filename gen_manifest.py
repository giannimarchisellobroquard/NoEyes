#!/usr/bin/env python3
"""
gen_manifest.py — Generate manifest.json for the current repo files.

Run this from the repo root before every release commit:
    python gen_manifest.py

This writes manifest.json containing the SHA-256 hash of every file in
TOOL_FILES.  Commit manifest.json alongside the release so update.py
can verify downloaded files against it.
"""

import hashlib, json
from pathlib import Path

TOOL_FILES = [
    "noeyes.py", "server.py", "client.py", "encryption.py",
    "identity.py", "utils.py", "config.py",
    "launch.py", "setup.py", "update.py",
    "install.sh", "install.ps1", "install.bat",
    "selftest.py", "demo2.py", "selftest_demo2.py",
    "README.md", "CHANGELOG.md", "requirements.txt", ".gitignore",
    "sfx/diskette.mp3", "sfx/crt.mp3", "sfx/logo.mp3",
]

HERE = Path(__file__).parent.resolve()

manifest = {}
missing  = []
for f in TOOL_FILES:
    p = HERE / f
    if p.exists():
        manifest[f] = hashlib.sha256(p.read_bytes()).hexdigest()
        print(f"  ✔  {f}")
    else:
        missing.append(f)
        print(f"  ?  {f}  (not found — skipped)")

out = HERE / "manifest.json"
out.write_text(json.dumps(manifest, indent=2))
print(f"\n  manifest.json written ({len(manifest)} files)")
if missing:
    print(f"  Skipped {len(missing)} missing file(s): {', '.join(missing)}")
print("  Commit manifest.json with your release.\n")
