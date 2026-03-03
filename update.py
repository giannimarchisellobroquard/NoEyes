#!/usr/bin/env python3
"""
update.py — NoEyes self-updater

Pulls the latest version from GitHub and replaces the tool files in-place.
Your keys, config, identity, and received files are NEVER touched.

Usage:
    python update.py           — update to latest
    python update.py --check   — check if an update is available, don't install
    python update.py --force   — re-download and reinstall even if up to date
"""

import argparse, json, os, shutil, sys, tempfile, urllib.request
from pathlib import Path

REPO_OWNER = "Ymsniper"
REPO_NAME  = "NoEyes"
GITHUB_API = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}"
RAW_BASE   = f"https://raw.githubusercontent.com/{REPO_OWNER}/{REPO_NAME}"

TOOL_FILES = [
    # core
    "noeyes.py", "server.py", "client.py", "encryption.py",
    "identity.py", "utils.py", "config.py",
    # UI / helpers
    "launch.py",       # interactive launcher
    "setup.py",        # dependency wizard  ← NEW
    "update.py",       # self-updater
    # bootstrap (platform entry-points for setup.py)
    "install.sh",      # Linux / macOS / Termux / iSH
    "install.ps1",     # Windows PowerShell
    "install.bat",     # Windows CMD fallback
    # tests / demos
    "selftest.py",
    "demo2.py",
    "selftest_demo2.py",
    # docs
    "README.md", "CHANGELOG.md", "requirements.txt", ".gitignore",
]

PROTECTED = {
    "files", "chat.key", "noeyes_config.json",
    ".noeyes_version", ".noeyes_backup",
}

HERE = Path(__file__).parent.resolve()


def _get(url, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": f"NoEyes-updater/{REPO_OWNER}"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()

def _get_json(url):
    return json.loads(_get(url))

def _c(code, msg): return f"\033[{code}m{msg}\033[0m"
def ok(m):   print(_c("92", f"  ✔  {m}"))
def warn(m): print(_c("93", f"  !  {m}"))
def err(m):  print(_c("91", f"  ✘  {m}"))
def info(m): print(_c("90", f"  ·  {m}"))


def latest_commit():
    for branch in ("main", "master"):
        try:
            d = _get_json(f"{GITHUB_API}/commits/{branch}")
            return {"sha": d["sha"], "short": d["sha"][:7],
                    "message": d["commit"]["message"].splitlines()[0],
                    "author":  d["commit"]["author"]["name"],
                    "date":    d["commit"]["author"]["date"][:10],
                    "branch":  branch}
        except Exception:
            continue
    err("Could not reach GitHub. Check your internet connection.")
    sys.exit(1)

def local_commit():
    p = HERE / ".noeyes_version"
    return p.read_text().strip() if p.exists() else ""

def save_commit(sha):
    (HERE / ".noeyes_version").write_text(sha)

def download(filename, branch, dest):
    try:
        data = _get(f"{RAW_BASE}/{branch}/{filename}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        return True
    except Exception as e:
        err(f"Failed to download {filename}: {e}")
        return False


def cmd_check():
    info("Checking for updates…")
    lo = local_commit(); re = latest_commit()
    if not lo:
        warn("No version info found — run  python update.py  to install.")
        return
    if lo == re["sha"]:
        ok(f"Already up to date  ({re['short']} · {re['date']})")
    else:
        warn("Update available!")
        info(f"Installed : {lo[:7]}")
        info(f"Latest    : {re['short']} — {re['message']}  ({re['date']})")
        info("Run  python update.py  to install.")


def cmd_update(force=False):
    info("Checking for updates…")
    lo = local_commit(); re = latest_commit()

    if lo == re["sha"] and not force:
        ok(f"Already up to date  ({re['short']} · {re['date']})")
        return

    print()
    print(_c("96", f"  {'Updating' if lo else 'Installing'}  "
             f"{lo[:7] + ' → ' if lo else ''}{re['short']}"))
    info(f"{re['message']}  by {re['author']}  on {re['date']}")
    print()

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir); failed = []
        info("Downloading files…")
        for f in TOOL_FILES:
            if download(f, re["branch"], tmp / f):
                info(f"  ✓ {f}")
            else:
                failed.append(f)

        if failed:
            print()
            err(f"Download failed for: {', '.join(failed)}")
            err("Aborting — your installation is unchanged.")
            sys.exit(1)

        info("Installing…")
        backup = HERE / ".noeyes_backup"
        backup.mkdir(exist_ok=True)
        replaced = []

        try:
            for f in TOOL_FILES:
                src = tmp / f; dest = HERE / f
                parts = dest.relative_to(HERE).parts
                if parts[0] in PROTECTED or dest.name in PROTECTED:
                    continue
                if not src.exists():
                    continue
                if dest.exists():
                    shutil.copy2(dest, backup / f)
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dest)
                replaced.append(f)
        except Exception as e:
            err(f"Install error: {e}")
            warn("Rolling back…")
            for f in replaced:
                b = backup / f
                if b.exists(): shutil.copy2(b, HERE / f)
            warn("Rolled back — your installation is unchanged.")
            sys.exit(1)

    save_commit(re["sha"])
    print()
    ok(f"Updated to {re['short']} successfully!")
    info(f"{len(replaced)} file(s) replaced.")
    info("Backup saved to .noeyes_backup/")
    info("Keys, identity, config, and received files were not touched.")
    print()
    info("Run  python setup.py --check  to verify all dependencies are up to date.")


def main():
    ap = argparse.ArgumentParser(description="NoEyes self-updater")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    cmd_check() if args.check else cmd_update(force=args.force)

if __name__ == "__main__":
    main()
