# FILE: noeyes.py
"""
noeyes.py — NoEyes entry point.

Usage:
    python noeyes.py --server [--port PORT] [--no-bore] [--key PASS | --key-file PATH]
    python noeyes.py --connect HOST [--port PORT] [--key PASS | --key-file PATH]
    python noeyes.py --gen-key --key-file PATH
"""

import logging
import os
import sys
from getpass import getpass

from core import config as cfg_mod
from core import encryption as enc
from core import utils
from core import firewall as fw

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
# Keep the noeyes.server logger at INFO for join/leave/listen events,
# but make sure raw IP addresses never appear at INFO level — see server.py.
logging.getLogger("noeyes.server").setLevel(logging.INFO)


def _resolve_fernet(cfg: dict):
    """
    Derive or load a group Fernet key.

    Priority: --key-file > --key > interactive passphrase prompt.
    """
    from cryptography.fernet import Fernet

    if cfg.get("key_file"):
        return enc.load_key_file(cfg["key_file"])  # returns (Fernet, key_bytes)

    passphrase = cfg.get("key")
    if not passphrase:
        if sys.stdin.isatty():
            passphrase = getpass("Shared passphrase: ")
            confirm    = getpass("Confirm passphrase: ")
            if passphrase != confirm:
                print(utils.cerr("[error] Passphrases do not match."))
                sys.exit(1)
        else:
            print(utils.cerr("[error] No key or key-file provided."))
            sys.exit(1)
    else:
        # Security warning: the passphrase is visible in `ps aux` and in
        # shell history to any local user who can read /proc/<pid>/cmdline.
        # --key-file is always safer — the passphrase never touches argv.
        print(utils.cwarn(
            "[security] WARNING: passphrase passed via --key is visible in\n"
            "           `ps aux` and shell history. Use --key-file instead:\n"
            "             python noeyes.py --gen-key --key-file ./chat.key\n"
            "             python noeyes.py --connect HOST --key-file ./chat.key"
        ))

    # ── Secure key derivation ──────────────────────────────────────────────────
    # Instead of re-deriving from the passphrase on every run (which would
    # reuse the same static salt each time), we derive ONCE with a fresh random
    # salt, save the result to a key file, and use the key file from then on.
    #
    # This means:
    #   - Each deployment gets a unique random salt → rainbow tables are useless.
    #   - After the first run the passphrase is no longer needed.
    #   - Other users should receive the generated key FILE, not the passphrase.
    #
    # Key file is saved to --key-file path if provided, otherwise to the
    # default location ~/.noeyes/derived.key.
    import os as _os
    from pathlib import Path as _Path

    save_path = cfg.get("key_file") or "~/.noeyes/derived.key"
    save_p    = _Path(save_path).expanduser()

    if save_p.exists():
        # Key file already exists from a previous run — load it directly.
        # No PBKDF2 re-derivation, no static salt.
        return enc.load_key_file(save_path)  # returns (Fernet, key_bytes)

    # First run with this passphrase: derive key with fresh random salt and save.
    fernet, key_bytes = enc.derive_and_save_key_file(save_path, passphrase)
    print(utils.cok(
        f"[keygen] Passphrase derived and saved to {save_p}\n"
        f"         Share this file (not the passphrase) with other users:\n"
        f"           python noeyes.py --connect HOST --key-file {save_p}"
    ))
    return fernet, key_bytes


def _get_username(cfg: dict) -> str:
    uname = cfg.get("username")
    if uname:
        return uname.strip()[:32]
    if sys.stdin.isatty():
        uname = input("Username: ").strip()[:32]
    if not uname:
        import random, string
        uname = "user_" + "".join(random.choices(string.ascii_lowercase, k=5))
    return uname


def _start_bore(port: int) -> None:
    """
    Launch bore in background and print the public address once it appears.
    Silently skips if bore is not installed.
    """
    import subprocess, threading, shutil, re

    import sys as _sys, os as _os
    from pathlib import Path as _Path
    cargo_bin  = str(_Path.home() / ".cargo" / "bin")
    bore_exe   = _Path.home() / ".cargo" / "bin" / ("bore.exe" if _sys.platform == "win32" else "bore")
    bore_cmd   = shutil.which("bore")

    # On Windows the PATH may not be refreshed yet — fall back to direct path
    if not bore_cmd and bore_exe.exists():
        bore_cmd = str(bore_exe)
        # Also add to session PATH so child process inherits it
        if cargo_bin not in _os.environ.get("PATH", ""):
            _os.environ["PATH"] = cargo_bin + _os.pathsep + _os.environ.get("PATH", "")

    if not bore_cmd:
        print(utils.cgrey(
            "[bore] not installed — run without tunnel.\n"
            "       Install: https://github.com/ekzhang/bore (see README)"
        ))
        return

    def _run():
        import time as _time
        # On Windows: use STARTUPINFO to hide the bore console window
        # WITHOUT using CREATE_NO_WINDOW or DETACHED_PROCESS which can
        # cause Windows Terminal to minimize the parent window.
        kwargs = {}
        if _sys.platform == "win32":
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            si.wShowWindow = 0  # SW_HIDE
            kwargs["startupinfo"] = si

        try:
            proc = subprocess.Popen(
                [bore_cmd, "local", str(port), "--to", "bore.pub"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,   # separate stderr so we can log errors
                text=True,
                **kwargs,
            )

            # Drain stderr in a separate thread so it never blocks bore
            def _drain_stderr():
                for err_line in proc.stderr:
                    err_line = err_line.strip()
                    if err_line:
                        print(utils.cgrey(f"[bore] {err_line}"), flush=True)
            threading.Thread(target=_drain_stderr, daemon=True).start()

            _root = str(_Path(__file__).parent)
            _key = "./chat.key"
            if (_Path(__file__).parent / "ui" / "chat.key").exists() and not (_Path(__file__).parent / "chat.key").exists():
                _key = "./ui/chat.key"

            announced = False
            for line in proc.stdout:
                m = re.search(r"bore\.pub:(\d+)", line)
                if m and not announced:
                    p = m.group(1)
                    announced = True
                    print(utils.cinfo(
                        f"\n  ┌─ bore tunnel active ─────────────────────────────────────────\n"
                        f"  │  address : bore.pub:{p}\n"
                        f"  │\n"
                        f"  │  Share this with anyone who wants to connect:\n"
                        f"  │\n"
                        f"  │    1. cd {_root}\n"
                        f"  │    2. python noeyes.py --connect bore.pub --port {p} --key-file {_key}\n"
                        f"  │\n"
                        f"  │  They also need a copy of the key file ({_key})\n"
                        f"  └──────────────────────────────────────────────────────────────\n"
                    ), flush=True)
                # Keep draining stdout — never break, so the pipe never fills
                # and Windows doesn't kill bore due to a blocked pipe buffer.

            # Loop exited — bore process died
            code = proc.wait()
            print(utils.cwarn(f"[bore] tunnel closed (exit {code}) — restarting in 5s…"), flush=True)
            _time.sleep(5)

        except Exception as e:
            print(utils.cgrey(f"[bore] failed to start: {e}"), flush=True)

    def _run_with_restart():
        """Keep bore alive — restart it if it crashes."""
        while True:
            _run()

    threading.Thread(target=_run_with_restart, daemon=True).start()


def run_server(cfg: dict) -> None:
    import atexit, signal as _signal
    from network.server import NoEyesServer

    _port       = cfg["port"]
    _no_fw      = cfg.get("no_firewall", False)

    # Open firewall rule for the server port (skip if --no-firewall)
    if not _no_fw:
        fw.open_port(_port)
        atexit.register(fw.close_port, _port)

    # Also close on SIGINT / SIGTERM so Ctrl-C and kill both clean up
    def _sig_handler(signum, frame):
        if not _no_fw:
            fw.close_port(_port)
        sys.exit(0)
    try:
        _signal.signal(_signal.SIGINT,  _sig_handler)
        _signal.signal(_signal.SIGTERM, _sig_handler)
    except (OSError, ValueError):
        pass  # signal setup can fail inside threads; atexit still covers it

    server = NoEyesServer(
        host="0.0.0.0",
        port=cfg["port"],
        history_size=cfg["history_size"],
        rate_limit_per_minute=cfg["rate_limit_per_minute"],
        ssl_cert=cfg.get("cert") or "",
        ssl_key=cfg.get("tls_key") or "",
        no_tls=cfg.get("no_tls", False),
    )

    if cfg.get("daemon"):
        _daemonize()

    if cfg.get("no_bore"):
        # --no-bore was passed: skip the tunnel entirely and explain why that
        # can be the right choice (LAN server, static IP, custom tunnel, etc.).
        print(utils.cgrey(
            "[bore] tunnel disabled via --no-bore.\n"
            "       Clients on the same network can connect directly:\n"
            f"       python noeyes.py --connect <YOUR-IP> --port {cfg['port']} --key-file ./chat.key"
        ))
    else:
        _start_bore(cfg["port"])

    server.run()


TLS_TOFU_PATH = "~/.noeyes/tls_fingerprints.json"


def _resolve_tls_for_client(host: str, port: int, no_tls: bool) -> tuple:
    """
    Resolve TLS settings for a client connection.

    Returns (tls: bool, tls_cert: str) where tls_cert is a path to the
    server's cert if we have it cached, or empty string to use TOFU mode.

    How it works:
      1. Client connects with TLS but without certificate verification
         (check_hostname=False, verify_mode=CERT_NONE).
      2. After the handshake, it reads the server's cert fingerprint.
      3. On first connection: stores the fingerprint and trusts it.
      4. On subsequent connections: verifies the fingerprint matches.
      5. If fingerprint changed: warns the user (possible MITM).

    This mirrors SSH host-key verification — transport is always encrypted,
    and the server's identity is pinned after first contact.
    """
    if no_tls:
        return False, ""
    return True, ""   # tls=True, cert="" → client uses TOFU mode


def run_client(cfg: dict) -> None:
    from network.client import NoEyesClient

    group_fernet, group_key_bytes = _resolve_fernet(cfg)
    username     = _get_username(cfg)

    no_tls = cfg.get("no_tls", False)
    tls, tls_cert = _resolve_tls_for_client(cfg["connect"], cfg["port"], no_tls)

    client = NoEyesClient(
        host=cfg["connect"],
        port=cfg["port"],
        username=username,
        group_fernet=group_fernet,
        group_key_bytes=group_key_bytes,
        room=cfg["room"],
        identity_path=cfg["identity_path"],
        tofu_path=cfg["tofu_path"],
        tls=tls,
        tls_cert=tls_cert,
        tls_tofu_path=TLS_TOFU_PATH,
    )
    client.run()


def run_gen_key(cfg: dict) -> None:
    path = cfg.get("key_file")
    if not path:
        print(utils.cerr("[error] --gen-key requires --key-file PATH"))
        sys.exit(1)
    enc.generate_key_file(path)


def _daemonize() -> None:
    """Double-fork to create a background daemon (Unix only)."""
    if os.name != "posix":
        print(utils.cwarn("[warn] --daemon is not supported on Windows; ignoring."))
        return
    pid = os.fork()
    if pid > 0:
        sys.exit(0)
    os.setsid()
    pid = os.fork()
    if pid > 0:
        sys.exit(0)
    sys.stdin  = open(os.devnull)
    sys.stdout = open(os.devnull, "w")
    sys.stderr = open(os.devnull, "w")


def main(argv=None) -> None:
    cfg = cfg_mod.load_config(argv)

    if cfg["gen_key"]:
        run_gen_key(cfg)
        return

    if cfg["server"]:
        fw.check_stale()
        run_server(cfg)
        return

    if cfg["connect"]:
        run_client(cfg)
        return

    # No mode selected
    cfg_mod.build_arg_parser().print_help()
    sys.exit(1)


if __name__ == "__main__":
    main()
