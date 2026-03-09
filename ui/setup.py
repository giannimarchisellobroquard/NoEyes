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

def check_bore():
    """Return True if bore binary is on PATH or in ~/.cargo/bin.
    On Windows, also fixes the permanent PATH if bore exists but isn't registered."""
    cargo_bin = str(Path.home() / ".cargo" / "bin")
    bore_exe  = Path.home() / ".cargo" / "bin" / ("bore.exe" if sys.platform == "win32" else "bore")

    # If bore.exe exists on disk but isn't in the permanent Windows PATH, fix it silently
    if sys.platform == "win32" and bore_exe.exists():
        added = _add_to_windows_path_permanently(cargo_bin)
        if added:
            print(f"  {cy('PATH')} updated — added {gy(cargo_bin)} to your Windows user PATH")
            print(f"  {gy('Open a new terminal for this to take effect in new windows.')}")

    env = os.environ.copy()
    if cargo_bin not in env.get("PATH", ""):
        env["PATH"] = cargo_bin + os.pathsep + env.get("PATH", "")
    try:
        r = subprocess.run(["bore", "--version"], capture_output=True, env=env)
        return r.returncode == 0
    except FileNotFoundError:
        return bore_exe.exists()  # exe is there but PATH not refreshed yet — still counts

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

    bore_ok = check_bore()
    return {
        "python":       (py_ok,       py_ver),
        "pip":          (pip_ok,      "python -m pip"),
        "compiler":     (cc_ok,       "gcc / clang / MSVC"),
        "rust":         (rust_ok,     "cargo" if rust_ok else
                         ("not needed — pre-built wheel available" if not need_rust
                          else "needed for this platform")),
        "need_rust":    (need_rust,   ""),
        "cryptography": (crypto_ok,   cv if crypto_ok else "not installed"),
        "bore":         (bore_ok,     "bore.pub tunnel" if bore_ok else "optional — needed to host a server online"),
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

# ── bore ─────────────────────────────────────────────────────────────────────



def _add_to_windows_path_permanently(directory):
    """Add a directory to the Windows user PATH permanently via the registry."""
    if sys.platform != "win32":
        return
    directory = str(directory)
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Environment",
            0, winreg.KEY_READ | winreg.KEY_WRITE
        )
        try:
            current, _ = winreg.QueryValueEx(key, "Path")
        except FileNotFoundError:
            current = ""
        if directory.lower() not in current.lower():
            new_path = current + ";" + directory if current else directory
            winreg.SetValueEx(key, "Path", 0, winreg.REG_EXPAND_SZ, new_path)
            winreg.CloseKey(key)
            # Notify running programs of the PATH change
            try:
                import ctypes
                HWND_BROADCAST = 0xFFFF
                WM_SETTINGCHANGE = 0x001A
                ctypes.windll.user32.SendMessageTimeoutW(
                    HWND_BROADCAST, WM_SETTINGCHANGE, 0, "Environment", 2, 5000, None
                )
            except Exception:
                pass
            return True  # was added
        winreg.CloseKey(key)
        return False  # already there
    except Exception:
        return False

def _install_bore_windows(cargo_bin):
    """Download pre-built bore.exe from GitHub releases — no Rust compiler needed."""
    import urllib.request, zipfile, tempfile, shutil
    
    # Get latest release tag from GitHub API
    api_url = "https://api.github.com/repos/ekzhang/bore/releases/latest"
    try:
        req = urllib.request.Request(api_url, headers={"User-Agent": "NoEyes-installer"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            import json
            data = json.loads(resp.read())
            tag = data["tag_name"]  # e.g. "v0.5.0"
    except Exception as e:
        return False, f"Could not fetch bore release info: {e}"

    zip_url = f"https://github.com/ekzhang/bore/releases/download/{tag}/bore-{tag}-x86_64-pc-windows-msvc.zip"
    try:
        tmp_zip = str(Path(tempfile.gettempdir()) / "bore-windows.zip")
        with urllib.request.urlopen(zip_url, timeout=60) as resp:
            open(tmp_zip, "wb").write(resp.read())
        
        # Extract bore.exe to ~/.cargo/bin (already on PATH from cargo installs)
        dest_dir = Path.home() / ".cargo" / "bin"
        dest_dir.mkdir(parents=True, exist_ok=True)
        
        with zipfile.ZipFile(tmp_zip) as zf:
            for name in zf.namelist():
                if name.endswith("bore.exe") or name == "bore.exe":
                    with zf.open(name) as src, open(dest_dir / "bore.exe", "wb") as dst:
                        dst.write(src.read())
                    break
        
        os.unlink(tmp_zip)
        
        # Add to PATH for this session and permanently in Windows registry
        cargo_bin_str = str(dest_dir)
        if cargo_bin_str not in os.environ.get("PATH", ""):
            os.environ["PATH"] = cargo_bin_str + os.pathsep + os.environ.get("PATH", "")
        _add_to_windows_path_permanently(cargo_bin_str)
        
        bore_exe = dest_dir / "bore.exe"
        if bore_exe.exists():
            return True, str(bore_exe)
        return False, "bore.exe not found after extraction"
    except Exception as e:
        return False, str(e)

def install_bore():
    """
    Install bore-cli via cargo — no sudo required anywhere.

    Strategy:
      1. If cargo is already available, run: cargo install bore-cli
      2. If cargo is not available, install Rust via rustup (no sudo),
         then run: cargo install bore-cli
      3. On Termux, try pkg first (bore may be packaged).
      4. On any platform, rustup --no-modify-path is always used so we
         never touch system files.
    """
    # Windows: download pre-built exe (no compiler needed)
    if sys.platform == "win32":
        print(f"  {cy('Windows')}: downloading pre-built bore.exe from GitHub...")
        success, result = _install_bore_windows(str(Path.home() / ".cargo" / "bin"))
        if success:
            print(f"  bore installed: {result}")
            print("  NOTE: open a NEW terminal for bore to be recognised in PATH")
            return True
        print(f"  Pre-built download failed ({result}) — trying cargo compile...")

    # Termux: try native package (no compilation needed)
    if P.is_termux:
        if _ok_run(["pkg", "install", "-y", "bore"]):
            return check_bore()

    # Ensure cargo is available (install via rustup if not)
    cargo_bin = str(Path.home() / ".cargo" / "bin")
    cargo_env = os.environ.copy()
    if cargo_bin not in cargo_env.get("PATH", ""):
        cargo_env["PATH"] = cargo_bin + os.pathsep + cargo_env.get("PATH", "")

    cargo_ok = False
    try:
        r = subprocess.run(["cargo", "--version"], capture_output=True, env=cargo_env)
        cargo_ok = r.returncode == 0
    except FileNotFoundError:
        pass

    if not cargo_ok:
        # Install Rust via rustup — completely user-local, no sudo
        import urllib.request, tempfile
        try:
            if sys.platform == "win32":
                # Windows needs rustup-init.exe, not the shell script
                url = "https://static.rust-lang.org/rustup/dist/x86_64-pc-windows-msvc/rustup-init.exe"
                tmp = str(Path(tempfile.gettempdir()) / "rustup-init.exe")
                with urllib.request.urlopen(url) as resp:
                    open(tmp, "wb").write(resp.read())
                r = _run([tmp, "-y", "--no-modify-path"])
            else:
                with urllib.request.urlopen("https://sh.rustup.rs") as resp:
                    script = resp.read()
                with tempfile.NamedTemporaryFile(suffix=".sh", delete=False, mode="wb") as f:
                    f.write(script); tmp = f.name
                os.chmod(tmp, 0o755)
                r = _run(["sh", tmp, "-y", "--no-modify-path"])
            try:
                os.unlink(tmp)
            except Exception:
                pass
            if r.returncode != 0:
                return False
            os.environ["PATH"] = cargo_bin + os.pathsep + os.environ.get("PATH", "")
            cargo_env["PATH"] = cargo_bin + os.pathsep + cargo_env.get("PATH", "")
        except Exception:
            return False

    # Install bore-cli via cargo (installs to ~/.cargo/bin — no sudo)
    r = subprocess.run(
        ["cargo", "install", "bore-cli"],
        capture_output=False, env=cargo_env
    )
    if r.returncode == 0:
        # Make sure bore is in this process's PATH too
        if cargo_bin not in os.environ.get("PATH", ""):
            os.environ["PATH"] = cargo_bin + os.pathsep + os.environ.get("PATH", "")
        # Permanently add to Windows user PATH so new terminals see it
        if sys.platform == "win32":
            _add_to_windows_path_permanently(cargo_bin)
        # Also check directly — PATH may not refresh in same terminal session
        bore_bin = Path.home() / ".cargo" / "bin" / ("bore.exe" if sys.platform == "win32" else "bore")
        if check_bore() or bore_bin.exists():
            if sys.platform == "win32":
                print(f"  NOTE: open a NEW terminal for bore to be recognised in PATH")
            return True
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

    bore_ok, bore_d = st["bore"]
    if bore_ok:
        checks.append(("bore  (online tunnel)", bore_ok, "ready — bore.pub tunnel available"))
    else:
        checks.append(("bore  (online tunnel)", None,
                       "optional — install if you want to host a server online"))

    # NoEyes core files — check against new folder structure
    root = Path(__file__).parent.parent
    core = [
        "noeyes.py",
        "network/server.py",
        "network/client.py",
        "core/encryption.py",
        "core/identity.py",
        "core/utils.py",
        "core/config.py",
    ]
    missing = [f for f in core if not (root / f).exists()]
    checks.append(("NoEyes core files", not missing,
                   "" if not missing else f"missing: {', '.join(missing)}"))

    lines = []
    all_good = True
    for label, ok_flag, detail in checks:
        if ok_flag is None:
            # Optional item — show as grey info, not a red failure
            icon = gy("·")
            det  = f"  {gy(detail)}" if detail else ""
            lines.append(f"{icon}  {label}{det}")
        else:
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

    bore_ok, _ = st["bore"]

    # ── Optional: bore tunnel ────────────────────────────────────────────────
    want_bore = False
    if not bore_ok:
        print(box("bore — Online Server Tunnel  (optional)", [
            gy("bore pub lets you host a NoEyes server online without"),
            gy("port-forwarding or a static IP. Your ISP or mobile data"),
            gy("provider may block inbound connections — bore bypasses that."),
            "",
            gy("bore is open-source, free, and installs to ~/.cargo/bin"),
            gy("(no sudo required on any platform)."),
            "",
            gy("You only need this if you plan to RUN a server."),
            gy("Clients connecting to someone else's server don't need it."),
            "",
            cy("Credit: Eric Zhang — https://github.com/ekzhang/bore"),
        ], colour=gy))
        print()
        want_bore = confirm("Install bore? (recommended for server operators)", default=False)
        print()

    if not to_install and not want_bore:
        return []

    items_display = [f"{gy('·')}  {item[0]}" for item in to_install]
    if want_bore:
        items_display.append(f"{gy('·')}  bore  (online tunnel via bore.pub)")

    print(box("Ready to Install", items_display + [
        "",
        "NoEyes needs the required items to run.",
        "bore is optional — only needed to host a server online.",
        "Nothing else will be installed or changed on your system.",
    ], colour=cy))
    print()

    if not confirm("Install everything now?", default=True):
        return None   # user said no

    if want_bore:
        to_install.append(("bore  (online tunnel)", install_bore))

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
        bore_ok = check_bore()
        bore_line = (gr("✔  bore installed — ready to host online (bore.pub)")
                     if bore_ok else
                     gy("·  bore not installed — run setup.py again if you need it"))
        print(box("Setup Complete", [
            gr("✔  All dependencies installed successfully."),
            bore_line,
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
    bore_ok = check_bore()
    bore_line = (gr("✔  bore installed — bore.pub tunnel ready")
                 if bore_ok else
                 gy("·  bore not installed  (optional — needed to host a server online)"))
    print(box("Already Installed", [
        gr("✔  All dependencies are already installed."),
        bore_line,
        "",
        f"Run  {cy(bo('python launch.py'))}  to start NoEyes.",
        "",
        gy("To force a reinstall:  python setup.py --force"),
    ], colour=gr))
    print()
    # Even if everything else is installed, ask about bore if missing
    if not bore_ok:
        want = confirm("Install bore now? (lets you host a server online via bore.pub)", default=False)
        if want:
            print()
            ok_flag = spinner_line("Installing bore", install_bore)
            print()
            if ok_flag:
                print(f"  {gr('✔')}  bore installed — open a new terminal for it to be recognised in PATH")
            else:
                print(f"  {rd('✘')}  bore install failed — try again later")
            print()

# ══════════════════════════════════════════════════════════════════════════════
#  Force-reinstall screen
# ══════════════════════════════════════════════════════════════════════════════

def screen_force():
    clear()
    print(LOGO)
    bore_ok = check_bore()
    bore_status = gr("already installed") if bore_ok else gy("not installed")
    print(box("Force Reinstall",
        ["This will reinstall selected components even if already present.",
         "", gy("pip, build tools, and Rust are skipped if already installed."),
         "", f"bore status: {bore_status}"],
        colour=yl))
    print()
    do_crypto = confirm("Reinstall cryptography?", default=True)
    do_bore   = confirm(f"{'Reinstall' if bore_ok else 'Install'} bore? (online tunnel)", default=not bore_ok)
    print()
    if do_crypto:
        ok_flag = spinner_line("Reinstalling cryptography", install_cryptography)
        print(f"  {gr('✔') if ok_flag else rd('✘')}  cryptography {'reinstalled' if ok_flag else 'failed'}")
        print()
    if do_bore:
        ok_flag = spinner_line(f"{'Reinstalling' if bore_ok else 'Installing'} bore", install_bore)
        print(f"  {gr('✔') if ok_flag else rd('✘')}  bore {'installed' if ok_flag else 'failed'}")
        if ok_flag:
            print(f"  {gy('NOTE: open a new terminal for bore to be recognised in PATH')}")
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

        if all_good and check_bore():
            # Everything including bore is installed — fully done
            screen_already_done()
            pause()
            return

        if all_good and not check_bore():
            # Deps done but bore missing — screen_already_done will ask
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
