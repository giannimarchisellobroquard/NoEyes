#!/usr/bin/env python3
"""
setup.py — NoEyes universal setup wizard.

Works on: Linux, macOS, Windows, Termux (Android), iSH (iOS/iPadOS)
Detects platform, shows what's missing, asks permission, installs everything.

Usage:
    python setup.py          — guided wizard
    python setup.py --check  — show status only, no changes
    python setup.py --force  — reinstall even if already present

If Python itself isn't installed yet, first run:
    Linux / macOS / Termux / iSH  →  sh install.sh
    Windows (PowerShell)           →  .\\install.ps1
    Windows (cmd)                  →  install.bat
Those scripts install Python then automatically launch this file.
"""

import os, platform, re, shutil, subprocess, sys, tempfile, threading, time
from pathlib import Path

# ─────────────────────────────────────────────────────────────────────────────
# Compatibility: termios / tty only exist on Unix.
# On Windows we fall back to msvcrt for raw keypress reading.
# ─────────────────────────────────────────────────────────────────────────────
try:
    import termios, tty
    _UNIX = True
except ImportError:
    _UNIX = False

# ══════════════════════════════════════════════════════════════════════════════
#  ANSI colours  (auto-disabled when not a TTY)
# ══════════════════════════════════════════════════════════════════════════════

def _tty():
    return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()

R   = "\033[0m"
B   = "\033[1m"
DIM = "\033[2m"
CY  = "\033[96m"
GR  = "\033[92m"
YL  = "\033[93m"
RD  = "\033[91m"
BL  = "\033[94m"
MG  = "\033[95m"
GY  = "\033[90m"

def cy(s):  return f"{CY}{s}{R}" if _tty() else s
def gr(s):  return f"{GR}{s}{R}" if _tty() else s
def yl(s):  return f"{YL}{s}{R}" if _tty() else s
def rd(s):  return f"{RD}{s}{R}" if _tty() else s
def gy(s):  return f"{GY}{s}{R}" if _tty() else s
def bo(s):  return f"{B}{s}{R}"  if _tty() else s
def dim(s): return f"{DIM}{s}{R}" if _tty() else s

def _strip_ansi(s):
    return re.sub(r"\x1b\[[0-9;]*m", "", s)

# ══════════════════════════════════════════════════════════════════════════════
#  Terminal helpers
# ══════════════════════════════════════════════════════════════════════════════

def clear():
    os.system("cls" if sys.platform == "win32" else "clear")

def hide_cursor():
    if _tty(): sys.stdout.write("\033[?25l"); sys.stdout.flush()

def show_cursor():
    if _tty(): sys.stdout.write("\033[?25h"); sys.stdout.flush()

def getch():
    """Read one keypress, return friendly name (UP/DOWN/ENTER/ESC or char)."""
    if _UNIX:
        import select as _sel
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setcbreak(fd)
            ch = os.read(fd, 1).decode("utf-8", errors="replace")
            if ch != "\x1b":
                return ch
            r, _, _ = _sel.select([fd], [], [], 0.05)
            if not r:
                return "ESC"
            nxt = os.read(fd, 1).decode("utf-8", errors="replace")
            if nxt in ("[", "O"):
                r2, _, _ = _sel.select([fd], [], [], 0.05)
                if r2:
                    fin = os.read(fd, 1).decode("utf-8", errors="replace")
                    if fin == "A": return "UP"
                    if fin == "B": return "DOWN"
            return "ESC"
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
    else:
        import msvcrt
        ch = msvcrt.getch()
        if ch in (b"\x00", b"\xe0"):
            ch2 = msvcrt.getch()
            if ch2 == b"H": return "UP"
            if ch2 == b"P": return "DOWN"
            return "ESC"
        try:
            c = ch.decode("utf-8")
        except Exception:
            return "?"
        return c

# ══════════════════════════════════════════════════════════════════════════════
#  UI components  (same style as launch.py)
# ══════════════════════════════════════════════════════════════════════════════

LOGO = f"""{cy(bo(''))}
  ███╗   ██╗ ██████╗ ███████╗██╗   ██╗███████╗███████╗
  ████╗  ██║██╔═══██╗██╔════╝╚██╗ ██╔╝██╔════╝██╔════╝
  ██╔██╗ ██║██║   ██║█████╗   ╚████╔╝ █████╗  ███████╗
  ██║╚██╗██║██║   ██║██╔══╝    ╚██╔╝  ██╔══╝  ╚════██║
  ██║ ╚████║╚██████╔╝███████╗   ██║   ███████╗███████║
  ╚═╝  ╚═══╝ ╚═════╝ ╚══════╝   ╚═╝   ╚══════╝╚══════╝{R}
{gy("  Setup Wizard  │  Automatic Dependency Installer")}
"""

def box(title, lines, width=0, colour=cy):
    min_w = max(
        len(_strip_ansi(title)) + 4,
        *(len(_strip_ansi(l)) + 4 for l in lines) if lines else [0],
        44,
    )
    w = max(width, min_w)

    def pad(l):
        vis = len(_strip_ansi(l))
        return l + " " * max(0, w - 4 - vis)

    top   = f"  {colour('╭')}{'─'*(w-2)}{colour('╮')}"
    label = f"  {colour('│')} {bo(title)}{' '*(w-4-len(_strip_ansi(title)))} {colour('│')}"
    sep   = f"  {colour('├')}{'─'*(w-2)}{colour('┤')}"
    body  = "\n".join(f"  {colour('│')} {pad(l)} {colour('│')}" for l in lines)
    bot   = f"  {colour('╰')}{'─'*(w-2)}{colour('╯')}"
    return "\n".join([top, label, sep, body, bot])

def spinner_line(msg, fn):
    """Run fn() in a thread, show a spinner on the same line. Returns result."""
    frames = ["⠋","⠙","⠹","⠸","⠼","⠴","⠦","⠧","⠇","⠏"]
    result = [None]
    exc    = [None]

    def worker():
        try:    result[0] = fn()
        except Exception as e: exc[0] = e

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    i = 0
    while t.is_alive():
        sys.stdout.write(f"\r  {cy(frames[i % len(frames)])}  {msg} …  ")
        sys.stdout.flush()
        time.sleep(0.09)
        i += 1
    sys.stdout.write("\r" + " " * (len(msg) + 16) + "\r")
    sys.stdout.flush()
    if exc[0]:
        raise exc[0]
    return result[0]

def print_status(label, ok_flag, detail=""):
    icon = gr("✔") if ok_flag else rd("✘")
    det  = f"  {gy(detail)}" if detail else ""
    print(f"  {icon}  {bo(label)}{det}")

def confirm(prompt, default=True):
    hint = "Y/n" if default else "y/N"
    show_cursor()
    sys.stdout.write(f"  {prompt} {gy(f'[{hint}]')}: ")
    sys.stdout.flush()
    try:
        val = input().strip().lower()
    except (EOFError, KeyboardInterrupt):
        print(); return False
    hide_cursor()
    return (val in ("y","yes")) if val else default

def menu(title, options, selected=0):
    """Arrow-key menu. options = [(label, description), ...]. Returns index."""
    hide_cursor()
    while True:
        clear()
        print(LOGO)
        print(f"  {bo(title)}\n")
        for i, (label, desc) in enumerate(options):
            if i == selected:
                prefix = f"  {cy('❯')} {cy(bo(label))}"
                suffix = f"  {cy(desc)}" if desc else ""
            else:
                prefix = f"    {gy(label)}"
                suffix = f"  {gy(desc)}" if desc else ""
            print(f"{prefix}{suffix}")
        print(f"\n  {gy('↑ ↓  navigate    Enter  select    Ctrl+C  quit')}")
        key = getch()
        if   key in ("UP",   "k"): selected = (selected - 1) % len(options)
        elif key in ("DOWN", "j"): selected = (selected + 1) % len(options)
        elif key in ("\r", "\n", "\x0a"): return selected
        elif key == "\x03": raise KeyboardInterrupt

def pause(msg="Press any key to continue…"):
    print(f"\n  {gy(msg)}")
    hide_cursor()
    try:
        getch()
    except KeyboardInterrupt:
        pass

# ══════════════════════════════════════════════════════════════════════════════
#  Platform detection
# ══════════════════════════════════════════════════════════════════════════════

class Platform:
    def __init__(self):
        self.system  = platform.system()           # Linux / Darwin / Windows
        self.machine = platform.machine().lower()  # x86_64 / aarch64 / arm…
        self.is_arm  = self.machine.startswith(("arm","aarch"))

        self.is_termux = (
            "com.termux" in os.environ.get("PREFIX","") or
            os.path.isdir("/data/data/com.termux")
        )
        self.is_ish = (
            self.system == "Linux" and
            (os.path.exists("/proc/ish") or "ish" in platform.release().lower())
        )

        self.distro_family = ""
        self.pkg_manager   = None
        self.pkg_name      = ""   # human-readable

        if self.system == "Linux":
            self._detect_linux()
        elif self.system == "Darwin":
            self.distro_family = "macos"
            self.pkg_manager   = "brew" if shutil.which("brew") else None
            self.pkg_name      = "macOS"
        elif self.system == "Windows":
            self.distro_family = "windows"
            self.pkg_manager   = (
                "winget" if shutil.which("winget") else
                "choco"  if shutil.which("choco")  else
                "scoop"  if shutil.which("scoop")  else None
            )
            self.pkg_name = "Windows"

    def _detect_linux(self):
        if self.is_termux:
            self.distro_family = "termux"
            self.pkg_manager   = "pkg"
            self.pkg_name      = "Termux (Android)"
            return
        if self.is_ish:
            self.distro_family = "alpine"
            self.pkg_manager   = "apk"
            self.pkg_name      = "iSH (iOS)"
            return

        info = {}
        for p in ("/etc/os-release", "/usr/lib/os-release"):
            if os.path.exists(p):
                for line in open(p):
                    line = line.strip()
                    if "=" in line:
                        k,_,v = line.partition("=")
                        info[k] = v.strip("\"'")
                break

        distro = info.get("ID","").lower()
        like   = info.get("ID_LIKE","").lower()
        name   = info.get("PRETTY_NAME", distro or "Linux")
        self.pkg_name = name
        ids = f"{distro} {like}"

        if any(x in ids for x in ("debian","ubuntu","mint","kali","pop","raspbian","elementary","linuxmint")):
            self.distro_family = "debian"
            self.pkg_manager   = "apt-get"
        elif any(x in ids for x in ("fedora","rhel","centos","rocky","alma","ol")):
            self.distro_family = "fedora"
            self.pkg_manager   = "dnf" if shutil.which("dnf") else "yum"
        elif any(x in ids for x in ("arch","manjaro","endeavour","artix","garuda")):
            self.distro_family = "arch"
            self.pkg_manager   = "pacman"
        elif "alpine" in ids:
            self.distro_family = "alpine"
            self.pkg_manager   = "apk"
        elif any(x in ids for x in ("opensuse","suse","sles")):
            self.distro_family = "suse"
            self.pkg_manager   = "zypper"
        elif "void" in ids:
            self.distro_family = "void"
            self.pkg_manager   = "xbps-install"
        elif any(x in ids for x in ("nixos","nix")):
            self.distro_family = "nix"
            self.pkg_manager   = "nix-env"
        else:
            for pm, fam in [("apt-get","debian"),("dnf","fedora"),("yum","fedora"),
                            ("pacman","arch"),("apk","alpine"),("zypper","suse"),
                            ("xbps-install","void")]:
                if shutil.which(pm):
                    self.distro_family = fam
                    self.pkg_manager   = pm
                    break

    def wheel_available(self):
        """True if cryptography ships a pre-built wheel — no Rust needed."""
        if self.system in ("Windows","Darwin"): return True
        if self.system == "Linux":
            if self.machine in ("x86_64","aarch64","armv7l","i686","i386","ppc64le","s390x"):
                return True
            if self.is_termux: return True
        return False

    def __str__(self):
        if self.pkg_name: return self.pkg_name
        return f"{self.system}/{self.machine}"

P = Platform()

# ══════════════════════════════════════════════════════════════════════════════
#  Dependency checking
# ══════════════════════════════════════════════════════════════════════════════

def _py_ver():
    v = sys.version_info
    return (v.major, v.minor, v.micro), f"{v.major}.{v.minor}.{v.micro}"

def check_python():
    ver, s = _py_ver()
    return ver >= (3,8), s

def check_pip():
    r = subprocess.run(
        [sys.executable, "-m", "pip", "--version"],
        capture_output=True, text=True
    )
    return r.returncode == 0

def check_compiler():
    return bool(
        shutil.which("gcc") or shutil.which("clang") or
        shutil.which("cc")  or shutil.which("cl")
    )

def check_rust():
    cargo_bin = str(Path.home() / ".cargo" / "bin")
    env = os.environ.copy()
    if cargo_bin not in env.get("PATH",""):
        env["PATH"] = cargo_bin + os.pathsep + env.get("PATH","")
    try:
        r = subprocess.run(["cargo","--version"], capture_output=True, env=env)
        return r.returncode == 0
    except FileNotFoundError:
        return False

def check_cryptography():
    r = subprocess.run(
        [sys.executable, "-c", "import cryptography; print(cryptography.__version__)"],
        capture_output=True, text=True
    )
    if r.returncode == 0:
        return True, r.stdout.strip()
    return False, ""

def gather_status():
    """Return dict of {name: (ok, detail)} for every dependency."""
    py_ok, py_ver  = check_python()
    pip_ok         = check_pip()
    cc_ok          = check_compiler()
    rust_ok        = check_rust()
    need_rust      = not P.wheel_available()
    crypto_ok, cv  = check_cryptography()

    return {
        "python":       (py_ok,       py_ver),
        "pip":          (pip_ok,      "python -m pip"),
        "compiler":     (cc_ok,       "gcc / clang / MSVC"),
        "rust":         (rust_ok,     "cargo" if rust_ok else
                         ("not needed — pre-built wheel available" if not need_rust
                          else "needed for this platform")),
        "need_rust":    (need_rust,   ""),
        "cryptography": (crypto_ok,   cv if crypto_ok else "not installed"),
    }

# ══════════════════════════════════════════════════════════════════════════════
#  Installer steps
# ══════════════════════════════════════════════════════════════════════════════

def _run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)

def _ok_run(cmd, **kw):
    r = _run(cmd, **kw)
    return r.returncode == 0

def _sudo(*cmd):
    needs = (P.system != "Windows" and not P.is_termux and os.geteuid() != 0)
    return (["sudo"] + list(cmd)) if needs else list(cmd)

def _refresh_index():
    """Refresh package index (apt / pacman only)."""
    if P.distro_family == "debian":
        _run(_sudo("apt-get","update","-qq"))
    elif P.distro_family == "arch":
        _run(_sudo("pacman","-Sy","--noconfirm"))

# ── pip ───────────────────────────────────────────────────────────────────────

def install_pip():
    # ensurepip first
    if _ok_run([sys.executable, "-m", "ensurepip", "--upgrade"]):
        return True
    # get-pip.py
    import urllib.request
    try:
        url = "https://bootstrap.pypa.io/get-pip.py"
        with tempfile.NamedTemporaryFile(suffix=".py", delete=False) as f:
            tmp = f.name
        urllib.request.urlretrieve(url, tmp)
        ok = _ok_run([sys.executable, tmp])
        os.unlink(tmp)
        return ok
    except Exception:
        return False

# ── build tools ───────────────────────────────────────────────────────────────

def install_compiler():
    _refresh_index()
    cmds = {
        "debian":  _sudo("apt-get","install","-y","build-essential","libssl-dev","libffi-dev","python3-dev"),
        "fedora":  _sudo(P.pkg_manager,"install","-y","gcc","openssl-devel","libffi-devel","python3-devel"),
        "arch":    _sudo("pacman","-S","--noconfirm","base-devel","openssl"),
        "alpine":  _sudo("apk","add","--no-cache","build-base","openssl-dev","libffi-dev","python3-dev","musl-dev"),
        "suse":    _sudo("zypper","install","-y","gcc","libopenssl-devel","libffi-devel","python3-devel"),
        "void":    _sudo("xbps-install","-y","base-devel","openssl-devel","libffi-devel"),
        "termux":  ["pkg","install","-y","clang","openssl","libffi"],
        "nix":     ["nix-env","-iA","nixpkgs.gcc","nixpkgs.openssl"],
        "macos":   None,   # handled separately via xcode-select
        "windows": None,   # wheels cover Windows — no compiler needed normally
    }
    fam = P.distro_family
    cmd = cmds.get(fam)
    if cmd is None:
        if fam == "macos":
            return _ok_run(["xcode-select","--install"])
        return True  # Windows: wheels handle it
    return _ok_run(cmd)

# ── Rust ──────────────────────────────────────────────────────────────────────

def install_rust():
    # Try system package first
    sys_cmds = {
        "debian":  _sudo("apt-get","install","-y","rustc","cargo"),
        "fedora":  _sudo(P.pkg_manager,"install","-y","rust","cargo"),
        "arch":    _sudo("pacman","-S","--noconfirm","rust"),
        "alpine":  _sudo("apk","add","--no-cache","rust","cargo"),
        "suse":    _sudo("zypper","install","-y","rust","cargo"),
        "void":    _sudo("xbps-install","-y","rust"),
        "termux":  ["pkg","install","-y","rust"],
        "macos":   ["brew","install","rust"],
    }
    fam = P.distro_family
    if fam in sys_cmds and _ok_run(sys_cmds[fam]) and check_rust():
        return True

    # rustup fallback
    import urllib.request
    try:
        with urllib.request.urlopen("https://sh.rustup.rs") as resp:
            script = resp.read()
        with tempfile.NamedTemporaryFile(suffix=".sh", delete=False, mode="wb") as f:
            f.write(script); tmp = f.name
        os.chmod(tmp, 0o755)
        r = _run(["sh", tmp, "-y", "--no-modify-path"])
        os.unlink(tmp)
        # add cargo to PATH for this process
        cargo_bin = str(Path.home() / ".cargo" / "bin")
        os.environ["PATH"] = cargo_bin + os.pathsep + os.environ.get("PATH","")
        return r.returncode == 0
    except Exception:
        return False

# ── cryptography ──────────────────────────────────────────────────────────────

def install_cryptography():
    # Termux: try native package first (no compilation at all)
    if P.is_termux:
        if _ok_run(["pkg","install","-y","python-cryptography"]):
            return True

    # System package managers that ship cryptography
    sys_cmds = {
        "debian":  _sudo("apt-get","install","-y","python3-cryptography"),
        "fedora":  _sudo(P.pkg_manager,"install","-y","python3-cryptography"),
        "arch":    _sudo("pacman","-S","--noconfirm","python-cryptography"),
        "alpine":  _sudo("apk","add","--no-cache","py3-cryptography"),
        "suse":    _sudo("zypper","install","-y","python3-cryptography"),
        "void":    _sudo("xbps-install","-y","python3-cryptography"),
        "nix":     ["nix-env","-iA","nixpkgs.python3Packages.cryptography"],
    }
    fam = P.distro_family
    if fam in sys_cmds:
        if _ok_run(sys_cmds[fam]):
            ok_val, _ = check_cryptography()
            if ok_val: return True

    # pip (preferred — gets latest version)
    pip = [sys.executable, "-m", "pip"]
    if _ok_run([*pip, "install", "--upgrade", "cryptography"]):
        return True

    # pip with --break-system-packages (needed on some distros)
    return _ok_run([*pip, "install", "--break-system-packages", "--upgrade", "cryptography"])

# ═══════════════════════════════════════════════════════════════════════════════
#  UI screens
# ══════════════════════════════════════════════════════════════════════════════

def screen_status():
    """Show current dependency status, return status dict."""
    clear()
    print(LOGO)

    print(f"  {bo('Detected platform:')}  {cy(str(P))}\n")

    st = gather_status()
    py_ok,  py_ver  = st["python"]
    pip_ok, _       = st["pip"]
    cc_ok,  _       = st["compiler"]
    rust_ok, rust_d = st["rust"]
    need_rust, _    = st["need_rust"]
    cry_ok, cry_ver = st["cryptography"]

    checks = []
    checks.append((f"Python {py_ver}", py_ok,
                   "" if py_ok else "need version 3.8 or newer"))
    checks.append(("pip  (package installer)", pip_ok,
                   "" if pip_ok else "will be installed automatically"))
    checks.append(("C compiler  (build tools)", cc_ok,
                   "" if cc_ok else "may be needed to build packages"))

    if need_rust:
        checks.append(("Rust / cargo", rust_ok,
                       "" if rust_ok else "required for this platform"))
    else:
        checks.append(("Rust / cargo", True,
                       "not needed — pre-built package available"))

    checks.append((f"cryptography {cry_ver}" if cry_ok else "cryptography",
                   cry_ok,
                   "" if cry_ok else "the only required Python package"))

    # NoEyes core files
    here = Path(__file__).parent
    core = ["noeyes.py","server.py","client.py","encryption.py",
            "identity.py","utils.py","config.py"]
    missing = [f for f in core if not (here / f).exists()]
    checks.append(("NoEyes core files", not missing,
                   "" if not missing else f"missing: {', '.join(missing)}"))

    lines = []
    all_good = True
    for label, ok_flag, detail in checks:
        icon = gr("✔") if ok_flag else rd("✘")
        det  = f"  {gy(detail)}" if detail else ""
        lines.append(f"{icon}  {label}{det}")
        if not ok_flag: all_good = False

    print(box("Dependency Status", lines, width=62))
    print()
    return st, all_good

def screen_confirm(st):
    """Ask what needs installing. Return list of (label, fn) pairs."""
    py_ok,  _        = st["python"]
    pip_ok, _        = st["pip"]
    cc_ok,  _        = st["compiler"]
    rust_ok,_        = st["rust"]
    need_rust, _     = st["need_rust"]
    cry_ok, _        = st["cryptography"]

    to_install = []

    if not py_ok:
        to_install.append(("Python 3.8+", None))   # can't self-install Python
    if not pip_ok:
        to_install.append(("pip", install_pip))
    if not cc_ok:
        to_install.append(("Build tools  (C compiler + headers)", install_compiler))
    if need_rust and not rust_ok:
        to_install.append(("Rust / cargo", install_rust))
    if not cry_ok:
        to_install.append(("cryptography  (PyPI)", install_cryptography))

    if not to_install:
        return []

    print(box("Ready to Install",
        [f"{gy('·')}  {item[0]}" for item in to_install] +
        ["",
         "NoEyes needs these to run. Nothing else will be",
         "installed or changed on your system."],
        colour=cy))
    print()

    if not confirm("Install everything now?", default=True):
        return None   # user said no

    return to_install

def screen_install(to_install):
    """Run each installer with a live spinner. Returns True if all succeeded."""
    print()
    results = []

    for label, fn in to_install:
        if fn is None:
            print(f"  {rd('✘')}  {bo(label)}")
            print(f"      {gy('Cannot be installed automatically.')}")
            print(f"      {gy('Please install Python 3.8+ manually and re-run setup.py.')}")
            print(f"      {gy('https://www.python.org/downloads/')}")
            results.append(False)
            continue

        ok_flag = spinner_line(f"Installing {label}", fn)
        if ok_flag:
            print(f"  {gr('✔')}  {bo(label)}")
        else:
            print(f"  {rd('✘')}  {bo(label)}  {gy('— failed (see details below)')}")
        results.append(ok_flag)

    return all(results)

def screen_done(success):
    clear()
    print(LOGO)
    if success:
        print(box("Setup Complete", [
            gr("✔  All dependencies installed successfully."),
            "",
            f"Run  {cy(bo('python launch.py'))}  to start NoEyes.",
        ], colour=gr))
    else:
        print(box("Setup Incomplete", [
            rd("✘  One or more steps failed."),
            "",
            "Check the errors above.",
            "Try running with administrator / sudo permissions,",
            "or install the missing packages manually.",
            "",
            f"Re-run  {cy(bo('python setup.py'))}  after fixing any issues.",
        ], colour=yl))
    print()

def screen_check_only():
    """--check mode: show status and exit."""
    st, all_good = screen_status()
    if all_good:
        print(f"  {gr(bo('All good!'))}  NoEyes is ready to run.\n")
        print(f"  {gy('Run:  python launch.py')}\n")
    else:
        print(f"  {yl('Some dependencies are missing.')}")
        print(f"  {gy('Run  python setup.py  to install them.')}\n")

def screen_already_done():
    clear()
    print(LOGO)
    print(box("Already Installed", [
        gr("✔  All dependencies are already installed."),
        "",
        f"Run  {cy(bo('python launch.py'))}  to start NoEyes.",
        "",
        gy("To force a reinstall:  python setup.py --force"),
    ], colour=gr))
    print()

# ══════════════════════════════════════════════════════════════════════════════
#  Force-reinstall screen
# ══════════════════════════════════════════════════════════════════════════════

def screen_force():
    clear()
    print(LOGO)
    print(box("Force Reinstall",
        ["This will reinstall cryptography even if it's already present.",
         "", gy("pip, build tools, and Rust are skipped if already installed.")],
        colour=yl))
    print()
    if not confirm("Reinstall cryptography?", default=True):
        return
    print()
    ok_flag = spinner_line("Reinstalling cryptography", install_cryptography)
    if ok_flag:
        print(f"  {gr('✔')}  cryptography reinstalled")
    else:
        print(f"  {rd('✘')}  reinstall failed")
    print()

# ══════════════════════════════════════════════════════════════════════════════
#  Main wizard
# ══════════════════════════════════════════════════════════════════════════════

def main_wizard():
    import argparse
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("--check",   action="store_true")
    ap.add_argument("--force",   action="store_true")
    ap.add_argument("--no-rust", action="store_true")
    args, _ = ap.parse_known_args()

    hide_cursor()

    try:
        if args.check:
            screen_check_only()
            return

        if args.force:
            screen_force()
            pause()
            return

        # ── scan status ───────────────────────────────────────────────────────
        st, all_good = screen_status()

        if all_good:
            screen_already_done()
            pause()
            return

        # ── confirm install ───────────────────────────────────────────────────
        to_install = screen_confirm(st)

        if to_install is None:
            clear()
            print(LOGO)
            print(f"  {gy('Installation cancelled.')}\n")
            print(f"  Run {cy(bo('python setup.py'))} whenever you are ready.\n")
            return

        if not to_install:
            screen_already_done()
            pause()
            return

        # drop Rust if --no-rust
        if args.no_rust:
            to_install = [(l, f) for l, f in to_install if "rust" not in l.lower()]

        # ── install ───────────────────────────────────────────────────────────
        print()
        success = screen_install(to_install)
        print()

        # ── re-check ─────────────────────────────────────────────────────────
        _, now_good = screen_status()
        screen_done(now_good)
        pause()

    except KeyboardInterrupt:
        clear()
        show_cursor()
        print(f"\n  {gy('Goodbye.')}\n")
    finally:
        show_cursor()

if __name__ == "__main__":
    main_wizard()
