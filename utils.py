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
from collections import defaultdict

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
    try:
        return os.isatty(sys.stdout.fileno())
    except Exception:
        return False


def colorize(text: str, color: str, bold: bool = False) -> str:
    if not _is_tty():
        return text
    prefix = BOLD if bold else ""
    return f"{prefix}{color}{text}{RESET}"


def cinfo(msg: str)  -> str: return colorize(msg, CYAN)
def cwarn(msg: str)  -> str: return colorize(msg, YELLOW, bold=True)
def cerr(msg: str)   -> str: return colorize(msg, RED,    bold=True)
def cok(msg: str)    -> str: return colorize(msg, GREEN)
def cgrey(msg: str)  -> str: return colorize(msg, GREY)


# ---------------------------------------------------------------------------
# Screen helpers
# ---------------------------------------------------------------------------

def clear_screen() -> None:
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
    print(colorize(BANNER, CYAN, bold=True))


# ---------------------------------------------------------------------------
# Global state — output lock + per-room message log + input buffer
#
# ALL terminal output goes through print_msg() which holds _OUTPUT_LOCK.
# read_line_noecho() shares _g_buf with print_msg() so incoming messages
# can erase the partial input, print, then redraw it seamlessly.
#
# Per-room log: every displayed message is stored in _room_logs[room].
# switch_room_display() clears the screen and reprints that room's log —
# no server history replay needed for room switches.
# ---------------------------------------------------------------------------

_OUTPUT_LOCK    = threading.Lock()
_g_buf          : list = []
_g_input_active : bool = False
_room_logs      : dict = defaultdict(list)   # room -> [rendered_string, ...]
_room_seen      : dict = defaultdict(set)    # room -> set of "ts|user|text" keys already animated
_current_room   : list = ["general"]         # mutable single-element so closures can mutate it


def _get_tw() -> int:
    try:
        return os.get_terminal_size().columns
    except OSError:
        return 80


def _erase_input_unsafe() -> None:
    """Erase partial input from screen. Caller must hold _OUTPUT_LOCK."""
    if not _g_input_active or not _g_buf:
        return
    tw       = _get_tw()
    n        = len(_g_buf)
    rows_up  = n // tw          # floor: after n chars from col 0, cursor is on row n//tw
    if rows_up:
        sys.stdout.write("\033[" + str(rows_up) + "A")
    sys.stdout.write("\r\033[J")
    sys.stdout.flush()


def _redraw_input_unsafe() -> None:
    """Redraw partial input. Caller must hold _OUTPUT_LOCK."""
    if not _g_input_active or not _g_buf:
        return
    sys.stdout.write("".join(_g_buf))
    sys.stdout.flush()


def print_msg(text: str) -> None:
    """Print a line of output, cleanly interleaving with in-progress input."""
    if not _is_tty():
        print(text)
        return
    with _OUTPUT_LOCK:
        _erase_input_unsafe()
        print(text)
        _redraw_input_unsafe()


def log_and_print(room: str, text: str) -> None:
    """Store message in room log and print it (no animation)."""
    _room_logs[room].append(text)
    print_msg(text)


def _msg_key(from_user: str, ts: str, text: str) -> str:
    return f"{ts}|{from_user}|{text[:40]}"


def already_seen(room: str, from_user: str, ts: str, text: str) -> bool:
    """Return True if this message has already been animated for this room."""
    return _msg_key(from_user, ts, text) in _room_seen[room]


def mark_seen(room: str, from_user: str, ts: str, text: str) -> None:
    """Mark a message as having been animated."""
    _room_seen[room].add(_msg_key(from_user, ts, text))


def switch_room_display(room_name: str, show_banner: bool = False) -> None:
    """
    Clear the terminal and show the room header.
    The server will replay history (with animation) right after this call,
    so we just clear the screen — no local log reprint needed.
    Holds _OUTPUT_LOCK throughout so nothing prints between clear and header.
    """
    _current_room[0] = room_name
    _room_logs[room_name].clear()   # server replay will refill it
    with _OUTPUT_LOCK:
        _erase_input_unsafe()
        if _is_tty():
            sys.stdout.write("\033[2J\033[H")
            sys.stdout.flush()
        if show_banner:
            print(colorize(BANNER, CYAN, bold=True))
        print(colorize(f"  ══  {room_name}  ══", CYAN, bold=True))
        print()
        _redraw_input_unsafe()


# Alias used in older call sites
def clear_for_room(room_name: str, show_banner: bool = False) -> None:
    switch_room_display(room_name, show_banner=show_banner)


# ---------------------------------------------------------------------------
# Decrypt animation
# ---------------------------------------------------------------------------

_CIPHER_POOL = list(
    "─│┌┐└┘├┤┬┴┼╔╗╚╝╠╣╦╩╬═║╒╓╕╖╘╙╛╜╞╟╡╢╤╥╧╨╪╫"
    "░▒▓█▀▄▌▐▖▗▘▙▚▛▜▝▞▟"
    "⠿⠾⠽⠻⠷⠯⠟⡿⢿"
    "!#$%&*+/<=>?@^~|*+-=<>{}[]"
    "·×÷±∑∏∂∇∞∴≈≠≡≤≥"
)

_CIPHER_COLORS = [
    "\033[36m",
    "\033[1;36m",
    "\033[96m",
    "\033[1;96m",
]

_CIPHER_CHAR_DELAY = 0.022
_REVEAL_PAUSE      = 0.38
_PLAIN_CHAR_MAX    = 0.060
_PLAIN_TOTAL_CAP   = 2.0


def _strip_ansi(s: str) -> str:
    return re.sub(r"\033\[[0-9;]*m", "", s)


def _run_animation(prefix: str, plaintext: str) -> None:
    """Wave-decrypt animation. Called while _OUTPUT_LOCK is held and input is erased."""
    WAVE = 6
    n    = len(plaintext)
    if n == 0:
        sys.stdout.write(prefix + "\n")
        sys.stdout.flush()
        return

    tw         = _get_tw()
    prefix_vis = len(_strip_ansi(prefix))

    sys.stdout.write(prefix)
    sys.stdout.flush()

    for i in range(n):
        sys.stdout.write(random.choice(_CIPHER_COLORS) + random.choice(_CIPHER_POOL) + RESET)
        sys.stdout.flush()

        reveal_i = i - WAVE
        if reveal_i >= 0:
            cursor_col = (prefix_vis + i + 1) % tw
            if cursor_col >= WAVE + 1:
                sys.stdout.write(
                    "\033[" + str(WAVE + 1) + "D"
                    + plaintext[reveal_i]
                    + "\033[" + str(WAVE) + "C"
                )
                sys.stdout.flush()

        time.sleep(_CIPHER_CHAR_DELAY)

    time.sleep(_REVEAL_PAUSE * 0.4)

    lines_up = (prefix_vis + n) // tw
    if lines_up:
        sys.stdout.write("\033[" + str(lines_up) + "A")
    sys.stdout.write("\r" + prefix + plaintext + "\n")
    sys.stdout.flush()


def _animate_msg(prefix: str, plaintext: str, room: str,
                  from_user: str = "", ts: str = "") -> None:
    """Run animation inside the output lock, log the final text, mark seen."""
    _room_logs[room].append(prefix + plaintext)
    if from_user and ts:
        mark_seen(room, from_user, ts, plaintext)
    with _OUTPUT_LOCK:
        _erase_input_unsafe()
        _run_animation(prefix, plaintext)
        _redraw_input_unsafe()


def chat_decrypt_animation(
    payload_bytes: bytes,
    plaintext: str,
    from_user: str,
    msg_ts: str,
    anim_enabled: bool = True,
    room: str = "general",
) -> None:
    ts_part   = cgrey(f"[{msg_ts}]")
    user_part = colorize(from_user, GREEN, bold=True)
    prefix    = f"{ts_part} {user_part}: "
    rendered  = prefix + plaintext

    # Already seen — reprint plain (no animation) so it shows in the room
    # after a screen clear / room switch.
    if already_seen(room, from_user, msg_ts, plaintext):
        _room_logs[room].append(rendered)
        print_msg(rendered)
        return

    if not anim_enabled or not _is_tty():
        log_and_print(room, rendered)
        mark_seen(room, from_user, msg_ts, plaintext)
        return

    _animate_msg(prefix, plaintext, room, from_user=from_user, ts=msg_ts)


def privmsg_decrypt_animation(
    payload_bytes: bytes,
    plaintext: str,
    from_user: str,
    msg_ts: str,
    verified: bool = False,
    anim_enabled: bool = True,
    room: str = "general",
) -> None:
    ts_part  = cgrey(f"[{msg_ts}]")
    src_part = colorize(f"[PM from {from_user}]", CYAN, bold=True)
    sig_part = cok("✓") if verified else cwarn("?")
    prefix   = f"{ts_part} {src_part}{sig_part} "
    rendered = prefix + plaintext

    if already_seen(room, from_user, msg_ts, plaintext):
        print_msg(rendered)   # replay — don't re-log, already in _room_logs
        return

    if not anim_enabled or not _is_tty():
        log_and_print(room, rendered)
        mark_seen(room, from_user, msg_ts, plaintext)
        return

    _animate_msg(prefix, plaintext, room, from_user=from_user, ts=msg_ts)


# ---------------------------------------------------------------------------
# No-echo input
# ---------------------------------------------------------------------------

def read_line_noecho() -> str:
    """
    Read a line with manual echo. Characters go into _g_buf so print_msg()
    can erase/redraw them around incoming messages.
    Falls back to plain input() when stdin is not a TTY.
    """
    global _g_input_active, _g_buf

    if not sys.stdin.isatty():
        line = sys.stdin.readline()
        if line == "":          # real EOF
            raise EOFError
        return line.rstrip("\n")

    import termios, tty

    fd           = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    result       = ""

    with _OUTPUT_LOCK:
        _g_buf          = []
        _g_input_active = True

    try:
        tty.setcbreak(fd)
        while True:
            ch = sys.stdin.read(1)

            if ch in ("\n", "\r"):
                with _OUTPUT_LOCK:
                    result          = "".join(_g_buf)
                    _erase_input_unsafe()
                    _g_input_active = False
                    _g_buf          = []
                break

            elif ch == "\x03":
                with _OUTPUT_LOCK:
                    _g_input_active = False
                    _g_buf          = []
                raise KeyboardInterrupt

            elif ch == "\x04":
                with _OUTPUT_LOCK:
                    _g_input_active = False
                    _g_buf          = []
                raise EOFError

            elif ch in ("\x7f", "\x08"):
                with _OUTPUT_LOCK:
                    if _g_buf:
                        _g_buf.pop()
                        sys.stdout.write("\b \b")
                        sys.stdout.flush()

            elif ch == "\x1b":
                nxt = sys.stdin.read(1)
                if nxt == "[":
                    sys.stdin.read(1)

            elif ch >= " ":
                with _OUTPUT_LOCK:
                    _g_buf.append(ch)
                    sys.stdout.write(ch)
                    sys.stdout.flush()

    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        with _OUTPUT_LOCK:
            _g_input_active = False
            _g_buf          = []

    return result


# ---------------------------------------------------------------------------
# Format helpers
# ---------------------------------------------------------------------------

def format_message(username: str, text: str, timestamp: str) -> str:
    ts  = cgrey(f"[{timestamp}]")
    usr = colorize(username, GREEN, bold=True)
    return f"{ts} {usr}: {text}"


def format_own_message(username: str, text: str, timestamp: str) -> str:
    ts  = cgrey(f"[{timestamp}]")
    usr = colorize(username, YELLOW, bold=True)
    return f"{ts} {usr}: {text}"


def format_system(text: str, timestamp: str) -> str:
    ts  = cgrey(f"[{timestamp}]")
    tag = colorize("[SYSTEM]", YELLOW, bold=True)
    return f"{ts} {tag} {text}"


def format_privmsg(from_user: str, text: str, timestamp: str, verified: bool) -> str:
    ts  = cgrey(f"[{timestamp}]")
    src = colorize(f"[PM from {from_user}]", CYAN, bold=True)
    sig = cok("✓") if verified else cwarn("?")
    return f"{ts} {src}{sig} {text}"
