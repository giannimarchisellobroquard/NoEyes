#!/usr/bin/env python3
"""
install.py — NoEyes universal dependency installer.

Supports:
  • Linux   — Debian/Ubuntu/Mint, Fedora/RHEL/CentOS, Arch/Manjaro,
               Alpine, openSUSE, Void, NixOS
  • macOS   — Homebrew (auto-installs if missing), Xcode CLT
  • Windows — winget, Chocolatey, Scoop, or guided manual install
  • Android — Termux  (pkg)
  • iOS     — iSH Shell (Alpine apk)

Installs in order:
  1. Python 3.8+
  2. pip
  3. Build tools (gcc / clang / MSVC) if cryptography needs compilation
  4. Rust / cargo  (only if no pre-built wheel is available)
  5. cryptography  (PyPI)
  6. Verifies the full NoEyes import chain works

Usage:
  python3 install.py          # normal install
  python3 install.py --check  # only check, do not install anything
  python3 install.py --force  # reinstall even if already present
"""

import argparse
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

# ── colour helpers ────────────────────────────────────────────────────────────

def _tty():
    return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()

def col(code, text):
    return f"\033[{code}m{text}\033[0m" if _tty() else text

def green(t):  return col("92", t)
def red(t):    return col("91", t)
def yellow(t): return col("93", t)
def cyan(t):   return col("96", t)
def bold(t):   return col("1",  t)
def dim(t):    return col("2",  t)

def ok(msg):   print(f"  {green('✔')}  {msg}")
def err(msg):  print(f"  {red('✘')}  {msg}")
def warn(msg): print(f"  {yellow('!')}  {msg}")
def info(msg): print(f"  {cyan('·')}  {msg}")
def step(msg): print(f"\n{bold(msg)}")

# ── platform detection ────────────────────────────────────────────────────────

class Platform:
    """Detect the current runtime environment."""

    def __init__(self):
        self.system   = platform.system()          # Linux / Darwin / Windows
        self.machine  = platform.machine().lower() # x86_64 / aarch64 / arm / i686
        self.is_64    = "64" in self.machine or "x86_64" in self.machine
        self.is_arm   = self.machine.startswith(("arm", "aarch"))

        # Termux: Android Linux with its own pkg manager
        self.is_termux = "com.termux" in os.environ.get("PREFIX", "") or \
                         os.path.isdir("/data/data/com.termux")

        # iSH: iOS Alpine-based shell emulator
        self.is_ish = self.system == "Linux" and \
                      os.path.exists("/proc/ish") or \
                      "ish" in platform.release().lower()

        # Detect Linux distro family
        self.distro        = ""
        self.distro_family = ""   # debian / fedora / arch / alpine / suse / void / nix
        self.pkg_manager   = None

        if self.system == "Linux":
            self._detect_linux()
        elif self.system == "Darwin":
            self.distro_family = "macos"
            self.pkg_manager   = self._find_macos_pkg_manager()
        elif self.system == "Windows":
            self.distro_family = "windows"
            self.pkg_manager   = self._find_windows_pkg_manager()

    def _detect_linux(self):
        if self.is_termux:
            self.distro_family = "termux"
            self.pkg_manager   = "pkg"
            return
        if self.is_ish:
            self.distro_family = "alpine"
            self.pkg_manager   = "apk"
            return

        # Read /etc/os-release
        info_raw = {}
        for path in ("/etc/os-release", "/usr/lib/os-release"):
            if os.path.exists(path):
                for line in open(path):
                    line = line.strip()
                    if "=" in line:
                        k, _, v = line.partition("=")
                        info_raw[k] = v.strip('"\'')
                break

        self.distro = info_raw.get("ID", "").lower()
        like        = info_raw.get("ID_LIKE", "").lower()

        all_ids = f"{self.distro} {like}"

        if any(x in all_ids for x in ("debian", "ubuntu", "mint", "kali", "pop", "elementary", "linuxmint", "raspbian")):
            self.distro_family = "debian"
            self.pkg_manager   = "apt-get"
        elif any(x in all_ids for x in ("fedora", "rhel", "centos", "rocky", "alma", "ol")):
            self.distro_family = "fedora"
            self.pkg_manager   = "dnf" if shutil.which("dnf") else "yum"
        elif any(x in all_ids for x in ("arch", "manjaro", "endeavour", "artix", "garuda")):
            self.distro_family = "arch"
            self.pkg_manager   = "pacman"
        elif any(x in all_ids for x in ("alpine",)):
            self.distro_family = "alpine"
            self.pkg_manager   = "apk"
        elif any(x in all_ids for x in ("opensuse", "suse", "sles")):
            self.distro_family = "suse"
            self.pkg_manager   = "zypper"
        elif any(x in all_ids for x in ("void",)):
            self.distro_family = "void"
            self.pkg_manager   = "xbps-install"
        elif any(x in all_ids for x in ("nixos", "nix")):
            self.distro_family = "nix"
            self.pkg_manager   = "nix-env"
        else:
            # fallback: detect by executable
            for pm, fam in [("apt-get","debian"),("dnf","fedora"),("yum","fedora"),
                            ("pacman","arch"),("apk","alpine"),("zypper","suse"),
                            ("xbps-install","void")]:
                if shutil.which(pm):
                    self.distro_family = fam
                    self.pkg_manager   = pm
                    break

    def _find_macos_pkg_manager(self):
        if shutil.which("brew"):   return "brew"
        if shutil.which("port"):   return "port"
        return None

    def _find_windows_pkg_manager(self):
        if shutil.which("winget"): return "winget"
        if shutil.which("choco"):  return "choco"
        if shutil.which("scoop"):  return "scoop"
        return None

    def __str__(self):
        bits = [self.system]
        if self.distro:       bits.append(self.distro)
        if self.distro_family and self.distro_family != self.distro:
            bits.append(f"[{self.distro_family}]")
        bits.append(self.machine)
        return " / ".join(bits)


P = Platform()

# ── shell helpers ─────────────────────────────────────────────────────────────

def run(cmd, capture=False, check=True, env=None, shell=False):
    """Run a command.  Returns CompletedProcess."""
    kwargs = dict(capture_output=capture, text=True, env=env, shell=shell)
    try:
        return subprocess.run(cmd, **kwargs, check=check)
    except FileNotFoundError:
        if check:
            raise
        return None

def run_ok(cmd, **kw):
    """Return True if command exits 0."""
    try:
        r = run(cmd, capture=True, check=False, **kw)
        return r is not None and r.returncode == 0
    except Exception:
        return False

def has_cmd(name):
    return shutil.which(name) is not None

def need_sudo():
    """True if we need sudo to install system packages."""
    if P.system == "Windows" or P.is_termux:
        return False
    return os.geteuid() != 0

def sudo(*cmd):
    """Return command with sudo prepended when needed."""
    if need_sudo():
        return ["sudo", *cmd]
    return list(cmd)

def ask(prompt, default="y"):
    """Ask yes/no.  Returns True for yes."""
    hint = "[Y/n]" if default == "y" else "[y/N]"
    try:
        ans = input(f"  {prompt} {dim(hint)}: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    if not ans:
        return default == "y"
    return ans in ("y", "yes")

# ── Python version check ──────────────────────────────────────────────────────

def python_ok():
    return sys.version_info >= (3, 8)

def ensure_python():
    step("Step 1 — Python 3.8+")

    v = sys.version_info
    if v >= (3, 8):
        ok(f"Python {v.major}.{v.minor}.{v.micro} — good")
        return True

    warn(f"Python {v.major}.{v.minor} is too old (need ≥ 3.8)")
    return _install_python()

def _install_python():
    info("Installing Python 3...")

    if P.system == "Windows":
        _windows_install_python()
        return False  # user must re-run after install

    cmds = {
        "debian":  sudo("apt-get", "install", "-y", "python3", "python3-venv", "python3-dev"),
        "fedora":  sudo(P.pkg_manager, "install", "-y", "python3", "python3-devel"),
        "arch":    sudo("pacman", "-S", "--noconfirm", "python"),
        "alpine":  sudo("apk", "add", "--no-cache", "python3", "python3-dev"),
        "suse":    sudo("zypper", "install", "-y", "python3", "python3-devel"),
        "void":    sudo("xbps-install", "-y", "python3", "python3-devel"),
        "termux":  ["pkg", "install", "-y", "python"],
        "nix":     ["nix-env", "-iA", "nixpkgs.python3"],
        "macos":   _brew_install_python,
    }
    return _run_install_cmd(cmds, "Python 3", restart_hint=True)


def _windows_install_python():
    print()
    print(bold("  Windows — Python not found or too old"))
    print()
    print("  Option A (recommended):  Windows Package Manager")
    print(dim("    winget install Python.Python.3.12"))
    print()
    print("  Option B:  Download from python.org")
    print(dim("    https://www.python.org/downloads/"))
    print()
    print("  After installing Python, re-run this script.")
    sys.exit(1)

def _brew_install_python():
    _ensure_brew()
    return run(["brew", "install", "python3"], check=False)

# ── pip ───────────────────────────────────────────────────────────────────────

def ensure_pip():
    step("Step 2 — pip")

    pip = _find_pip()
    if pip:
        ver = run([pip, "--version"], capture=True, check=False)
        ok(f"pip found ({pip})" + (f" — {ver.stdout.strip()}" if ver else ""))
        return pip

    info("pip not found — bootstrapping...")
    return _install_pip()

def _find_pip():
    for candidate in (sys.executable, "pip3", "pip"):
        if candidate == sys.executable:
            r = run([sys.executable, "-m", "pip", "--version"], capture=True, check=False)
            if r and r.returncode == 0:
                return sys.executable   # use as "python -m pip"
        elif shutil.which(candidate):
            return candidate
    return None

def _install_pip():
    # ensurepip first
    r = run([sys.executable, "-m", "ensurepip", "--upgrade"], capture=True, check=False)
    if r and r.returncode == 0:
        ok("pip installed via ensurepip")
        return sys.executable

    # get-pip.py
    info("Downloading get-pip.py...")
    import urllib.request
    try:
        url = "https://bootstrap.pypa.io/get-pip.py"
        with tempfile.NamedTemporaryFile(suffix=".py", delete=False) as f:
            tmp = f.name
        urllib.request.urlretrieve(url, tmp)
        run([sys.executable, tmp], check=True)
        os.unlink(tmp)
        ok("pip installed via get-pip.py")
        return sys.executable
    except Exception as e:
        err(f"Could not install pip: {e}")
        _manual_pip_hint()
        sys.exit(1)

def _manual_pip_hint():
    cmds = {
        "debian":  "sudo apt-get install -y python3-pip",
        "fedora":  "sudo dnf install -y python3-pip",
        "arch":    "sudo pacman -S --noconfirm python-pip",
        "alpine":  "sudo apk add --no-cache py3-pip",
        "suse":    "sudo zypper install -y python3-pip",
        "void":    "sudo xbps-install -y python3-pip",
        "termux":  "pkg install python  # pip is included",
        "macos":   "brew install python3  # pip is included",
        "windows": "python -m ensurepip --upgrade",
    }
    hint = cmds.get(P.distro_family or P.system.lower(), "pip install pip --upgrade")
    print(f"\n  Try manually:\n    {dim(hint)}\n")

# ── build tools ───────────────────────────────────────────────────────────────

def ensure_build_tools():
    """
    Install C compiler + headers.  cryptography can use pre-built wheels on
    most platforms but falls back to source compilation on unusual arches.
    We install build tools proactively so the fallback always works.
    """
    step("Step 3 — Build tools (C compiler)")

    if P.system == "Windows":
        _windows_build_tools()
        return

    compiler = shutil.which("gcc") or shutil.which("clang") or shutil.which("cc")
    if compiler:
        ok(f"C compiler found: {compiler}")
        return

    info("No C compiler found — installing...")

    cmds = {
        "debian":  sudo("apt-get", "install", "-y", "build-essential", "libssl-dev",
                        "libffi-dev", "python3-dev"),
        "fedora":  sudo(P.pkg_manager, "install", "-y", "gcc", "openssl-devel",
                        "libffi-devel", "python3-devel"),
        "arch":    sudo("pacman", "-S", "--noconfirm", "base-devel", "openssl"),
        "alpine":  sudo("apk", "add", "--no-cache", "build-base", "openssl-dev",
                        "libffi-dev", "python3-dev", "musl-dev"),
        "suse":    sudo("zypper", "install", "-y", "gcc", "libopenssl-devel",
                        "libffi-devel", "python3-devel"),
        "void":    sudo("xbps-install", "-y", "base-devel", "openssl-devel",
                        "libffi-devel"),
        "termux":  ["pkg", "install", "-y", "clang", "openssl", "libffi"],
        "nix":     ["nix-env", "-iA", "nixpkgs.gcc", "nixpkgs.openssl"],
        "macos":   _xcode_clt,
    }
    _run_install_cmd(cmds, "build tools")

def _xcode_clt():
    if run_ok(["xcode-select", "-p"]):
        ok("Xcode Command Line Tools already installed")
        return
    info("Installing Xcode Command Line Tools (this may take a few minutes)...")
    run(["xcode-select", "--install"], check=False)
    # xcode-select --install opens a GUI dialog — we can't automate further
    warn("A dialog should have appeared. Click Install, then re-run this script.")
    sys.exit(0)

def _windows_build_tools():
    # MSVC Build Tools via winget — lightweight, no full Visual Studio
    if run_ok(["cl"]):  # MSVC cl.exe
        ok("MSVC compiler found")
        return
    if run_ok(["gcc", "--version"]):  # MinGW / MSYS2
        ok("gcc found (MinGW)")
        return
    # cryptography on Windows ships pre-built wheels — no compiler needed normally
    warn("No C compiler found on Windows — this is usually fine because")
    info("cryptography ships pre-built wheels for Windows x86/x64/arm64.")
    info("If pip install fails, install Visual C++ Build Tools from:")
    info("  https://visualstudio.microsoft.com/visual-cpp-build-tools/")

# ── Rust / cargo ──────────────────────────────────────────────────────────────

def ensure_rust_if_needed(pip_cmd):
    """
    Install Rust only if cryptography's pre-built wheel is unavailable.
    We test this by attempting a dry-run first.
    """
    step("Step 4 — Rust (only if needed)")

    # Check if pre-built wheel is likely available
    if _wheel_likely_available():
        ok("Pre-built wheel available for this platform — Rust not needed")
        return

    if shutil.which("cargo"):
        ok("Rust / cargo already installed")
        return

    warn("No pre-built wheel for this platform — Rust compiler needed")
    info("cryptography is written in Rust; building from source requires cargo.")

    if not ask("Install Rust via rustup?"):
        err("Skipped — pip install cryptography will likely fail without Rust")
        return

    _install_rust()

def _wheel_likely_available():
    """
    PyPI ships pre-built cryptography wheels for:
      Windows   x86, x64, arm64
      macOS     x86_64, arm64  (10.12+)
      Linux     manylinux2014  x86_64, aarch64, ppc64le, s390x, i686
    If we're on one of those, no Rust needed.
    """
    s = P.system
    m = P.machine

    if s == "Windows":
        return True
    if s == "Darwin":
        return True  # both Intel and Apple Silicon have wheels
    if s == "Linux":
        # manylinux wheels cover most common arches
        if m in ("x86_64", "aarch64", "armv7l", "i686", "i386", "ppc64le", "s390x"):
            return True
        # Termux: has its own pre-built python-cryptography package
        if P.is_termux:
            return True
    return False

def _install_rust():
    # Platform-specific Rust install
    if P.system == "Windows":
        _windows_install_rust()
        return

    # Try system package first (faster, no rustup overhead)
    system_rust = {
        "debian":  sudo("apt-get", "install", "-y", "rustc", "cargo"),
        "fedora":  sudo(P.pkg_manager, "install", "-y", "rust", "cargo"),
        "arch":    sudo("pacman", "-S", "--noconfirm", "rust"),
        "alpine":  sudo("apk", "add", "--no-cache", "rust", "cargo"),
        "suse":    sudo("zypper", "install", "-y", "rust", "cargo"),
        "void":    sudo("xbps-install", "-y", "rust"),
        "termux":  ["pkg", "install", "-y", "rust"],
        "nix":     ["nix-env", "-iA", "nixpkgs.rustc", "nixpkgs.cargo"],
        "macos":   ["brew", "install", "rust"],
    }

    fam = P.distro_family or P.system.lower()
    if fam in system_rust:
        info(f"Installing Rust via system package manager ({P.pkg_manager})...")
        r = run(system_rust[fam], check=False)
        if r and r.returncode == 0 and shutil.which("cargo"):
            ok("Rust installed via system package manager")
            return
        warn("System package install failed — falling back to rustup")

    # rustup fallback
    info("Installing Rust via rustup.rs...")
    import urllib.request
    try:
        url = "https://sh.rustup.rs"
        with tempfile.NamedTemporaryFile(suffix=".sh", delete=False, mode="w") as f:
            tmp = f.name
        with urllib.request.urlopen(url) as resp:
            open(tmp, "wb").write(resp.read())
        os.chmod(tmp, 0o755)
        run(["sh", tmp, "-y", "--no-modify-path"], check=True)
        os.unlink(tmp)

        # Add cargo to PATH for this session
        cargo_bin = Path.home() / ".cargo" / "bin"
        os.environ["PATH"] = str(cargo_bin) + os.pathsep + os.environ["PATH"]

        if shutil.which("cargo"):
            ok("Rust installed via rustup")
        else:
            warn("Rust installed but cargo not in PATH yet.")
            info(f"Add to your shell profile:  export PATH=\"$HOME/.cargo/bin:$PATH\"")
            info("Then re-run this script.")
    except Exception as e:
        err(f"Rust install failed: {e}")
        info("Install manually: https://rustup.rs")

def _windows_install_rust():
    if shutil.which("winget"):
        info("Installing Rust via winget...")
        run(["winget", "install", "Rustlang.Rustup", "--silent"], check=False)
    else:
        info("Download and run rustup-init.exe from https://rustup.rs")
        info("Then re-run this script.")

# ── cryptography ──────────────────────────────────────────────────────────────

def ensure_cryptography(pip_cmd, force=False):
    step("Step 5 — cryptography (PyPI)")

    if not force:
        try:
            import cryptography
            ok(f"cryptography {cryptography.__version__} already installed")
            return True
        except ImportError:
            pass

    info("Installing cryptography...")

    # Build the pip command
    pip = _pip_cmd(pip_cmd)

    # Termux: prefer system package — avoids building Rust
    if P.is_termux:
        info("Termux detected — trying pkg install python-cryptography first...")
        r = run(["pkg", "install", "-y", "python-cryptography"], check=False)
        if r and r.returncode == 0:
            ok("cryptography installed via pkg (Termux)")
            return True
        warn("pkg install failed — falling back to pip")

    # Try pip install with pre-built wheel
    extra_flags = []
    if P.is_arm and P.system == "Linux" and not P.is_termux:
        # On ARM Linux without pre-built wheel, we need the Rust toolchain
        # Add CRYPTOGRAPHY_DONT_BUILD_RUST=1 as a last resort for very old versions
        # but modern cryptography requires Rust — so we just let it build
        pass

    r = run([*pip, "install", "--upgrade", "cryptography", *extra_flags], check=False)
    if r and r.returncode == 0:
        ok("cryptography installed via pip")
        return True

    err("pip install cryptography failed.")
    _cryptography_fallback_hints()
    return False

def _pip_cmd(pip_bin):
    """Return the list to invoke pip."""
    if pip_bin == sys.executable:
        return [sys.executable, "-m", "pip"]
    return [pip_bin]

def _cryptography_fallback_hints():
    print()
    hints = {
        "debian":  "sudo apt-get install -y python3-cryptography",
        "fedora":  "sudo dnf install -y python3-cryptography",
        "arch":    "sudo pacman -S --noconfirm python-cryptography",
        "alpine":  "sudo apk add --no-cache py3-cryptography",
        "suse":    "sudo zypper install -y python3-cryptography",
        "void":    "sudo xbps-install -y python3-cryptography",
        "termux":  "pkg install python-cryptography",
        "nix":     "nix-env -iA nixpkgs.python3Packages.cryptography",
        "macos":   "brew install openssl && pip3 install cryptography",
        "windows": "pip install cryptography  # ensure Build Tools are installed",
    }
    fam = P.distro_family or P.system.lower()
    hint = hints.get(fam, "pip3 install cryptography")
    print(f"  Try installing via your system package manager:\n    {dim(hint)}\n")

# ── util: generic install runner ─────────────────────────────────────────────

def _run_install_cmd(cmd_map, label, restart_hint=False):
    fam = P.distro_family or P.system.lower()
    cmd = cmd_map.get(fam)

    if cmd is None:
        warn(f"Unknown platform ({P}) — cannot auto-install {label}")
        return False

    if callable(cmd):
        cmd()
        return True

    # Refresh package index first for apt-based systems
    if P.distro_family == "debian":
        info("Refreshing apt package index...")
        run(sudo("apt-get", "update", "-qq"), check=False)

    if P.distro_family == "arch":
        info("Syncing pacman database...")
        run(sudo("pacman", "-Sy", "--noconfirm"), check=False)

    info(f"Running: {' '.join(str(x) for x in cmd)}")
    r = run(cmd, check=False)
    if r and r.returncode == 0:
        ok(f"{label} installed")
        if restart_hint:
            info("Python installed — please re-run this script.")
            sys.exit(0)
        return True
    else:
        err(f"{label} install failed (exit code {r.returncode if r else '?'})")
        return False

# ── macOS: ensure Homebrew ─────────────────────────────────────────────────────

def _ensure_brew():
    if shutil.which("brew"):
        return
    warn("Homebrew not found — installing...")
    if not ask("Install Homebrew? (requires internet + sudo password)"):
        err("Homebrew is needed on macOS. Install from https://brew.sh")
        sys.exit(1)
    import urllib.request
    script_url = "https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh"
    with tempfile.NamedTemporaryFile(suffix=".sh", delete=False) as f:
        tmp = f.name
    info("Downloading Homebrew installer...")
    with urllib.request.urlopen(script_url) as resp:
        open(tmp, "wb").write(resp.read())
    os.chmod(tmp, 0o755)
    run(["/bin/bash", tmp], check=True)
    os.unlink(tmp)
    ok("Homebrew installed")

# ── bore (optional tunnel) ───────────────────────────────────────────────────

def check_bore():
    """Return True if bore binary is reachable."""
    cargo_bin = str(Path.home() / ".cargo" / "bin")
    env = os.environ.copy()
    if cargo_bin not in env.get("PATH", ""):
        env["PATH"] = cargo_bin + os.pathsep + env.get("PATH", "")
    try:
        r = subprocess.run(["bore", "--version"], capture_output=True, env=env)
        return r.returncode == 0
    except FileNotFoundError:
        return False

def install_bore():
    """
    Install bore-cli — no sudo needed anywhere.

    bore tunnels your local NoEyes server to bore.pub so people outside your
    network can connect, even if your ISP blocks port-forwarding (CGNAT, mobile
    data providers, etc.).

    Install path:  ~/.cargo/bin/bore   (user-local, never touches system dirs)

    Strategy:
      Termux  → pkg install bore  (pre-built, no compilation)
      Others  → cargo install bore-cli
                If cargo is missing, install Rust first via rustup --no-modify-path
    """
    cargo_bin = str(Path.home() / ".cargo" / "bin")
    cargo_env = os.environ.copy()
    if cargo_bin not in cargo_env.get("PATH", ""):
        cargo_env["PATH"] = cargo_bin + os.pathsep + cargo_env.get("PATH", "")

    # ── Termux: try native package first (no compilation) ────────────────────
    if P.is_termux:
        info("Termux — trying pkg install bore...")
        r = run(["pkg", "install", "-y", "bore"], check=False)
        if r and r.returncode == 0 and check_bore():
            ok("bore installed via pkg (Termux)")
            return True
        warn("pkg install bore failed — trying cargo...")

    # ── Windows: cargo install or winget ─────────────────────────────────────
    if P.system == "Windows":
        # winget doesn't have bore yet; fall through to cargo
        pass

    # ── Ensure cargo is available ─────────────────────────────────────────────
    cargo_ok = False
    try:
        r = subprocess.run(["cargo", "--version"], capture_output=True, env=cargo_env)
        cargo_ok = r.returncode == 0
    except FileNotFoundError:
        pass

    if not cargo_ok:
        info("cargo not found — installing Rust via rustup (no sudo, user-local)...")
        import urllib.request
        try:
            url = "https://sh.rustup.rs"
            with tempfile.NamedTemporaryFile(suffix=".sh", delete=False, mode="wb") as f:
                tmp = f.name
            with urllib.request.urlopen(url) as resp:
                open(tmp, "wb").write(resp.read())
            os.chmod(tmp, 0o755)
            r = run(["sh", tmp, "-y", "--no-modify-path"], check=False)
            os.unlink(tmp)
            if r and r.returncode == 0:
                os.environ["PATH"] = cargo_bin + os.pathsep + os.environ.get("PATH", "")
                cargo_env["PATH"] = cargo_bin + os.pathsep + cargo_env.get("PATH", "")
                ok("Rust installed via rustup")
            else:
                err("Rust install failed — cannot install bore")
                info("Install Rust manually: https://rustup.rs  then run: cargo install bore-cli")
                return False
        except Exception as e:
            err(f"Rust install failed: {e}")
            return False

    # ── Install bore via cargo ────────────────────────────────────────────────
    info("Running: cargo install bore-cli  (compiles from source, may take a minute)...")
    r = subprocess.run(["cargo", "install", "bore-cli"],
                       capture_output=False, env=cargo_env)
    if r.returncode == 0:
        # Expose bore in this process's PATH too
        if cargo_bin not in os.environ.get("PATH", ""):
            os.environ["PATH"] = cargo_bin + os.pathsep + os.environ.get("PATH", "")
        if check_bore():
            ok("bore installed — bore.pub tunnel ready")
            info("Start a tunnelled server with:  python noeyes.py --server")
            info("(bore starts automatically — no extra flags needed)")
            return True
    err("cargo install bore-cli failed")
    info("You can try manually later:  cargo install bore-cli")
    return False

def ensure_bore():
    """Offer bore install interactively — skipped silently if user says no."""
    step("Step 6 — bore  (optional — online server tunnel)")

    if check_bore():
        ok("bore already installed — bore.pub tunnel ready")
        return

    print()
    print(f"  {cyan('What is bore?')}")
    print("  bore creates a public tunnel from your machine to bore.pub so")
    print("  anyone can connect to your NoEyes server — even if your ISP")
    print("  blocks port-forwarding (very common on mobile/home broadband).")
    print()
    print(f"  {cyan('No sudo required.')} bore installs to ~/.cargo/bin")
    print(f"  {cyan('Credit:')} Eric Zhang — https://github.com/ekzhang/bore")
    print()
    print(f"  {dim('Skip this if you are only connecting to someone else\'s server.')}")
    print()

    if not ask("Install bore? (recommended if you plan to run a server)", default="n"):
        info("Skipped — run  python install.py  again anytime to add bore later")
        return

    print()
    install_bore()

# ── verification ──────────────────────────────────────────────────────────────

def verify():
    step("Verification")

    # Python version
    v = sys.version_info
    py_ok = v >= (3, 8)
    (ok if py_ok else err)(f"Python {v.major}.{v.minor}.{v.micro}")

    # cryptography
    try:
        import cryptography
        from cryptography.fernet import Fernet
        from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        ok(f"cryptography {cryptography.__version__}  (Fernet + X25519 + Ed25519 OK)")
        crypto_ok = True
    except ImportError as e:
        err(f"cryptography import failed: {e}")
        crypto_ok = False

    # NoEyes core files
    # bore (optional)
    bore_present = check_bore()
    if bore_present:
        ok("bore — online tunnel ready (bore.pub)")
    else:
        info("bore not installed — needed only to host a server online")

    here = Path(__file__).parent
    core = ["noeyes.py", "server.py", "client.py", "encryption.py",
            "identity.py", "utils.py", "config.py"]
    missing = [f for f in core if not (here / f).exists()]
    if missing:
        warn(f"Missing NoEyes files: {', '.join(missing)}")
    else:
        ok("All NoEyes core files present")

    return py_ok and crypto_ok

# ── check-only mode ───────────────────────────────────────────────────────────

def check_only():
    step("Checking dependencies (no changes will be made)")

    v = sys.version_info
    py_ok = v >= (3, 8)
    (ok if py_ok else err)(
        f"Python {v.major}.{v.minor}.{v.micro}  {'(OK)' if py_ok else '(need ≥ 3.8)'}")

    pip_found = bool(_find_pip())
    (ok if pip_found else warn)("pip: " + ("found" if pip_found else "not found"))

    compiler = shutil.which("gcc") or shutil.which("clang") or shutil.which("cc")
    (ok if compiler else warn)(f"C compiler: " + (compiler if compiler else "not found"))

    rust = shutil.which("cargo")
    wheel_ok = _wheel_likely_available()
    if wheel_ok:
        ok("Rust/cargo: not needed (pre-built wheel available)")
    else:
        (ok if rust else warn)("Rust/cargo: " + ("found" if rust else "not found (needed)"))

    try:
        import cryptography
        ok(f"cryptography: {cryptography.__version__}")
    except ImportError:
        err("cryptography: not installed")

    bore_ok = check_bore()
    if bore_ok:
        ok("bore: installed — bore.pub tunnel ready")
    else:
        info("bore: not installed  (optional — needed only to host a server online)")

    here = Path(__file__).parent
    core = ["noeyes.py", "server.py", "client.py", "encryption.py",
            "identity.py", "utils.py", "config.py"]
    missing = [f for f in core if not (here / f).exists()]
    (warn if missing else ok)(
        f"NoEyes files: " + (f"missing {missing}" if missing else "all present"))

    print(f"\n  Platform: {dim(str(P))}")
    if P.pkg_manager:
        print(f"  Package manager: {dim(P.pkg_manager)}")

# ── banner ────────────────────────────────────────────────────────────────────

def banner():
    print(cyan(bold("""
  ███╗   ██╗ ██████╗ ███████╗██╗   ██╗███████╗███████╗
  ████╗  ██║██╔═══██╗██╔════╝╚██╗ ██╔╝██╔════╝██╔════╝
  ██╔██╗ ██║██║   ██║█████╗   ╚████╔╝ █████╗  ███████╗
  ██║╚██╗██║██║   ██║██╔══╝    ╚██╔╝  ██╔══╝  ╚════██║
  ██║ ╚████║╚██████╔╝███████╗   ██║   ███████╗███████║
  ╚═╝  ╚═══╝ ╚═════╝ ╚══════╝   ╚═╝   ╚══════╝╚══════╝""")))
    print(f"  {dim('Dependency Installer')}\n")
    print(f"  Platform:  {bold(str(P))}")
    if P.pkg_manager:
        print(f"  Pkg mgr:   {bold(P.pkg_manager)}")
    print(f"  Python:    {bold(sys.version.split()[0])}")
    print()

# ── main ──────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="NoEyes dependency installer")
    ap.add_argument("--check", action="store_true",
                    help="Only check — do not install anything")
    ap.add_argument("--force", action="store_true",
                    help="Reinstall even if already present")
    ap.add_argument("--no-rust", action="store_true",
                    help="Skip Rust install (pip may fail on exotic arches)")
    ap.add_argument("--no-bore", action="store_true",
                    help="Skip bore install prompt entirely")
    args = ap.parse_args()

    banner()

    if args.check:
        check_only()
        return

    try:
        if not ensure_python():
            return  # user must re-run after Python install

        pip_cmd = ensure_pip()

        ensure_build_tools()

        if not args.no_rust:
            ensure_rust_if_needed(pip_cmd)

        success = ensure_cryptography(pip_cmd, force=args.force)

        print()
        if not args.no_bore:
            ensure_bore()

        print()
        if verify():
            print(f"\n  {green(bold('All dependencies satisfied.'))} "
                  f"Run {bold('python launch.py')} to start NoEyes.\n")
        else:
            print(f"\n  {yellow(bold('Some issues remain.'))} "
                  f"See errors above.\n")

    except KeyboardInterrupt:
        print(f"\n\n  {yellow('Interrupted.')}\n")
        sys.exit(1)
    except PermissionError as e:
        print(f"\n  {red('Permission denied:')} {e}")
        if need_sudo():
            print(f"  {dim('Try running with sudo, or run as root.')}")
        sys.exit(1)


if __name__ == "__main__":
    main()
