# FILE: utils.py
"""
utils.py — Terminal utilities, ANSI colors, and the NoEyes ASCII banner.
"""

import sys
import os
import time
import random
import re
import threading

# ---------------------------------------------------------------------------
# ANSI color helpers
# ---------------------------------------------------------------------------

RESET        = "\033[0m"
BOLD         = "\033[1m"
RED          = "\033[31m"
GREEN        = "\033[32m"
YELLOW       = "\033[33m"
CYAN         = "\033[36m"
WHITE        = "\033[37m"
GREY         = "\033[90m"
PURPLE       = "\033[35m"
BRIGHT_WHITE = "\033[1;37m"


def _is_tty() -> bool:
    """True if we are attached to a real terminal (robust check)."""
    try:
        return os.isatty(sys.stdout.fileno())
    except Exception:
        return False


def colorize(text: str, color: str, bold: bool = False) -> str:
    """Wrap *text* with ANSI escape codes if stdout is a TTY."""
    if not _is_tty():
        return text
    prefix = BOLD if bold else ""
    return f"{prefix}{color}{text}{RESET}"


def cinfo(msg: str) -> str:
    return colorize(msg, CYAN)


def cwarn(msg: str) -> str:
    return colorize(msg, YELLOW, bold=True)


def cerr(msg: str) -> str:
    return colorize(msg, RED, bold=True)


def cok(msg: str) -> str:
    return colorize(msg, GREEN)


def cgrey(msg: str) -> str:
    return colorize(msg, GREY)


# ---------------------------------------------------------------------------
# Screen helpers
# ---------------------------------------------------------------------------


def clear_screen() -> None:
    """Clear the terminal screen (cross-platform)."""
    os.system("cls" if os.name == "nt" else "clear")


# ---------------------------------------------------------------------------
# ASCII banner
# ---------------------------------------------------------------------------

BANNER = r"""
 _   _       _____
| \ | | ___ | ____|_   _  ___  ___
|  \| |/ _ \|  _| | | | |/ _ \/ __|
| |\  | (_) | |___| |_| |  __/\__ \
|_| \_|\___/|_____|\__, |\___||___/
                   |___/
  Secure Terminal Chat  |  E2E Encrypted
"""


def print_banner() -> None:
    """Print the ASCII banner with colour if the terminal supports it."""
    print(colorize(BANNER, CYAN, bold=True))


# ---------------------------------------------------------------------------
# Decrypt animation
#
# Two-phase cinematic effect on every incoming message:
#
#   Phase 1 — CIPHER: exactly len(plaintext) random characters from a
#              cinematic noise pool stream out in shifting purple/magenta.
#              Each char picks a different shade — not a flat block of colour.
#
#   Phase 2 — REVEAL: cursor rewinds (save/restore — works after line-wrap)
#              and the real plaintext types over the cipher position-by-
#              position.  Each character flashes bright-white for one tick
#              then settles to normal: the "lock-in" feel.
#
# A threading.Lock() serialises concurrent messages so two animations never
# interleave.  chat and privmsg share a single _run_animation() core.
#
# Toggle: /anim on|off  (stored in NoEyesClient._anim_enabled)
# Non-TTY: animation skipped entirely — plain print, no side effects.
# ---------------------------------------------------------------------------

# Character pool — box-drawing, block-elements, braille dots, symbol noise.
# No letters/digits: looks like encrypted noise, not garbled plaintext.
_CIPHER_POOL = list(
    "─│┌┐└┘├┤┬┴┼╔╗╚╝╠╣╦╩╬═║╒╓╕╖╘╙╛╜╞╟╡╢╤╥╧╨╪╫"
    "░▒▓█▀▄▌▐▖▗▘▙▚▛▜▝▞▟"
    "⠿⠾⠽⠻⠷⠯⠟⡿⢿"
    "!#$%&*+/<=>?@^~|*+-=<>{}[]"
    "·×÷±∑∏∂∇∞∴≈≠≡≤≥"
)

# Purple/blue/teal shades — each cipher char picks one randomly
_CIPHER_COLORS = [
    "\033[35m",    # purple
    "\033[1;35m",  # bright purple
    "\033[95m",    # light magenta
    "\033[34m",    # dark blue
    "\033[1;34m",  # bright blue
    "\033[36m",    # teal
]

# ── Timing ──────────────────────────────────────────────────────────────────
_CIPHER_CHAR_DELAY = 0.022   # s per cipher char
_REVEAL_PAUSE      = 0.38    # s pause between phases (the "moment of decryption")
_PLAIN_CHAR_MAX    = 0.060   # s per plaintext char (cap for short messages)
_PLAIN_TOTAL_CAP   = 2.0     # s max total for the whole plaintext phase
_FLASH_DUR         = 0.028   # s a char stays bright-white before settling

# VT100 cursor save/restore — supported by every modern terminal
_CUR_SAVE    = "\033[s"
_CUR_RESTORE = "\033[u"
_CUR_BACK1   = "\033[1D"
_ERASE_EOL   = "\033[K"

# Serialise all animation writes so concurrent arrivals never interleave
_ANIM_LOCK = threading.Lock()


def _run_animation(prefix: str, plaintext: str) -> None:
    """
    Core two-phase animation.  Called with _ANIM_LOCK already held.

    prefix    — formatted '[ts] user: ' string (may contain ANSI codes)
    plaintext — decrypted message text
    """
    n = len(plaintext)
    if n == 0:
        sys.stdout.write(prefix + "\n")
        sys.stdout.flush()
        return

    # ── Phase 1: cipher noise, exactly n chars ───────────────────────────────
    # Print prefix then save cursor position so Phase 2 can rewind even if
    # the cipher chars caused the line to wrap.
    sys.stdout.write(prefix + _CUR_SAVE)
    sys.stdout.flush()

    for _ in range(n):
        ch    = random.choice(_CIPHER_POOL)
        color = random.choice(_CIPHER_COLORS)
        sys.stdout.write(color + ch + RESET)
        sys.stdout.flush()
        time.sleep(_CIPHER_CHAR_DELAY)

    time.sleep(_REVEAL_PAUSE)

    # ── Phase 2: restore cursor, type plaintext with lock-in flash ───────────
    sys.stdout.write(_CUR_RESTORE)
    sys.stdout.flush()

    per_char   = min(_PLAIN_CHAR_MAX, _PLAIN_TOTAL_CAP / n)
    settle_dur = max(0.0, per_char - _FLASH_DUR)

    for ch in plaintext:
        # Char appears bright-white ("locks in")
        sys.stdout.write(BRIGHT_WHITE + ch + RESET)
        sys.stdout.flush()
        time.sleep(_FLASH_DUR)

        # Step back one column and rewrite in normal colour (settles)
        sys.stdout.write(_CUR_BACK1 + ch)
        sys.stdout.flush()
        time.sleep(settle_dur)

    # Erase any residual cipher chars (guards emoji/wide-char edge cases)
    sys.stdout.write(_ERASE_EOL + "\n")
    sys.stdout.flush()


def chat_decrypt_animation(
    payload_bytes: bytes,
    plaintext: str,
    from_user: str,
    msg_ts: str,
    anim_enabled: bool = True,
) -> None:
    """Display an incoming group-chat message with the decrypt animation."""
    ts_part   = cgrey(f"[{msg_ts}]")
    user_part = colorize(from_user, GREEN, bold=True)
    prefix    = f"{ts_part} {user_part}: "

    if not anim_enabled or not _is_tty():
        print(prefix + plaintext)
        return

    with _ANIM_LOCK:
        _run_animation(prefix, plaintext)


def privmsg_decrypt_animation(
    payload_bytes: bytes,
    plaintext: str,
    from_user: str,
    msg_ts: str,
    verified: bool = False,
    anim_enabled: bool = True,
) -> None:
    """Display an incoming private message with the decrypt animation."""
    ts_part  = cgrey(f"[{msg_ts}]")
    src_part = colorize(f"[PM from {from_user}]", CYAN, bold=True)
    sig_part = cok("✓") if verified else cwarn("?")
    prefix   = f"{ts_part} {src_part}{sig_part} "

    if not anim_enabled or not _is_tty():
        print(prefix + plaintext)
        return

    with _ANIM_LOCK:
        _run_animation(prefix, plaintext)


# ---------------------------------------------------------------------------
# Misc helpers
# ---------------------------------------------------------------------------


def format_message(username: str, text: str, timestamp: str) -> str:
    """Format a chat line for display."""
    ts  = cgrey(f"[{timestamp}]")
    usr = colorize(username, GREEN, bold=True)
    return f"{ts} {usr}: {text}"


def format_system(text: str, timestamp: str) -> str:
    """Format a system/event line for display."""
    ts = cgrey(f"[{timestamp}]")
    tag = colorize("[SYSTEM]", YELLOW, bold=True)
    return f"{ts} {tag} {text}"


def format_privmsg(from_user: str, text: str, timestamp: str, verified: bool) -> str:
    """Format a private message line, noting signature status."""
    ts  = cgrey(f"[{timestamp}]")
    src = colorize(f"[PM from {from_user}]", CYAN, bold=True)
    sig = cok("✓") if verified else cwarn("?")
    return f"{ts} {src}{sig} {text}"
