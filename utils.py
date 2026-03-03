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

BANNER = (
    "\n"
    "  ███╗   ██╗ ██████╗ ███████╗██╗   ██╗███████╗███████╗\n"
    "  ████╗  ██║██╔═══██╗██╔════╝╚██╗ ██╔╝██╔════╝██╔════╝\n"
    "  ██╔██╗ ██║██║   ██║█████╗   ╚████╔╝ █████╗  ███████╗\n"
    "  ██║╚██╗██║██║   ██║██╔══╝    ╚██╔╝  ██╔══╝  ╚════██║\n"
    "  ██║ ╚████║╚██████╔╝███████╗   ██║   ███████╗███████║\n"
    "  ╚═╝  ╚═══╝ ╚═════╝ ╚══════╝   ╚═╝   ╚══════╝╚══════╝\n"
    "  Secure Terminal Chat  │  E2E Encrypted\n"
)


def print_banner() -> None:
    print(colorize(BANNER, CYAN, bold=True))


# ---------------------------------------------------------------------------
# CRT startup animation  (shown once on connect, never inside the chat)
# ---------------------------------------------------------------------------

def play_startup_animation() -> None:
    """
    CRT boot animation — slick full-window cold-start.
    Skipped when stdout is not a TTY.
    """
    if not _is_tty():
        return

    import shutil

    tw = shutil.get_terminal_size((80, 24)).columns
    th = shutil.get_terminal_size((80, 24)).lines

    ESC     = "\033"
    RST     = ESC + "[0m"
    BRT_WHT = ESC + "[1;37m"
    BRT_CYN = ESC + "[1;96m"
    CYN     = ESC + "[36m"
    DIM_CYN = ESC + "[2;36m"
    GRN     = ESC + "[32m"
    BRT_GRN = ESC + "[1;32m"
    DIM_GRN = ESC + "[2;32m"
    GREY    = ESC + "[90m"
    DIM     = ESC + "[2m"
    BOLD    = ESC + "[1m"
    CYANS   = [CYN, BRT_CYN, ESC + "[96m", ESC + "[1;36m"]
    FRINGE  = [ESC + "[31m", ESC + "[32m", ESC + "[34m", ESC + "[96m", ESC + "[37m"]
    GLITCH  = list("\u2588\u2593\u2592\u2591\u2584\u2580\u25a0\u25a1\u256c\u2560\u2563\u2550\u2551\xb7:!@#$%^&*")
    NOISECH = list("\u2591\u2592\u2593\u2502\u2500\u253c\u256c\xb7:;!?$#@%")

    def _goto(r, c=1):
        sys.stdout.write(f"\033[{r};{c}H")

    def _clr():
        sys.stdout.write("\033[2J\033[H")
        sys.stdout.flush()

    def _fill(color, char):
        line = color + (char * tw) + RST
        buf  = "".join(f"\033[{r};1H" + line for r in range(1, th + 1))
        sys.stdout.write(buf)
        sys.stdout.flush()

    def _noise_frame():
        buf = ""
        for r in range(1, th + 1):
            buf += f"\033[{r};1H" + "".join(
                random.choice(CYANS) + random.choice(NOISECH) + RST
                for _ in range(tw)
            )
        sys.stdout.write(buf)
        sys.stdout.flush()

    # ── 1. Flash ──────────────────────────────────────────────────────────────
    _clr()
    _fill(BRT_WHT, "\u2588")
    time.sleep(0.04)
    _clr()
    time.sleep(0.02)

    # ── 2. Glitch burst — scattered RGB tears ─────────────────────────────────
    for _ in range(6):
        row = random.randint(1, max(1, th - 1))
        col = random.randint(1, max(1, tw - 25))
        lng = random.randint(12, min(45, tw - col + 1))
        _goto(row, col)
        sys.stdout.write("".join(
            random.choice(FRINGE) + random.choice(GLITCH) + RST
            for _ in range(lng)
        ))
        sys.stdout.flush()
        time.sleep(0.012)
    _clr()

    # ── 3. Phosphor ramp: black → green → cyan ────────────────────────────────
    for col, char, delay in [
        (DIM_GRN,          "\u2593", 0.030),
        (GRN,              "\u2593", 0.025),
        (BRT_GRN,          "\u2592", 0.025),
        (CYN,              "\u2592", 0.025),
        (BRT_CYN,          "\u2591", 0.020),
        (ESC + "[96m",     "\u2591", 0.018),
    ]:
        _fill(col, char)
        time.sleep(delay)
    _clr()

    # ── 4. Static burst — 3 quick noise frames ────────────────────────────────
    for _ in range(3):
        _noise_frame()
        time.sleep(0.035)
    _clr()

    # ── 5. Beam sweep — full height, crisp and fast ───────────────────────────
    beam  = BRT_CYN + ("\u2501" * tw) + RST
    trail = DIM_CYN + ("\u2500" * tw) + RST
    buf   = ""
    for r in range(1, th + 1):
        if r > 1:
            buf += f"\033[{r-1};1H" + trail
        buf += f"\033[{r};1H" + beam
    sys.stdout.write(buf)
    sys.stdout.flush()
    # now animate it row by row at speed
    _clr()
    for r in range(1, th + 1):
        out = ""
        if r > 1:
            out += f"\033[{r-1};1H" + trail
        out += f"\033[{r};1H" + beam
        sys.stdout.write(out)
        sys.stdout.flush()
        time.sleep(0.007)
    time.sleep(0.04)
    _clr()

    # ── 6. Logo burn-in — vertically & horizontally centred ───────────────────
    logo_lines = BANNER.split("\n")
    logo_h     = len(logo_lines)
    logo_w     = 56
    h_pad      = max(0, (tw - logo_w) // 2)
    v_start    = max(1, (th - logo_h) // 2 - 2)
    indent     = " " * h_pad

    _clr()
    cur_row = v_start
    for line in logo_lines:
        _goto(cur_row)
        cur_row += 1
        if not line.strip():
            continue
        vis = len(line)

        # cipher flash
        sys.stdout.write(indent + "".join(
            random.choice(CYANS) + random.choice(GLITCH) + RST
            for _ in range(min(vis, tw - h_pad))
        ) + "\r")
        sys.stdout.flush()
        time.sleep(0.018)

        # left-to-right wipe
        step = max(1, vis // 6)
        for s in range(0, vis, step):
            e = min(s + step, vis)
            sys.stdout.write(
                indent +
                BRT_CYN + line[:e] + RST +
                "".join(
                    random.choice(CYANS) + random.choice(GLITCH) + RST
                    for _ in range(max(0, vis - e))
                ) + "\r"
            )
            sys.stdout.flush()
            time.sleep(0.008)

        # lock in
        sys.stdout.write(BRT_CYN + indent + line + RST)
        sys.stdout.flush()
        time.sleep(0.028)

    # ── 7. Bloom pulse — two quick dim/bright flickers ────────────────────────
    for delay in [0.05, 0.04]:
        time.sleep(delay)
        sys.stdout.write(DIM);  sys.stdout.flush(); time.sleep(0.03)
        sys.stdout.write(RST);  sys.stdout.flush()

    # ── 8. Tagline — centred, typed fast ─────────────────────────────────────
    tagline = "E2E Encrypted  \xb7  Blind-Forwarder Server  \xb7  Zero Trust"
    tag_col = max(1, (tw - len(tagline)) // 2)
    _goto(cur_row + 1, tag_col)
    for ch in tagline:
        sys.stdout.write(CYN + ch + RST)
        sys.stdout.flush()
        time.sleep(0.012)

    # ── 9. Boot status — fast scroll ─────────────────────────────────────────
    status = [
        ("SYS", "Ed25519 / X25519 / AES-256-GCM / Fernet"),
        ("SYS", "Blind-forwarder protocol active         "),
        ("OK ", "Identity loaded \u2014 transport armed         "),
    ]
    stat_col = max(1, (tw - 52) // 2)
    stat_row = cur_row + 3
    for tag, msg in status:
        _goto(stat_row, stat_col)
        stat_row += 1
        col = GRN if tag == "OK " else GREY
        sys.stdout.write(
            GREY + "[" + RST + col + tag + RST + GREY + "] " + RST +
            CYN + msg + RST
        )
        sys.stdout.flush()
        time.sleep(0.075)

    # ── 10. Two scanline flickers then hold ───────────────────────────────────
    time.sleep(0.15)
    for _ in range(2):
        sys.stdout.write(DIM);        sys.stdout.flush(); time.sleep(0.04)
        sys.stdout.write(RST + BOLD); sys.stdout.flush(); time.sleep(0.04)
    sys.stdout.write(RST);  sys.stdout.flush()

    time.sleep(0.55)
    _clr()


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
_g_cur          : int  = 0    # cursor position within _g_buf (0 = start)
_g_input_active : bool = False
_g_header       : str  = ""   # sticky header shown at top of screen
_room_logs      : dict = defaultdict(list)   # room -> [rendered_string, ...]
_room_seen      : dict = defaultdict(set)    # room -> set of "ts|user|text" keys already animated
_current_room   : list = ["general"]         # mutable single-element so closures can mutate it

# Animation skip — set by Escape hotkey; auto-clears after 2 s so future messages still animate.
_SKIP_ANIM : threading.Event = threading.Event()

def trigger_skip_animation() -> None:
    """
    Called when user presses Escape.
    Skips all ongoing/queued animations instantly.
    Auto-resets after 2 s so future incoming messages still animate.
    """
    _SKIP_ANIM.set()
    def _auto_clear():
        time.sleep(2.0)
        _SKIP_ANIM.clear()
    threading.Thread(target=_auto_clear, daemon=True).start()



def _get_tw() -> int:
    try:
        return os.get_terminal_size().columns
    except OSError:
        return 80


def _erase_input_unsafe() -> None:
    """
    Erase partial input from screen. Caller must hold _OUTPUT_LOCK.

    Cursor may be anywhere within _g_buf (left/right arrows move it).
    We need to move UP to the start row of the input, then clear down.
    The cursor is at column (_g_cur % tw) on row (_g_cur // tw) of the
    input area, so we go up that many rows to reach the input start row.
    """
    if not _g_input_active or not _g_buf:
        return
    tw      = _get_tw()
    rows_up = _g_cur // tw      # rows above cursor to reach start of input
    if rows_up:
        sys.stdout.write("\033[" + str(rows_up) + "A")
    sys.stdout.write("\r\033[J")
    sys.stdout.flush()


def _redraw_input_unsafe() -> None:
    """
    Redraw partial input with cursor at _g_cur. Caller must hold _OUTPUT_LOCK.

    Prints the entire buffer then moves the cursor left by however many
    characters trail after the cursor position.
    """
    if not _g_input_active:
        return
    if not _g_buf:
        return
    sys.stdout.write("".join(_g_buf))
    trail = len(_g_buf) - _g_cur
    if trail > 0:
        sys.stdout.write(f"\033[{trail}D")
    sys.stdout.flush()


def _redraw_header_unsafe() -> None:
    """Re-stamp the sticky header at row 1. Caller holds _OUTPUT_LOCK."""
    if not _g_header or not _is_tty():
        return
    try:
        rows = os.get_terminal_size().lines
    except OSError:
        rows = 24
    sys.stdout.write(f"[s[1;1H[2K{_g_header}[2;{rows}r[u")
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
    Clear the terminal, pin a sticky header at row 1 showing the room name,
    and set the scroll region to rows 2..N so messages scroll under it.

    show_banner is kept for backward-compat but ignored — use
    play_startup_animation() to show the logo before entering chat.
    """
    global _g_header
    _current_room[0] = room_name
    _room_logs[room_name].clear()   # server replay will refill it
    with _OUTPUT_LOCK:
        _erase_input_unsafe()
        if _is_tty():
            try:
                rows = os.get_terminal_size().lines
            except OSError:
                rows = 24
            # Build sticky header
            _g_header = colorize(f"  ══  {room_name}  ══", CYAN, bold=True)
            # Clear screen, pin header at row 1, set scroll region rows 2..N
            sys.stdout.write("[2J[H")
            sys.stdout.write(f"[1;1H[2K{_g_header}")
            sys.stdout.write(f"[2;{rows}r")   # scroll region = row 2..rows
            sys.stdout.write("[2;1H")          # cursor into scroll region
            sys.stdout.flush()
        else:
            _g_header = ""
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
    """
    Wave animation using DECSC/DECRC (\0337/\0338) save-restore cursor.

    At every step we restore to the saved position and rewrite the full
    current wave state — no cursor arithmetic, no line-wrap maths, works
    at any terminal width.

    Wave state at step i:
      plaintext[0 .. i-WAVE]     already revealed (plaintext chars)
      cipher x WAVE              the moving cipher window
    End-of-wave drain reveals the last WAVE chars one by one.
    """
    WAVE = 6
    n    = len(plaintext)
    if n == 0:
        sys.stdout.write(prefix + "\n")
        sys.stdout.flush()
        return

    # ── fast path ─────────────────────────────────────────────────────────────
    if _SKIP_ANIM.is_set():
        sys.stdout.write(prefix + plaintext + RESET + "\n")
        sys.stdout.flush()
        return

    # Save cursor position — we restore here at every frame
    sys.stdout.write("\0337")
    sys.stdout.flush()

    def _write_state(revealed: int, wave_end: int) -> None:
        """Restore to saved pos, write prefix + plaintext[:revealed] + cipher window."""
        sys.stdout.write("\0338" + RESET + prefix)
        if revealed > 0:
            sys.stdout.write(plaintext[:revealed])
        for _ in range(wave_end - revealed):
            sys.stdout.write(
                random.choice(_CIPHER_COLORS) + random.choice(_CIPHER_POOL) + RESET
            )
        sys.stdout.flush()

    # ── main wave ─────────────────────────────────────────────────────────────
    for i in range(n):
        if _SKIP_ANIM.is_set():
            break
        # revealed = chars before the WAVE window
        revealed = max(0, i + 1 - WAVE)
        _write_state(revealed, i + 1)
        time.sleep(_CIPHER_CHAR_DELAY)

    # ── end-of-wave drain: reveal last WAVE chars one by one ─────────────────
    end_delay = min(_PLAIN_CHAR_MAX, _REVEAL_PAUSE / max(WAVE, 1))
    for k in range(max(0, n - WAVE), n):
        if _SKIP_ANIM.is_set():
            break
        _write_state(k + 1, n)
        time.sleep(end_delay)

    # ── final clean overwrite ─────────────────────────────────────────────────
    sys.stdout.write("\0338" + RESET + prefix + plaintext + RESET + "\n")
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
    own_username: str = "",
) -> None:
    ts_part   = cgrey(f"[{msg_ts}]")
    # Own messages use YELLOW (matching what was displayed at send time).
    # Other users use GREEN.
    color     = YELLOW if (own_username and from_user == own_username) else GREEN
    user_part = colorize(from_user, color, bold=True)
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
    Read a line with manual echo and left/right cursor movement.

    Characters go into _g_buf (cursor tracked by _g_cur) so print_msg()
    can erase/redraw them cleanly around incoming messages.

    Keys:
      Printable       inserted at cursor position
      Backspace/Del   delete char left of cursor
      Left/Right      move cursor (CSI ESC[D/C or SS3 ESC OD/OC)
      Home/End        jump to start/end
      Up/Down/scroll  consumed silently
      Escape          trigger animation skip
      Ctrl+C/D        raise KeyboardInterrupt/EOFError
    """
    global _g_input_active, _g_buf, _g_cur

    if not sys.stdin.isatty():
        line = sys.stdin.readline()
        if line == "":
            raise EOFError
        return line.rstrip("\n")

    import termios, tty

    fd           = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    result       = ""

    with _OUTPUT_LOCK:
        _g_buf          = []
        _g_cur          = 0
        _g_input_active = True

    import os as _os, select as _sel

    def _readbyte():
        return _os.read(fd, 1).decode("utf-8", errors="replace")

    def _inline_redraw():
        """Redraw tail from cursor to end, then reposition. Caller holds lock."""
        tail = "".join(_g_buf[_g_cur:])
        sys.stdout.write(tail + " ")          # trailing space erases leftover on delete
        sys.stdout.write(f"\033[{len(tail)+1}D")  # move cursor back
        sys.stdout.flush()

    try:
        tty.setcbreak(fd)
        while True:
            ch = _readbyte()

            if ch in ("\n", "\r"):
                with _OUTPUT_LOCK:
                    result          = "".join(_g_buf)
                    _erase_input_unsafe()
                    _g_input_active = False
                    _g_buf          = []
                    _g_cur          = 0
                break

            elif ch == "\x03":
                with _OUTPUT_LOCK:
                    _g_input_active = False
                    _g_buf = []; _g_cur = 0
                raise KeyboardInterrupt

            elif ch == "\x04":
                with _OUTPUT_LOCK:
                    _g_input_active = False
                    _g_buf = []; _g_cur = 0
                raise EOFError

            elif ch in ("\x7f", "\x08"):
                with _OUTPUT_LOCK:
                    if _g_cur > 0:
                        _g_buf.pop(_g_cur - 1)
                        _g_cur -= 1
                        sys.stdout.write("\033[D")   # move cursor left
                        _inline_redraw()

            elif ch == "\x1b":
                r, _, _ = _sel.select([fd], [], [], 0.05)
                if not r:
                    trigger_skip_animation()
                    continue
                nxt = _readbyte()
                if nxt in ("[", "O"):
                    r2, _, _ = _sel.select([fd], [], [], 0.05)
                    if not r2:
                        continue
                    fin = _readbyte()
                    with _OUTPUT_LOCK:
                        if fin == "D":                # Left
                            if _g_cur > 0:
                                _g_cur -= 1
                                sys.stdout.write("\033[D")
                                sys.stdout.flush()
                        elif fin == "C":              # Right
                            if _g_cur < len(_g_buf):
                                _g_cur += 1
                                sys.stdout.write("\033[C")
                                sys.stdout.flush()
                        elif fin == "H":              # Home
                            if _g_cur > 0:
                                sys.stdout.write(f"\033[{_g_cur}D")
                                _g_cur = 0
                                sys.stdout.flush()
                        elif fin == "F":              # End
                            trail = len(_g_buf) - _g_cur
                            if trail > 0:
                                sys.stdout.write(f"\033[{trail}C")
                                _g_cur = len(_g_buf)
                                sys.stdout.flush()
                        elif fin == "5":        # PageUp = ESC[5~
                            r3,_,_ = _sel.select([fd],[],[],0.05)
                            if r3: _readbyte()  # consume trailing ~
                            _erase_input_unsafe()
                            room = _current_room[0]
                            log  = _room_logs.get(room, [])
                            if log:
                                lines = log[-30:]
                                sys.stdout.write(colorize(f"\n  \u2500\u2500 last {len(lines)} of {len(log)} messages \u2500\u2500\n","\033[90m"))
                                for ln in lines: print(ln)
                                sys.stdout.write("\n")
                                sys.stdout.flush()
                            _redraw_input_unsafe()
                        elif not (fin.isalpha() or fin == "~"):
                            # Extended sequence — drain until terminator
                            while True:
                                r3, _, _ = _sel.select([fd], [], [], 0.05)
                                if not r3: break
                                b = _readbyte()
                                if b.isalpha() or b == "~": break
                        # Up/Down/F-keys — fin consumed, ignore

            elif ch >= " ":
                with _OUTPUT_LOCK:
                    _g_buf.insert(_g_cur, ch)
                    _g_cur += 1
                    if _g_cur == len(_g_buf):
                        sys.stdout.write(ch)
                        sys.stdout.flush()
                    else:
                        sys.stdout.write(ch)
                        _inline_redraw()

    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        with _OUTPUT_LOCK:
            _g_input_active = False
            _g_buf = []; _g_cur = 0

    return result

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
