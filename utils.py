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
import signal
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


# ---------------------------------------------------------------------------
# Message tag system
# ---------------------------------------------------------------------------
# Senders prefix their message with !tagname to signal tone.
# The tag travels inside the encrypted payload — the server never sees it.
# Receivers use the tag to color the message and play a notification sound.
# Everything is opt-in and silent for normal untagged messages.

TAGS = {
    "ok":     {"label": "✔ OK",     "color": "[92m",  "bold": True,  "sound": "ok"},
    "warn":   {"label": "⚡ WARN",  "color": "[93m",  "bold": True,  "sound": "warn"},
    "danger": {"label": "☠ DANGER","color": "[91m",  "bold": True,  "sound": "danger"},
    "info":   {"label": "ℹ INFO",   "color": "[94m",  "bold": False, "sound": "info"},
    "req":    {"label": "↗ REQ",    "color": "[95m",  "bold": False, "sound": "req"},
    "?":      {"label": "? ASK",    "color": "[96m",  "bold": False, "sound": "ask"},
}
TAG_NAMES = set(TAGS.keys())

# Prefix a user types to tag a message, e.g.  !danger server is down
TAG_PREFIX = "!"

def parse_tag(text: str) -> tuple:
    """
    Parse optional !tag prefix from a message.
    Returns (tag_or_None, message_text).
    Normal messages with no tag return (None, original_text).
    """
    if not text.startswith(TAG_PREFIX):
        return None, text
    # Find end of tag word
    space = text.find(" ", 1)
    if space == -1:
        word = text[1:]
        rest = ""
    else:
        word = text[1:space]
        rest = text[space + 1:]
    if word.lower() in TAG_NAMES:
        return word.lower(), rest.strip()
    # Not a known tag — treat whole thing as normal message
    return None, text


def format_tag_badge(tag: str) -> str:
    """Render a colored badge for a tag, e.g.  [[92m✔ OK[0m]"""
    if not tag or tag not in TAGS:
        return ""
    t = TAGS[tag]
    color = t["color"]
    bold  = "[1m" if t["bold"] else ""
    return f"[{bold}{color}{t['label']}[0m] "


# ---------------------------------------------------------------------------
# Notification sounds
# ---------------------------------------------------------------------------
# Sounds play in a background thread so they never block the UI.
# Uses platform-native audio where available, falls back to terminal bell.

_SOUNDS_ENABLED = True  # toggled by /notify on|off

def set_sounds_enabled(val: bool) -> None:
    global _SOUNDS_ENABLED
    _SOUNDS_ENABLED = val

def sounds_enabled() -> bool:
    return _SOUNDS_ENABLED

# Custom sounds folder — place files here to override built-in sounds.
# Naming: <tag>.<ext>  e.g.  sounds/danger.mp3  sounds/ok.wav  sounds/warn.ogg
# Any format your OS player supports works.  Falls back to built-in tones.
_SOUNDS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sounds")
_SOUND_EXTS  = (".wav", ".mp3", ".ogg", ".aiff", ".flac", ".m4a")

def _find_custom_sound(sound_type: str):
    """Return path to a custom sound file for *sound_type*, or None."""
    if not os.path.isdir(_SOUNDS_DIR):
        return None
    for ext in _SOUND_EXTS:
        p = os.path.join(_SOUNDS_DIR, sound_type + ext)
        if os.path.isfile(p):
            return p
    return None


def play_notification(sound_type: str) -> None:
    """Play a non-blocking notification sound for the given tag type.

    Custom sounds: drop files into a  sounds/  folder next to noeyes.py.
    Name them after the tag: ok.wav, danger.mp3, warn.ogg, info.wav,
    req.wav, ask.wav, normal.wav.  Any format your OS player supports works.
    Built-in tones are used as fallback when no custom file is found.
    """
    if not _SOUNDS_ENABLED:
        return
    if not _is_tty():
        return

    def _play():
        import subprocess, sys as _sys
        plat = _sys.platform

        # ── 1. Custom sound file (highest priority) ───────────────────────────
        custom = _find_custom_sound(sound_type)
        if custom:
            try:
                if plat == "darwin":
                    subprocess.run(["afplay", custom], capture_output=True, timeout=10)
                    return
                elif plat == "win32":
                    import winsound as _ws
                    if custom.lower().endswith(".wav"):
                        _ws.PlaySound(custom, _ws.SND_FILENAME)
                    else:
                        subprocess.run(
                            ["wmplayer", "/play", "/close", custom],
                            capture_output=True, timeout=10,
                        )
                    return
                else:
                    for player in ("paplay", "aplay", "mpg123", "ffplay", "afplay"):
                        if subprocess.run(
                            ["which", player], capture_output=True
                        ).returncode == 0:
                            subprocess.run(
                                [player, custom], capture_output=True, timeout=10
                            )
                            return
            except Exception:
                pass   # custom sound failed — fall through to built-in

        # ── 2. Built-in system sounds ─────────────────────────────────────────
        try:
            if plat == "darwin":
                _mac = {
                    "ok":     "/System/Library/Sounds/Ping.aiff",
                    "warn":   "/System/Library/Sounds/Tink.aiff",
                    "danger": "/System/Library/Sounds/Basso.aiff",
                    "info":   "/System/Library/Sounds/Pop.aiff",
                    "req":    "/System/Library/Sounds/Hero.aiff",
                    "ask":    "/System/Library/Sounds/Bottle.aiff",
                    "normal": "/System/Library/Sounds/Funk.aiff",
                }
                snd = _mac.get(sound_type, _mac["normal"])
                if os.path.exists(snd):
                    subprocess.run(["afplay", snd], capture_output=True, timeout=3)
                    return
            elif plat == "win32":
                import winsound as _ws
                _win = {
                    "ok":     (880, 120), "warn":   (440, 280),
                    "danger": (220, 500), "info":   (660, 100),
                    "req":    (550, 180), "ask":    (770, 130),
                    "normal": (440,  80),
                }
                freq, dur = _win.get(sound_type, (440, 80))
                _ws.Beep(freq, dur)
                return
            else:
                import wave, struct, tempfile, math
                _linux = {
                    "ok":     (880, 0.15), "warn":   (440, 0.28),
                    "danger": (220, 0.45), "info":   (660, 0.10),
                    "req":    (550, 0.18), "ask":    (770, 0.13),
                    "normal": (440, 0.08),
                }
                freq, dur = _linux.get(sound_type, (440, 0.08))
                rate = 22050; n = int(rate * dur)
                data = b"".join(
                    struct.pack("<h", int(32767 * math.sin(
                        2 * math.pi * freq * i / rate
                    ) * max(0, 1 - i / n)))
                    for i in range(n)
                )
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                    fname = f.name
                    with wave.open(f, "w") as wf:
                        wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(rate)
                        wf.writeframes(data)
                for player in ("paplay", "aplay", "afplay"):
                    if subprocess.run(["which", player], capture_output=True).returncode == 0:
                        subprocess.run([player, fname], capture_output=True, timeout=3)
                        break
                os.unlink(fname)
                return
        except Exception:
            pass

        # ── 3. Terminal bell fallback ─────────────────────────────────────────
        _bells = {
            "ok": "", "warn": "", "danger": "",
            "info": "", "req": "", "ask": "", "normal": "",
        }
        for b in _bells.get(sound_type, ""):
            _sys.stdout.write(b); _sys.stdout.flush(); time.sleep(0.12)

    threading.Thread(target=_play, daemon=True).start()


def _is_tty() -> bool:
    try:
        return os.isatty(sys.stdout.fileno())
    except Exception:
        return False


def _set_title(text: str) -> None:
    """Set the terminal window/tab title — visible while scrolling back."""
    if not _is_tty():
        return
    # OSC 0 sets both icon name and window title; OSC 2 sets window title only.
    # BEL () terminates the sequence; ST (\) is the proper terminator
    # but BEL works universally including older xterm and Konsole.
    sys.stdout.write(f"]0;{text}")
    sys.stdout.flush()


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

# ── TUI state ───────────────────────────────────────────────────────────────
# _tui_active: True after enter_tui() is called.  All display code checks
# this flag and takes the absolute-positioning path when set.
_tui_active        : bool = False
_tui_rows          : list = [24]            # cached terminal height
_tui_cols          : list = [80]            # cached terminal width
_scroll_offset     : dict = defaultdict(int)  # room -> lines scrolled up (0 = live)
_unread_while_away : dict = defaultdict(int)  # new msgs received while scrolled back
_resize_pending    : list = [False]           # set by SIGWINCH handler

# Animation skip — set by Escape hotkey; auto-clears after 2 s so future messages still animate.
_SKIP_ANIM : threading.Event = threading.Event()

# ── Shimmer state ─────────────────────────────────────────────────────────────
# The gradient shimmer runs in a background thread so it NEVER holds
# _OUTPUT_LOCK for more than one brief frame write (~2 ms).  This means new
# messages can always acquire the lock immediately and are never blocked.
#
# _SHIMMER_STOP   — set to kill the active shimmer thread instantly.
# _shimmer_thread — current shimmer thread (or None).
# _msg_queue_depth — number of _animate_msg calls currently waiting for the
#                    lock.  If > 0 when a new animation starts, the shimmer is
#                    suppressed (we're in a replay burst, not live chat).
# _shimmer_msg_rows — how many terminal rows the last animated message occupied
#                     so the shimmer thread knows how far to jump back.

_SHIMMER_STOP      : threading.Event = threading.Event()
_shimmer_thread    : threading.Thread = None   # type: ignore[assignment]
_msg_queue_depth   : int  = 0
_shimmer_msg_rows  : int  = 1

def trigger_skip_animation() -> None:
    """
    Called when user presses Escape.
    Skips all ongoing/queued animations instantly.
    Auto-resets after 2 s so future incoming messages still animate.
    """
    _SKIP_ANIM.set()
    _stop_shimmer()
    def _auto_clear():
        time.sleep(2.0)
        _SKIP_ANIM.clear()
    threading.Thread(target=_auto_clear, daemon=True).start()


def _stop_shimmer() -> None:
    """
    Kill the active shimmer thread (if any) and wait for it to finish its
    current frame write before returning.  Safe to call from any thread.
    """
    global _shimmer_thread
    _SHIMMER_STOP.set()
    t = _shimmer_thread
    if t and t.is_alive():
        t.join(timeout=0.15)   # at most one frame delay (45 ms) + margin
    _shimmer_thread = None


def _tui_last_msg_pos(room: str) -> tuple:
    """
    Compute (start_row, n_rows) of the LAST visible message in the TUI viewport.
    Uses the same layout logic as _tui_draw_viewport_unsafe so it is always in sync.
    Returns (None, 0) if there are no messages or the window is too small.
    Caller must hold _OUTPUT_LOCK.
    """
    rows, cols, vp_start, vp_end, sep_row, inp_row = _tui_layout()
    vh = max(1, vp_end - vp_start + 1)
    if cols < 1:
        return None, 0
    log = list(_room_logs[room])
    if not log:
        return None, 0

    # Mirror _tui_draw_viewport_unsafe: walk backwards collecting messages
    selected = []
    used_rows = 0
    for i in range(len(log) - 1, -1, -1):
        mr = max(1, (len(_strip_ansi(log[i])) + cols - 1) // cols)
        if used_rows + mr > vh:
            break
        selected.insert(0, log[i])
        used_rows += mr

    if not selected:
        return None, 0

    # Walk forward to find where the last message starts
    start_row = vp_start + (vh - used_rows)
    for msg in selected[:-1]:
        mr = max(1, (len(_strip_ansi(msg)) + cols - 1) // cols)
        start_row += mr

    last_mr = max(1, (len(_strip_ansi(selected[-1])) + cols - 1) // cols)
    return start_row, last_mr


def _shimmer_bg(prefix: str, plaintext: str, tokens: list, msg_rows: int, tui_vp_end: int = None, room: str = "general") -> None:
    """
    Background thread: continuously animate styled words with a per-character
    gradient colour wave, char-by-char across the whole line, looping until:
      • _SHIMMER_STOP is set (new message queued or ESC pressed)
      • _g_buf becomes non-empty (user started typing)
      • _SKIP_ANIM is set

    TUI mode: uses _tui_last_msg_pos() to find the exact rows of the last
    message and writes ONLY to those rows — no full viewport redraws, which
    were causing the whole screen to flicker and long messages to ghost.

    Plain mode: uses relative cursor movement to step up msg_rows lines,
    erase, rewrite, then redraw input.
    """
    # Pre-flatten tokens → (char, style) list
    all_chars: list = []
    for idx, (word, style) in enumerate(tokens):
        for ch in word:
            all_chars.append((ch, style))
        if idx < len(tokens) - 1:
            all_chars.append((" ", "normal"))

    has_gradient = any(_KZ_GRADIENTS.get(sty) for _, sty in all_chars)
    if not has_gradient:
        return   # nothing to shimmer — exit immediately

    max_depth = max((len(g) for g in _KZ_GRADIENTS.values() if g), default=4)
    offset    = 0
    frame_dt  = 0.045   # ~22 fps

    def _erase_msg_area_plain() -> None:
        sys.stdout.write(f"\033[{msg_rows}A\r")
        for i in range(msg_rows):
            sys.stdout.write("\033[2K")
            if i < msg_rows - 1:
                sys.stdout.write("\033[1B\r")
        if msg_rows > 1:
            sys.stdout.write(f"\033[{msg_rows - 1}A\r")

    def _build_gradient_line() -> str:
        parts = [RESET, prefix]
        for i, (ch, sty) in enumerate(all_chars):
            grad = _KZ_GRADIENTS.get(sty, [])
            if grad:
                parts.append(grad[(offset + i) % len(grad)] + ch + RESET)
            else:
                parts.append(ch)
        parts.append(RESET)
        return "".join(parts)

    def _build_final_line() -> str:
        parts = [RESET, prefix]
        for i, (word, style) in enumerate(tokens):
            parts.append(_kz_render(word, style))
            if i < len(tokens) - 1:
                parts.append(" ")
        parts.append(RESET)
        return "".join(parts)

    def _write_tui_rows(line: str) -> None:
        """
        Write line to the exact rows the last message occupies. Caller holds lock.
        Restricts scroll region to only those rows so long text wraps naturally
        across them without scrolling the rest of the viewport.
        """
        start_row, n_rows = _tui_last_msg_pos(room)
        if start_row is None:
            return
        end_row = start_row + n_rows - 1
        # Erase just the rows this message occupies
        for r in range(start_row, end_row + 1):
            sys.stdout.write(f"\033[{r};1H\033[2K")
        # Narrow scroll region to these rows, enable wrap, then write.
        # A newline at end_row only scrolls within [start_row..end_row]
        # so nothing outside shifts.
        _, _, vs, ve, _, _ = _tui_layout()
        sys.stdout.write(f"\033[{start_row};{end_row}r")
        sys.stdout.write("\033[?7h")
        sys.stdout.write(f"\033[{start_row};1H")
        sys.stdout.write(line)
        # Restore the real viewport scroll region
        sys.stdout.write(f"\033[{vs};{ve}r")

    def _write_gradient_frame() -> None:
        with _OUTPUT_LOCK:
            if tui_vp_end is not None:
                _erase_input_unsafe()
                _write_tui_rows(_build_gradient_line())
                _redraw_input_unsafe()
            else:
                _erase_input_unsafe()
                _erase_msg_area_plain()
                sys.stdout.write(_build_gradient_line() + "\n")
                _redraw_input_unsafe()
            sys.stdout.flush()

    def _write_final_frame() -> None:
        with _OUTPUT_LOCK:
            final_line = _build_final_line()
            if tui_vp_end is not None:
                # Update log entry so future viewport redraws use static color
                if _room_logs[room]:
                    _room_logs[room][-1] = final_line
                _erase_input_unsafe()
                _write_tui_rows(final_line)
                _redraw_input_unsafe()
            else:
                _erase_input_unsafe()
                _erase_msg_area_plain()
                sys.stdout.write(final_line + "\n")
                _redraw_input_unsafe()
            sys.stdout.flush()

    # ── Shimmer loop ──────────────────────────────────────────────────────────
    while (
        not _SHIMMER_STOP.is_set()
        and not _g_buf
        and not _SKIP_ANIM.is_set()
    ):
        _write_gradient_frame()
        time.sleep(frame_dt)
        offset = (offset + 1) % max_depth

    # ── Final static write — ALWAYS runs so no char is ever left multicolored ─
    _write_final_frame()



def _get_tw() -> int:
    try:
        return os.get_terminal_size().columns
    except OSError:
        return 80


def _erase_input_unsafe() -> None:
    """
    Erase partial input from screen. Caller must hold _OUTPUT_LOCK.

    TUI mode:  jump to inp_row (row N) and clear the line — O(1), no arithmetic.
    Plain mode: use relative cursor movement to find and clear the input row.
    """
    if not _g_input_active:
        return
    if _tui_active:
        inp_row = _tui_rows[0]
        sys.stdout.write(f"\033[{inp_row};1H\033[2K")
        sys.stdout.flush()
        return
    if not _g_buf:
        return
    tw      = _get_tw()
    rows_up = _g_cur // tw
    if rows_up:
        sys.stdout.write("\033[" + str(rows_up) + "A")
    sys.stdout.write("\r\033[J")
    sys.stdout.flush()


def _redraw_input_unsafe() -> None:
    """
    Redraw partial input with cursor at _g_cur. Caller must hold _OUTPUT_LOCK.

    TUI mode:  shows a scrolling WINDOW of cols-1 chars around the cursor so
               the buffer NEVER wraps past the single input row into the
               separator / message area above it.
    Plain mode: write buffer relative to current cursor position.
    """
    if not _g_input_active:
        return
    if _tui_active:
        inp_row = _tui_rows[0]
        cols    = max(10, _tui_cols[0])
        win     = cols - 1          # visible chars in the input row
        sys.stdout.write(f"\033[{inp_row};1H\033[2K")
        if _g_buf:
            # Scroll window so cursor is always visible
            # win_start: keep cursor inside [win_start, win_start+win)
            win_start = max(0, _g_cur - win + 1)
            win_start = min(win_start, max(0, len(_g_buf) - win))
            win_end   = min(len(_g_buf), win_start + win)
            sys.stdout.write("".join(_g_buf[win_start:win_end]))
            # Reposition cursor within the visible window
            cur_in_win = _g_cur - win_start
            chars_after = (win_end - win_start) - cur_in_win
            if chars_after > 0:
                sys.stdout.write(f"\033[{chars_after}D")
        sys.stdout.flush()
        return
    if not _g_buf:
        return
    sys.stdout.write("".join(_g_buf))
    trail = len(_g_buf) - _g_cur
    if trail > 0:
        sys.stdout.write(f"\033[{trail}D")
    sys.stdout.flush()


def _redraw_header_unsafe() -> None:
    """Re-stamp the room header at row 1 (TUI mode). Caller holds _OUTPUT_LOCK."""
    if not _tui_active or not _g_header:
        return
    cols = _tui_cols[0]
    bar  = colorize("─" * cols, GREY)
    sys.stdout.write(f"\033[s\033[1;1H\033[2K{_g_header}\n{bar}\033[u")
    sys.stdout.flush()


# ---------------------------------------------------------------------------
# TUI core — alternate screen, absolute layout, internal scrollback
# ---------------------------------------------------------------------------

def _tui_size() -> tuple:
    """Return (rows, cols) and refresh cached values."""
    try:
        sz = os.get_terminal_size()
        rows, cols = sz.lines, sz.columns
    except OSError:
        rows, cols = 24, 80
    _tui_rows[0], _tui_cols[0] = rows, cols
    return rows, cols


def _tui_layout() -> tuple:
    """Return (rows, cols, vp_start, vp_end, sep_row, inp_row)."""
    rows, cols = _tui_rows[0], _tui_cols[0]
    # Row 1        = header
    # Rows 2..N-2  = viewport (scroll region)
    # Row N-1      = separator
    # Row N        = input bar
    return rows, cols, 2, rows - 2, rows - 1, rows


def _tui_draw_viewport_unsafe() -> None:
    """
    Redraw the message viewport from _room_logs respecting _scroll_offset.
    Caller holds _OUTPUT_LOCK.

    We compute how many terminal rows each message occupies (ceiling division)
    and show the most recent messages that fit, bottom-aligned in the viewport.
    The scroll region (set in _tui_full_redraw_unsafe) keeps content inside.
    """
    room = _current_room[0]
    rows, cols, vp_start, vp_end, sep_row, inp_row = _tui_layout()
    vh = max(1, vp_end - vp_start + 1)
    if cols < 1:
        return

    log    = list(_room_logs[room])
    offset = max(0, min(_scroll_offset.get(room, 0), max(0, len(log) - 1)))
    _scroll_offset[room] = offset

    end_idx = max(0, len(log) - offset)

    # Walk backwards through log collecting messages until we fill vh rows
    selected = []
    used_rows = 0
    for i in range(end_idx - 1, -1, -1):
        msg_rows = max(1, (len(_strip_ansi(log[i])) + cols - 1) // cols)
        if used_rows + msg_rows > vh:
            break
        selected.insert(0, log[i])
        used_rows += msg_rows

    # Erase entire viewport
    for r in range(vp_start, vp_end + 1):
        sys.stdout.write(f"\033[{r};1H\033[2K")

    # Write each message at its computed row using absolute positioning.
    # Never use \n — a \n at vp_end scrolls the whole scroll region up,
    # which causes long messages to jump/duplicate then snap back.
    cur_row = vp_start + (vh - used_rows)
    for msg in selected:
        mr = max(1, (len(_strip_ansi(msg)) + cols - 1) // cols)
        sys.stdout.write(f"\033[{cur_row};1H\033[?7h")  # ensure wrap ON
        sys.stdout.write(msg)
        cur_row += mr

    # Scroll-back indicator overlaid at vp_end
    if offset > 0:
        unread = _unread_while_away.get(room, 0)
        if unread:
            ind = colorize(f"  \u2193 {unread} new \u2014 scroll down to resume live ", CYAN, bold=True)
        else:
            ind = colorize(f"  \u2191 scrolled back {offset} \u2014 PageDn or scroll to resume ", GREY)
        sys.stdout.write(f"\033[{vp_end};1H\033[2K{ind}")

    sys.stdout.flush()


def _tui_full_redraw_unsafe() -> None:
    """
    Full TUI screen redraw. Caller holds _OUTPUT_LOCK.
    Guards against tiny windows (< 6 rows) by falling back to plain output.
    """
    rows, cols, vp_start, vp_end, sep_row, inp_row = _tui_layout()

    if rows < 4 or cols < 10:
        # Window too small for TUI — just print header in plain mode
        sys.stdout.write("\033[2J\033[H")
        if _g_header:
            sys.stdout.write(_g_header + "\n")
        sys.stdout.flush()
        return

    # Set scroll region to viewport only (rows vp_start..vp_end)
    sys.stdout.write(f"\033[{vp_start};{vp_end}r")
    # Clear full screen
    sys.stdout.write("\033[2J")

    # Row 1: header
    sys.stdout.write(f"\033[1;1H\033[2K")
    if _g_header:
        sys.stdout.write(_g_header)

    # Row N-1: separator
    sys.stdout.write(f"\033[{sep_row};1H\033[2K")
    sys.stdout.write(colorize("\u2500" * cols, GREY))

    # Row N: input bar label
    sys.stdout.write(f"\033[{inp_row};1H\033[2K")

    # Viewport content
    _tui_draw_viewport_unsafe()

    # Restore cursor to input row
    sys.stdout.write(f"\033[{inp_row};1H")
    if _g_buf:
        sys.stdout.write("".join(_g_buf))
        trail = len(_g_buf) - _g_cur
        if trail > 0:
            sys.stdout.write(f"\033[{trail}D")

    sys.stdout.write("\033[?25h")
    sys.stdout.flush()


def _tui_scroll(delta: int) -> None:
    """
    Scroll the viewport by delta lines.
    delta > 0 = scroll up (older messages), delta < 0 = scroll down (newer).
    Called from read_line_noecho on mouse wheel / PageUp/Down.
    """
    room = _current_room[0]
    log  = _room_logs[room]
    vh   = max(1, _tui_rows[0] - 3)
    max_off = max(0, len(log) - 1)
    old_off = _scroll_offset.get(room, 0)
    new_off = max(0, min(max_off, old_off + delta))
    if new_off == old_off:
        return
    _scroll_offset[room] = new_off
    if new_off == 0:
        _unread_while_away[room] = 0
    with _OUTPUT_LOCK:
        _erase_input_unsafe()
        _tui_draw_viewport_unsafe()
        _redraw_input_unsafe()


def enter_tui() -> None:
    """
    Enter the alternate screen buffer and set up the TUI layout.
    Safe to call multiple times (no-op if already active).
    If switch_room_display() was already called before enter_tui(),
    a full redraw is triggered so the header/viewport/input are painted correctly.
    """
    global _tui_active
    if not _is_tty() or _tui_active:
        return
    _tui_active = True
    _tui_size()
    sys.stdout.write(
        "\033[?1049h"   # enter alternate screen
        "\033[?1007h"   # alternate scroll: wheel -> arrow keys, no click capture
        # Text selection works normally. Scroll wheel sends ESC[A/ESC[B.
    )
    sys.stdout.flush()
    try:
        signal.signal(signal.SIGWINCH, _handle_resize)
    except (AttributeError, OSError):
        pass
    # Always do a full redraw after entering alt screen so any prior
    # switch_room_display() call (which ran in plain mode) is applied.
    with _OUTPUT_LOCK:
        _tui_full_redraw_unsafe()

def exit_tui() -> None:
    """
    Exit the alternate screen buffer and restore the main screen.
    Call on disconnect / quit.
    """
    global _tui_active
    if not _tui_active:
        return
    _stop_shimmer()
    _tui_active = False
    sys.stdout.write(
        "\033[?1007l"   # disable alternate scroll
        "\033[r"        # reset scroll region
        "\033[?25h"     # ensure cursor visible
        "\033[?1049l"   # exit alternate screen
    )
    sys.stdout.flush()


def _handle_resize(signum, frame) -> None:
    """SIGWINCH handler — update cached size and immediately redraw the TUI.
    A background thread is used so we never block inside a signal handler."""
    try:
        sz = os.get_terminal_size()
        _tui_rows[0], _tui_cols[0] = sz.lines, sz.columns
    except OSError:
        pass
    _resize_pending[0] = True

    def _do_resize():
        # Brief debounce so rapid drags only trigger one redraw
        time.sleep(0.05)
        if not _tui_active:
            return
        _resize_pending[0] = False
        with _OUTPUT_LOCK:
            _tui_size()            # refresh cached dims
            rows2, cols2, vs, ve, sr, ir = _tui_layout()
            sys.stdout.write(f"\033[{vs};{ve}r")   # re-assert scroll region
            _tui_full_redraw_unsafe()

    threading.Thread(target=_do_resize, daemon=True).start()


def print_msg(text: str, _skip_log: bool = False) -> None:
    """Print a line of output, cleanly interleaving with in-progress input.

    In TUI mode every call is also appended to the room log so that /help,
    system messages, connection status, and all other transient output
    persists in the viewport (it was disappearing before because the viewport
    only redraws from _room_logs).

    Pass _skip_log=True from call sites that have ALREADY appended to
    _room_logs (i.e. _animate_msg) to avoid double-entries.
    """
    if not _is_tty():
        print(text)
        return
    try:
        acquired = False
        while not acquired:
            acquired = _OUTPUT_LOCK.acquire(timeout=0.05)
        try:
            if _tui_active:
                _erase_input_unsafe()
                room   = _current_room[0]
                if not _skip_log:
                    _room_logs[room].append(text)
                offset = _scroll_offset.get(room, 0)
                if offset > 0:
                    _unread_while_away[room] = _unread_while_away.get(room, 0) + 1
                _tui_draw_viewport_unsafe()
                _redraw_input_unsafe()
            else:
                _erase_input_unsafe()
                print(text)
                _redraw_input_unsafe()
        finally:
            _OUTPUT_LOCK.release()
    except KeyboardInterrupt:
        pass   # silently discard print during shutdown — caller handles Ctrl+C


def log_and_print(room: str, text: str) -> None:
    """Store message in room log and print it (no animation).

    In plain mode: appends to log then prints.
    In TUI mode:  print_msg handles the append, so we skip it here to avoid
                  double-entries in the viewport.
    """
    if not _tui_active:
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
    Switch to room_name.

    TUI mode:   full TUI redraw with pinned header, scroll region viewport,
                separator, and input bar.  History is per-room in _room_logs.
    Plain mode: clear screen, print header, reset scroll region.
    """
    global _g_header
    _current_room[0] = room_name
    _scroll_offset[room_name]     = 0   # start at live view
    _unread_while_away[room_name] = 0
    _room_logs[room_name].clear()       # server replay will refill it
    with _OUTPUT_LOCK:
        _erase_input_unsafe()
        _g_header = colorize(f"  ══  {room_name}  ══", CYAN, bold=True)
        _set_title(f"NoEyes │ #{room_name}")
        if _tui_active:
            _tui_size()   # refresh cached dimensions on room switch
            _tui_full_redraw_unsafe()
        elif _is_tty():
            sys.stdout.write("[3J[2J[H")
            sys.stdout.write("[r")
            sys.stdout.write(_g_header + "\n\n")
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
    Cipher wave animation. Uses row-overwrite for TUI mode (absolute row),
    DECSC/DECRC for plain mode.
    """
    WAVE = 6
    n    = len(plaintext)
    if n == 0:
        sys.stdout.write(prefix + "\n")
        sys.stdout.flush()
        return

    if _SKIP_ANIM.is_set():
        sys.stdout.write(prefix + plaintext + RESET + "\n")
        sys.stdout.flush()
        return

    if _tui_active:
        vp_end = _tui_rows[0] - 2
        def _write_state(revealed: int, wave_end: int) -> None:
            sys.stdout.write(f"\033[{vp_end};1H\033[2K" + RESET + prefix)
            if revealed > 0:
                sys.stdout.write(plaintext[:revealed])
            for _ in range(wave_end - revealed):
                sys.stdout.write(random.choice(_CIPHER_COLORS) + random.choice(_CIPHER_POOL) + RESET)
            sys.stdout.flush()
    else:
        sys.stdout.write("\0337")
        sys.stdout.flush()
        def _write_state(revealed: int, wave_end: int) -> None:
            sys.stdout.write("\0338" + RESET + prefix)
            if revealed > 0:
                sys.stdout.write(plaintext[:revealed])
            for _ in range(wave_end - revealed):
                sys.stdout.write(random.choice(_CIPHER_COLORS) + random.choice(_CIPHER_POOL) + RESET)
            sys.stdout.flush()

    for i in range(n):
        if _SKIP_ANIM.is_set():
            break
        revealed = max(0, i + 1 - WAVE)
        _write_state(revealed, i + 1)
        time.sleep(_CIPHER_CHAR_DELAY)

    end_delay = min(_PLAIN_CHAR_MAX, _REVEAL_PAUSE / max(WAVE, 1))
    for k in range(max(0, n - WAVE), n):
        if _SKIP_ANIM.is_set():
            break
        _write_state(k + 1, n)
        time.sleep(end_delay)

    if _tui_active:
        vp_end = _tui_rows[0] - 2
        sys.stdout.write(f"\033[{vp_end};1H\033[2K" + RESET + prefix + plaintext + RESET + "\n")
    else:
        sys.stdout.write("\0338" + RESET + prefix + plaintext + RESET + "\n")
    sys.stdout.flush()


# ---------------------------------------------------------------------------
# Katana Zero word animation engine — fully automatic, no user markup needed
# ---------------------------------------------------------------------------
# Tag sets the animation rhythm (speed per word).
# Each word is independently classified by the engine and gets its own color.
# Both layers apply simultaneously: tag = speed, word detection = color.
#
# Word classifications (auto-detected, no syntax needed from user):
#   ALL CAPS          → shout    — instant red pop
#   word...           → trailing — dim grey, slow fade-in
#   @mention          → mention  — bright cyan highlight
#   number/digit      → number   — slightly emphasized white
#   intensifier       → intense  — bold bright white
#   happy/positive    → happy    — bright green
#   angry/urgent      → angry    — bright red/orange
#   sad/low-energy    → sad      — dim blue
#   surprised/shocked → shocked  — bright yellow flash
#   question word     → question — cyan
#   normal            → normal   — default terminal color
# ---------------------------------------------------------------------------

# ── Word emotion dictionaries ─────────────────────────────────────────────────

_HAPPY_WORDS = {
    # joy / excitement
    "great","love","perfect","nice","good","awesome","excellent","amazing",
    "wonderful","fantastic","happy","joy","best","beautiful","brilliant",
    "superb","outstanding","incredible","magnificent","glorious","splendid",
    "delightful","marvelous","exceptional","extraordinary","terrific",
    # social / gratitude
    "congrats","congratulations","thanks","thank","appreciate","proud",
    "grateful","thankful","blessed","honored","respect","welcome","cheers",
    "bravo","kudos","legend","goat","elite","fire","lit","based",
    # success / achievement
    "win","won","success","victory","achieved","done","completed","finished",
    "solved","fixed","working","shipped","deployed","released","launched",
    "passed","approved","accepted","confirmed","verified","valid","clean",
    # positive vibes
    "yes","yay","cool","sweet","glad","pleased","excited","enjoy","fun",
    "laugh","smile","cheerful","positive","hope","hype","hyped","lets","letsgo",
    "nice","dope","sick","goated","smooth","solid","crisp","clean","fresh",
    "perfect","flawless","easy","ez","gg","poggers","pog","lol","haha",
    "hahaha","lmao","lmfao","rofl","xd",
}

_ANGRY_WORDS = {
    # frustration / failure
    "hate","wrong","broken","stop","bad","terrible","awful","horrendous",
    "atrocious","dreadful","pathetic","garbage","trash","rubbish","junk",
    "useless","worthless","pointless","stupid","dumb","idiotic","braindead",
    "fail","failed","failure","failing","crash","crashed","crashing","bug",
    "bugs","buggy","error","errors","glitch","glitches","corrupt","corrupted",
    "problem","problems","issue","issues","disaster","catastrophe","mess",
    # urgency
    "urgent","asap","immediately","critical","emergency","priority","now",
    "broken","offline","down","dead","stuck","blocked","denied","rejected",
    "banned","suspended","terminated","deleted","lost","missing","gone",
    # anger words
    "unacceptable","ridiculous","absurd","outrageous","disgusting","pathetic",
    "infuriating","maddening","enraging","infuriated","furious","rage","angry",
    "mad","livid","outraged","annoyed","irritated","frustrated","pissed",
    "annoying","irritating","frustrating","impossible","unbearable","intolerable",
    "horrible","worst","terrible","awful","disgusting","revolting","appalling",
    # curse words
    "fuck","fucked","fucking","fucker","fucks","motherfucker","mf",
    "shit","shitty","bullshit","bs","horseshit","shitstorm",
    "damn","dammit","damned","goddamn","goddammit",
    "ass","asshole","asshat","jackass","smartass","dumbass","dipshit",
    "bitch","bitching","bitchy","son","bastard",
    "crap","crapload","crappy",
    "hell","wtf","stfu","gtfo","kys","ffs","smh",
    "idiot","moron","imbecile","buffoon","clown","loser","creep",
    "screw","screwed","piss","pissy","hate","detests",
}

_SAD_WORDS = {
    # core sadness
    "sorry","sad","hurt","miss","lost","gone","alone","lonely","isolated",
    "abandoned","rejected","unloved","unwanted","invisible","forgotten",
    "tired","exhausted","drained","burnt","burnout","depleted","empty",
    "numb","hollow","broken","shattered","crushed","devastated","destroyed",
    # emotional distress
    "disappointed","heartbroken","grief","grieving","mourning","depressed",
    "depression","anxious","anxiety","hopeless","helpless","worthless",
    "useless","failure","loser","pathetic","weak","fragile","vulnerable",
    # regret / apology
    "unfortunately","regret","regrets","regretful","wish","wished","mistake",
    "mistakes","oops","apologize","apologies","apology","pardon","forgive",
    "forgiveness","blame","fault","guilty","shame","ashamed","embarrassed",
    # difficulty
    "afraid","scared","terrified","frightened","worried","worrying","concern",
    "concerned","nervous","stressed","stress","struggling","struggle","suffer",
    "suffering","pain","painful","agony","miserable","misery","cry","crying",
    "tears","weeping","aching","difficult","hard","tough","rough","dark",
}

_SHOCKED_WORDS = {
    # disbelief
    "wait","what","wow","omg","wtf","wth","omfg","seriously","really",
    "actually","literally","honest","honestly","genuinely","truly","really",
    "impossible","unbelievable","unreal","unthinkable","inconceivable",
    "incredible","shocking","shocking","stunned","speechless","mindblown",
    "unexpected","sudden","suddenly","overnight","instantly","immediately",
    # reactions
    "whoa","woah","damn","holy","insane","crazy","wild","nuts","bonkers",
    "absurd","surreal","bizarre","weird","strange","odd","peculiar",
    "no","nope","nah","no way","never","wut","huh","eh","uh","um","hmm",
    "bruh","bro","dude","man","yo","ayo","oi","oof","yikes","sheesh",
    "dayum","dayumn","geez","gosh","dang","shoot","snap","crikey",
}

# Only true interrogative words — not auxiliary verbs
_QUESTION_WORDS = {
    "who","what","why","when","how","where","which","whose","whom",
    "whatever","whoever","whenever","wherever","however","whichever",
}

_INTENSIFIERS = {
    # degree
    "very","extremely","absolutely","completely","totally","utterly","fully",
    "entirely","wholly","perfectly","purely","quite","rather","fairly",
    "terribly","awfully","dreadfully","frightfully","incredibly","remarkably",
    "especially","particularly","specifically","notably","significantly",
    "highly","deeply","strongly","heavily","seriously","severely","badly",
    # certainty
    "definitely","certainly","surely","undoubtedly","unquestionably","clearly",
    "obviously","evidently","apparently","plainly","simply","just","literally",
    "basically","essentially","fundamentally","really","truly","genuinely",
    "honestly","frankly","absolutely","positively","categorically",
    # frequency / scope
    "always","never","forever","constantly","continuously","perpetually",
    "everywhere","anywhere","nowhere","everything","anything","nothing",
    "everyone","anyone","nobody","somebody","all","none","every","each",
}

_EXCITED_WORDS = {
    "hype","hyped","fire","lit","banger","letsgo","lets","go","poggers","pog",
    "insane","crazy","wild","nuts","epic","legendary","goated","peak","based",
    "bussin","slaps","bop","heat","flames","absolute","unit","beast","god",
    "cracked","nasty","filthy","dirty","clean","crispy","crisp","smooth",
    "unstoppable","unreal","unmatched","untouchable","dominant","obliterated",
    "destroyed","clapped","rekt","bodied","demolished","annihilated","carried",
    "popping","popped","banging","slapping","hitting","going","going","off",
    "vibrating","vibing","vibes","energy","surge","rush","boost","turbo",
    "max","maxed","full","send","sending","sent","launched","blasted","rocket",
    "zooming","zoomed","flying","soaring","rising","climbing","skyrocket",
    "let","go","goo","gooo","lesgo","letsgooo","sheesh","sheeeesh","yoooo",
}

_UNCERTAIN_WORDS = {
    "maybe","idk","dunno","probably","guess","perhaps","kinda","sorta","ish",
    "possibly","potentially","presumably","apparently","seemingly","supposedly",
    "roughly","approximately","around","about","almost","nearly","somewhat",
    "kind","sort","type","like","fairly","pretty","quite","rather","relatively",
    "might","could","would","should","may","unsure","uncertain","unclear",
    "confused","confusing","complicated","complex","ambiguous","vague","fuzzy",
    "not sure","not certain","not clear","not sure","hard to say","depends",
    "wondering","wonder","curious","not sure","thinking","thought","feel",
    "suppose","suspect","reckon","imagine","assume","believe","think",
}

_THREAT_WORDS = {
    "careful","watch","beware","risk","danger","caution","avoid","warning",
    "alert","alarm","hazard","threat","menace","peril","jeopardy","crisis",
    "critical","severe","extreme","high","elevated","imminent","incoming",
    "suspicious","suspect","shady","sketchy","fishy","off","wrong","bad",
    "malicious","malware","virus","hack","hacked","breach","compromised",
    "leaked","exposed","vulnerable","attack","attacked","attacking","exploit",
    "phishing","scam","fraud","fake","spoofed","hijacked","targeted","pwned",
    "stay","heads","up","watch","out","look","out","be","careful","dont",
    "never","trust","verify","check","double","check","confirm","validate",
}

_TIMEPRESSURE_WORDS = {
    "deadline","late","overdue","today","tonight","tomorrow","asap","now",
    "urgent","immediately","soon","quickly","fast","hurry","rush","sprint",
    "yesterday","due","past","due","missed","delayed","behind","schedule",
    "running","out","time","clock","ticking","countdown","expire","expiring",
    "expired","timeout","timeouts","cutoff","last","chance","final","closing",
    "end","ends","ending","closing","close","almost","nearly","minutes","hours",
    "seconds","deadline","crunch","pressure","pending","waiting","overdue",
    "morning","afternoon","evening","midnight","noon","eod","eow","eom",
}

_SOCIAL_WORDS = {
    "bro","bruh","yo","dude","man","guys","everyone","team","hey","ayo",
    "fam","homie","homies","crew","squad","gang","people","folks","peeps",
    "friend","friends","buddy","mate","pal","partner","colleague","boss",
    "sir","ma","madam","chief","captain","boss","king","queen","legend",
    "brother","sister","sibling","cousin","neighbor","stranger","person",
    "yall","ya'll","u","ur","you","your","yours","yourself","yourselves",
    "them","they","those","these","we","us","our","ours","ourselves","i",
}

_AGREEMENT_WORDS = {
    "yes","yep","yup","yeah","yah","ya","sure","ok","okay","k","kk","ight",
    "alright","right","correct","exactly","precisely","absolutely","definitely",
    "roger","copy","affirmative","confirmed","understood","noted","received",
    "gotcha","got","agreed","agree","concur","seconded","approved","accepted",
    "valid","true","fact","facts","accurate","spot","on","nail","nailed",
    "true","real","legit","based","solid","good","great","perfect","nice",
    "makes","sense","fair","enough","works","fine","cool","sounds","good",
}

_DISAGREEMENT_WORDS = {
    "no","nope","nah","negative","nay","disagree","wrong","incorrect","false",
    "reject","denied","denied","refused","declined","rejected","vetoed",
    "absolutely not","no way","not a chance","never","not happening","nope",
    "invalid","inaccurate","mistaken","error","bug","issue","problem","flaw",
    "but","however","although","though","yet","still","nevertheless","despite",
    "except","unless","until","without","against","oppose","opposed","counter",
    "contradict","refute","dispute","challenge","question","doubt","skeptical",
}

_GREETING_WORDS = {
    "hi","hello","hey","howdy","hiya","sup","wassup","whatsup","what's up",
    "greetings","salutations","good morning","good afternoon","good evening",
    "morning","afternoon","evening","night","gm","gn","goodnight","goodmorning",
    "bye","goodbye","cya","later","laters","ttyl","ttys","peace","out","deuces",
    "take care","stay safe","see you","see ya","catch you","later","peaceout",
    "farewell","adieu","adios","ciao","sayonara","toodles","cheers","seeya",
    "wb","welcome back","welcome","back","nice to see","glad you're here",
}

# ── ANSI styles per word class ────────────────────────────────────────────────

_KZ_STYLES = {
    # original categories
    "shout":       "[1;91m",     # bold bright red          — loud impact
    "trailing":    "[2;90m",     # dim dark grey            — fading out
    "mention":     "[1;95m",     # bold bright magenta      — @user highlight
    "number":      "[38;5;214m", # amber orange             — data/value
    "intense":     "[1;97m",     # bold bright white        — emphasis
    "happy":       "[1;92m",     # bold bright green        — positive
    "angry":       "[38;5;202m", # deep orange-red          — anger
    "sad":         "[38;5;69m",  # steel blue               — melancholy
    "shocked":     "[1;93m",     # bold bright yellow       — surprise
    "question":    "[38;5;51m",  # bright aqua              — inquiry
    # new categories
    "excited":     "[38;5;213m", # hot pink/fuchsia         — hype energy
    "uncertain":   "[38;5;245m", # medium grey              — ambiguity
    "threat":      "[38;5;196m", # pure red (brighter)      — danger/warning
    "timepressure":"[38;5;220m", # gold yellow              — urgency/time
    "social":      "[38;5;159m", # light sky blue           — address/people
    "agreement":   "[38;5;120m", # light green              — yes/confirm
    "disagreement":"[38;5;210m", # soft red/salmon          — no/reject
    "greeting":    "[38;5;227m", # pale yellow              — hello/bye
    "normal":      "",               # default terminal color
}

# ── Katana Zero gradient palettes — char-by-char colour shimmer ──────────────
# 4-step palettes: dim → mid → saturated → bright, matching each word style.
# "normal" is empty — unstyled words stay static during shimmer.

_KZ_GRADIENTS = {
    # shout — red ramp, no ambiguity
    "shout":        ["\033[31m",        "\033[1;31m",      "\033[91m",        "\033[1;91m"],
    # trailing — grey ramp, dim to mid
    "trailing":     ["\033[2;90m",      "\033[90m",        "\033[2;37m",      "\033[90m"],
    # mention — pure magenta ramp
    "mention":      ["\033[35m",        "\033[1;35m",      "\033[95m",        "\033[1;95m"],
    # number — amber/orange ramp, no red
    "number":       ["\033[33m",        "\033[38;5;208m",  "\033[38;5;214m",  "\033[38;5;220m"],
    # intense — white ramp
    "intense":      ["\033[37m",        "\033[1;37m",      "\033[97m",        "\033[1;97m"],
    # happy — green ramp
    "happy":        ["\033[32m",        "\033[1;32m",      "\033[92m",        "\033[1;92m"],
    # angry — pure red/orange-red only, no blue or ambiguous codes
    "angry":        ["\033[31m",        "\033[1;31m",      "\033[91m",        "\033[1;91m"],
    # sad — pure blue ramp
    "sad":          ["\033[34m",        "\033[1;34m",      "\033[94m",        "\033[1;34m"],
    # shocked — yellow ramp
    "shocked":      ["\033[33m",        "\033[1;33m",      "\033[93m",        "\033[1;93m"],
    # question — cyan ramp
    "question":     ["\033[36m",        "\033[1;36m",      "\033[96m",        "\033[1;96m"],
    # excited — magenta→pink ramp (no blue)
    "excited":      ["\033[35m",        "\033[1;35m",      "\033[95m",        "\033[1;95m"],
    # uncertain — grey ramp
    "uncertain":    ["\033[2;37m",      "\033[37m",        "\033[90m",        "\033[2;37m"],
    # threat — red ramp (same family as shout but slightly different rhythm)
    "threat":       ["\033[31m",        "\033[91m",        "\033[1;31m",      "\033[1;91m"],
    # timepressure — yellow/gold ramp
    "timepressure": ["\033[33m",        "\033[1;33m",      "\033[93m",        "\033[1;33m"],
    # social — cyan ramp (distinct from question by being lighter)
    "social":       ["\033[36m",        "\033[96m",        "\033[1;36m",      "\033[1;96m"],
    # agreement — green ramp
    "agreement":    ["\033[32m",        "\033[92m",        "\033[1;32m",      "\033[1;92m"],
    # disagreement — red ramp (softer than shout/threat)
    "disagreement": ["\033[31m",        "\033[91m",        "\033[1;31m",      "\033[91m"],
    # greeting — yellow ramp
    "greeting":     ["\033[33m",        "\033[93m",        "\033[1;33m",      "\033[1;33m"],
    "normal":       [],
}

# ── Base delay between words per tag ─────────────────────────────────────────

_KZ_WORD_DELAY = {
    "danger": 0.022,
    "warn":   0.034,
    "ok":     0.046,
    "req":    0.052,
    "ask":    0.058,
    "info":   0.064,
    "normal": 0.040,
}

_KZ_PUNCT_PAUSE = {".": 3.5, "!": 2.0, "?": 2.8, ",": 1.6, ";": 1.8, ":": 1.5}


def _kz_classify(word: str) -> str:
    """
    Classify a single word into a KZ style category.
    Order matters — more specific checks first.
    """
    import re
    bare = word.rstrip(".,!?;:").lower()
    raw  = word.rstrip(".,!?;:")

    # Structural detections first
    if raw == raw.upper() and len(raw) >= 2 and raw.isalpha():
        return "shout"
    if word.endswith("...") or word.endswith("…"):
        return "trailing"
    if bare.startswith("@") and len(bare) > 1:
        return "mention"
    if re.match(r"^-?\d[\d,.%$€£]*$", bare):
        return "number"

    # Semantic detections — order matters, more specific wins
    if bare in _INTENSIFIERS:
        return "intense"
    if bare in _THREAT_WORDS:
        return "threat"
    if bare in _TIMEPRESSURE_WORDS:
        return "timepressure"
    if bare in _GREETING_WORDS:
        return "greeting"
    if bare in _SOCIAL_WORDS:
        return "social"
    if bare in _AGREEMENT_WORDS:
        return "agreement"
    if bare in _DISAGREEMENT_WORDS:
        return "disagreement"
    if bare in _EXCITED_WORDS:
        return "excited"
    if bare in _HAPPY_WORDS:
        return "happy"
    if bare in _ANGRY_WORDS:
        return "angry"
    if bare in _SAD_WORDS:
        return "sad"
    if bare in _UNCERTAIN_WORDS:
        return "uncertain"
    if bare in _SHOCKED_WORDS:
        return "shocked"
    if bare in _QUESTION_WORDS:
        return "question"

    return "normal"


def _kz_render(word: str, style: str) -> str:
    """Apply ANSI color for a word's style."""
    color = _KZ_STYLES.get(style, "")
    if not color:
        return word
    if style == "shout":
        return f"{color}{word.upper()}[0m"
    return f"{color}{word}[0m"


def _kz_tokenize(text: str) -> list:
    """Split text into (word, style) pairs, preserving punctuation on words.

    Also strips any leftover markup syntax characters (*,_,~) that might
    appear literally in the message so they never show on screen.
    """
    import re
    # Strip any residual markup markers — *word*, _word_, ~word~, **word**
    # These are no longer valid syntax but could appear in old messages or
    # if someone types them literally.
    clean = re.sub(r'\*{1,2}([^*]+)\*{1,2}', r'', text)
    clean = re.sub(r'~([^~]+)~', r'', clean)
    clean = re.sub(r'(?<!\w)_([^_]+)_(?!\w)', r'', clean)
    tokens = []
    for word in re.split(r'(\s+)', clean):
        if not word or word.isspace():
            continue
        tokens.append((word, _kz_classify(word)))
    return tokens


def _has_kz_content(text: str) -> bool:
    """Return True if any word in text would get a non-normal KZ style."""
    return any(style != "normal" for _, style in _kz_tokenize(text))


def _run_kz_animation(prefix: str, plaintext: str, tag: str = "") -> None:
    """
    Word-by-word cipher wave animation.

    Each word runs through the same cipher wave as the full-sentence animation
    (random chars scrolling → plaintext reveal) but word by word.
    Emotion color is applied when the word finally reveals.
    Tag sets the wave speed per word.
    Shout words skip the wave and pop in instantly.
    Trailing words use a slower wave.
    Escape skips to full reveal immediately.
    """
    tokens = _kz_tokenize(plaintext)
    if not tokens:
        sys.stdout.write(prefix + "\n")
        sys.stdout.flush()
        return

    if _SKIP_ANIM.is_set():
        if _tui_active:
            vp_end = _tui_rows[0] - 2
            sys.stdout.write(f"\033[{vp_end};1H\033[2K")
        sys.stdout.write(prefix)
        for i, (w, sty) in enumerate(tokens):
            sys.stdout.write(_kz_render(w, sty))
            if i < len(tokens) - 1:
                sys.stdout.write(" ")
        sys.stdout.write(RESET + "\n")
        sys.stdout.flush()
        return

    WAVE = 4   # cipher window width per word (shorter than full-sentence wave)
    base_char_delay = _KZ_WORD_DELAY.get(tag, _KZ_WORD_DELAY["normal"]) * 0.35

    # In TUI mode use absolute row positioning; in plain mode use DECSC/DECRC.
    if _tui_active:
        _kz_vp_end = _tui_rows[0] - 2
    else:
        _kz_vp_end = None
        sys.stdout.write("\0337" + prefix)
        sys.stdout.flush()

    revealed: list = []   # list of (word, style) already shown

    def _redraw_line(word_placeholder: str = "") -> None:
        """Rewrite prefix + revealed words + placeholder at the correct row."""
        if _kz_vp_end is not None:
            sys.stdout.write(f"\033[{_kz_vp_end};1H\033[2K" + RESET + prefix)
        else:
            sys.stdout.write("\0338" + RESET + prefix)
        for i, (w, sty) in enumerate(revealed):
            sys.stdout.write(_kz_render(w, sty))
            sys.stdout.write(" ")
        if word_placeholder:
            sys.stdout.write(word_placeholder)
        sys.stdout.flush()

    def _wave_reveal_word(word: str, style: str) -> None:
        """Run the cipher wave over a single word then snap to its colored form."""
        n = len(word)
        color = _KZ_STYLES.get(style, "")

        # Speed modifiers per style
        if style == "trailing":
            delay = base_char_delay * 1.7
        elif style in ("shout", "shocked"):
            delay = base_char_delay * 0.3
        elif style in ("intense", "mention"):
            delay = base_char_delay * 0.7
        else:
            delay = base_char_delay

        # Wave: cipher chars scroll across the word length
        for i in range(n):
            if _SKIP_ANIM.is_set():
                break
            revealed_chars = max(0, i + 1 - WAVE)
            # already-revealed part of this word in its final color
            prefix_part = (color + word[:revealed_chars] + RESET) if revealed_chars else ""
            # cipher window
            cipher_part  = "".join(
                random.choice(_CIPHER_COLORS) + random.choice(_CIPHER_POOL) + RESET
                for _ in range(min(WAVE, i + 1))
            )
            _redraw_line(prefix_part + cipher_part)
            time.sleep(delay)

        # Drain: reveal last WAVE chars
        drain_delay = delay * 0.6
        for k in range(max(0, n - WAVE), n):
            if _SKIP_ANIM.is_set():
                break
            prefix_part = color + word[:k + 1] + RESET
            _redraw_line(prefix_part)
            time.sleep(drain_delay)

        # Word fully revealed — add to revealed list
        revealed.append((word, style))
        _redraw_line()

    for word, style in tokens:
        if _SKIP_ANIM.is_set():
            revealed.append((word, style))
            continue

        if style == "shout":
            # Block flash then instant snap — no wave, just impact
            _redraw_line(
                "[1;91m" + "█" * len(word) + RESET
            )
            time.sleep(0.022)
            revealed.append((word, style))
            _redraw_line()
            time.sleep(base_char_delay * 0.9)
        else:
            _wave_reveal_word(word, style)

        # Natural pause on sentence-ending punctuation
        last_char = word[-1] if word else ""
        if last_char in _KZ_PUNCT_PAUSE and not _SKIP_ANIM.is_set():
            pause = base_char_delay * _KZ_PUNCT_PAUSE[last_char] * 1.2
            elapsed = 0.0
            while elapsed < pause and not _SKIP_ANIM.is_set():
                time.sleep(0.02)
                elapsed += 0.02

    # Final clean write — full line with all emotion colors
    if _kz_vp_end is not None:
        sys.stdout.write(f"\033[{_kz_vp_end};1H\033[2K" + RESET + prefix)
    else:
        sys.stdout.write("\0338" + RESET + prefix)
    for i, (word, style) in enumerate(_kz_tokenize(plaintext)):
        sys.stdout.write(_kz_render(word, style))
        if i < len(tokens) - 1:
            sys.stdout.write(" ")
    sys.stdout.write(RESET + "\n")
    sys.stdout.flush()



def _kz_render_full(plaintext: str) -> str:
    """
    Render plaintext with KZ emotion colors applied to each word.
    Returns a string with ANSI color codes — suitable for storing in _room_logs
    so the TUI viewport always shows colored messages.
    """
    tokens = _kz_tokenize(plaintext)
    if not tokens:
        return plaintext
    parts = []
    for i, (w, sty) in enumerate(tokens):
        parts.append(_kz_render(w, sty))
        if i < len(tokens) - 1:
            parts.append(" ")
    parts.append(RESET)
    return "".join(parts)


def _animate_msg(prefix: str, plaintext: str, room: str,
                  from_user: str = "", ts: str = "",
                  tag: str = "") -> None:
    """
    Run cipher-wave animation then hand off to the background shimmer thread.

    Lock discipline:
      _OUTPUT_LOCK is held ONLY during the bounded cipher wave animation and
      the final static write.  It is RELEASED before the shimmer starts.
      The shimmer thread acquires the lock briefly (~2 ms) per frame.

    Replay-burst detection:
      _msg_queue_depth counts how many _animate_msg calls are waiting for the
      lock right now.  If the depth is > 0 we are in a server replay or message
      burst — skip the shimmer entirely (and optionally skip the cipher wave too)
      so the backlog drains instantly instead of queuing up for seconds.
    """
    global _shimmer_thread, _msg_queue_depth, _shimmer_msg_rows

    # Pre-build the KZ-colored version once — stored in _room_logs so the
    # TUI viewport always redraws with emotion colors, not plain text.
    colored_text = _kz_render_full(plaintext)
    tokens = _kz_tokenize(plaintext)

    # Log is appended AFTER animation so the message does not appear
    # in the viewport while it is still being cipher-animated.
    if from_user and ts:
        mark_seen(room, from_user, ts, plaintext)

    # ── 1. Signal queue depth and kill any active shimmer ─────────────────────
    _msg_queue_depth += 1
    _stop_shimmer()   # sets _SHIMMER_STOP, joins shimmer thread

    # ── 2. Run the bounded cipher-wave animation (holds lock) ─────────────────
    with _OUTPUT_LOCK:
        _msg_queue_depth = max(0, _msg_queue_depth - 1)
        _SHIMMER_STOP.clear()   # we now own the terminal; shimmer is gone

        _erase_input_unsafe()

        # Auto-skip animation when the user is actively typing
        if _g_buf:
            trigger_skip_animation()

        # Burst mode: if messages are still queued behind us, skip cipher wave
        # entirely and just print static so the backlog clears instantly.
        burst = _msg_queue_depth > 0

        if burst or _SKIP_ANIM.is_set():
            # Fast path — static print with emotion colors, no cipher wave
            _room_logs[room].append(prefix + colored_text)
            if _tui_active:
                _tui_draw_viewport_unsafe()
            else:
                sys.stdout.write(prefix)
                for i, (w, sty) in enumerate(tokens):
                    sys.stdout.write(_kz_render(w, sty))
                    if i < len(tokens) - 1:
                        sys.stdout.write(" ")
                sys.stdout.write(RESET + "\n")
                sys.stdout.flush()
            _redraw_input_unsafe()
            return   # no shimmer in burst mode

        # Compute shimmer row count before we decide where to animate
        tw = (_tui_cols[0] if _tui_active else _get_tw()) or 80
        visible_len = len(_strip_ansi(prefix)) + len(plaintext)
        _shimmer_msg_rows = max(1, (visible_len + tw - 1) // tw)

        if _tui_active:
            # In TUI mode skip the per-character cipher wave entirely.
            # The shimmer handles the gradient animation for any message length.
            _room_logs[room].append(prefix + colored_text)
            _tui_draw_viewport_unsafe()
        else:
            # Plain mode — full cipher wave then log
            if tag or _has_kz_content(plaintext):
                _run_kz_animation(prefix, plaintext, tag=tag)
            else:
                _run_animation(prefix, plaintext)
            _room_logs[room].append(prefix + colored_text)

        _redraw_input_unsafe()
        # Lock released here — shimmer thread can now acquire it per-frame

    # ── 3. Spawn background shimmer ─────────────────────────────────────────
    # Works in both plain and TUI mode.  In TUI mode we pass tui_vp_end so
    # _shimmer_bg uses absolute row positioning to rewrite just the last
    # message row — it never touches the header, separator, or input bar.
    # _stop_shimmer() is always called at the top of the next _animate_msg so
    # there is no race: the shimmer is dead before any new message is drawn.
    if not _SKIP_ANIM.is_set() and not _g_buf:
        shimmer_vp_end = (_tui_rows[0] - 2) if _tui_active else None
        _shimmer_thread = threading.Thread(
            target=_shimmer_bg,
            args=(prefix, plaintext, tokens, _shimmer_msg_rows, shimmer_vp_end, room),
            daemon=True,
        )
        _shimmer_thread.start()


def chat_decrypt_animation(
    payload_bytes: bytes,
    plaintext: str,
    from_user: str,
    msg_ts: str,
    anim_enabled: bool = True,
    room: str = "general",
    own_username: str = "",
    tag: str = "",
) -> None:
    ts_part   = cgrey(f"[{msg_ts}]")
    # Own messages use YELLOW (matching what was displayed at send time).
    # Other users use GREEN.  Tagged messages use the tag's color instead.
    if tag and tag in TAGS:
        color = TAGS[tag]["color"]
        bold  = TAGS[tag]["bold"]
    else:
        color = YELLOW if (own_username and from_user == own_username) else GREEN
        bold  = True
    user_part  = colorize(from_user, color, bold=bold)
    badge_part = format_tag_badge(tag)
    prefix     = f"{ts_part} {user_part}: {badge_part}"
    # Colored version (KZ emotion colors on words) — stored in _room_logs so
    # the TUI viewport always redraws with colors.
    colored_plain = _kz_render_full(plaintext)
    rendered   = prefix + colored_plain

    # Already seen — reprint plain (no animation) so it shows in the room
    # after a screen clear / room switch.
    if already_seen(room, from_user, msg_ts, plaintext):
        _room_logs[room].append(rendered)
        print_msg(rendered)
        return

    # Fire sound immediately — before animation so long messages don't delay the alert.
    if from_user != own_username:
        if tag and tag in TAGS:
            play_notification(TAGS[tag]["sound"])
        else:
            play_notification("normal")

    if not anim_enabled or not _is_tty():
        log_and_print(room, rendered)
        mark_seen(room, from_user, msg_ts, plaintext)
    else:
        _animate_msg(prefix, plaintext, room, from_user=from_user, ts=msg_ts, tag=tag)


def privmsg_decrypt_animation(
    payload_bytes: bytes,
    plaintext: str,
    from_user: str,
    msg_ts: str,
    verified: bool = False,
    anim_enabled: bool = True,
    room: str = "general",
    tag: str = "",
) -> None:
    ts_part   = cgrey(f"[{msg_ts}]")
    src_part  = colorize(f"[PM from {from_user}]", CYAN, bold=True)
    sig_part  = cok("✓") if verified else cwarn("?")
    badge_part = format_tag_badge(tag)
    prefix    = f"{ts_part} {src_part}{sig_part} {badge_part}"
    colored_plain = _kz_render_full(plaintext)
    rendered  = prefix + colored_plain

    if already_seen(room, from_user, msg_ts, plaintext):
        print_msg(rendered)   # replay — don't re-log, already in _room_logs
        return

    # Fire sound immediately — before animation so long messages don't delay the alert.
    if tag and tag in TAGS:
        play_notification(TAGS[tag]["sound"])
    else:
        play_notification("info")   # PMs always ping

    if not anim_enabled or not _is_tty():
        log_and_print(room, rendered)
        mark_seen(room, from_user, msg_ts, plaintext)
    else:
        _animate_msg(prefix, plaintext, room, from_user=from_user, ts=msg_ts, tag=tag)


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
        # In TUI mode the cursor may have drifted into the viewport after the
        # last message / send.  Explicitly home it to the input row so the
        # first character typed appears in the right place.
        if _tui_active:
            inp_row = _tui_rows[0]
            sys.stdout.write(f"\033[{inp_row};1H\033[2K")
            sys.stdout.flush()

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
                        if _tui_active:
                            _redraw_input_unsafe()
                        else:
                            sys.stdout.write("\033[D")
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
                    if fin == "<" and _tui_active:
                        # SGR extended mouse sequence: ESC[<btn;col;row{M|m}
                        buf = ""
                        while True:
                            r3, _, _ = _sel.select([fd], [], [], 0.2)
                            if not r3: break
                            b = _readbyte()
                            buf += b
                            if b in ("M", "m"): break
                        try:
                            parts = buf[:-1].split(";")
                            btn   = int(parts[0])
                            final = buf[-1] if buf else ""
                            if final == "M":        # press event
                                if btn == 64:      # scroll wheel up
                                    _tui_scroll(3)
                                elif btn == 65:    # scroll wheel down
                                    _tui_scroll(-3)
                        except (ValueError, IndexError):
                            pass
                        continue
                    # Handle scroll keys OUTSIDE the lock (_tui_scroll acquires it)
                    _scroll_delta = 0
                    if fin == "A" and _tui_active:       # Up arrow / wheel up
                        _scroll_delta = 3
                    elif fin == "B" and _tui_active:     # Down arrow / wheel down
                        _scroll_delta = -3
                    elif fin == "5":                     # PageUp
                        r3,_,_ = _sel.select([fd],[],[],0.05)
                        if r3: _readbyte()
                        _scroll_delta = max(1, _tui_rows[0] - 4) if _tui_active else 0
                        if not _tui_active:
                            with _OUTPUT_LOCK:
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
                    elif fin == "6":                     # PageDown
                        r3,_,_ = _sel.select([fd],[],[],0.05)
                        if r3: _readbyte()
                        _scroll_delta = -(max(1, _tui_rows[0] - 4)) if _tui_active else 0

                    if _scroll_delta != 0 and _tui_active:
                        _tui_scroll(_scroll_delta)
                        continue   # skip the lock block below for these keys

                    with _OUTPUT_LOCK:
                        if fin == "D":                # Left
                            if _g_cur > 0:
                                _g_cur -= 1
                                if _tui_active:
                                    _redraw_input_unsafe()
                                else:
                                    sys.stdout.write("\033[D")
                                    sys.stdout.flush()
                        elif fin == "C":              # Right
                            if _g_cur < len(_g_buf):
                                _g_cur += 1
                                if _tui_active:
                                    _redraw_input_unsafe()
                                else:
                                    sys.stdout.write("\033[C")
                                    sys.stdout.flush()
                        elif fin == "H":              # Home
                            if _g_cur > 0:
                                _g_cur = 0
                                if _tui_active:
                                    _redraw_input_unsafe()
                                else:
                                    sys.stdout.write(f"\033[{_g_cur}D")
                                    sys.stdout.flush()
                        elif fin == "F":              # End
                            if _g_cur < len(_g_buf):
                                _g_cur = len(_g_buf)
                                if _tui_active:
                                    _redraw_input_unsafe()
                                else:
                                    trail = len(_g_buf) - _g_cur
                                    sys.stdout.write(f"\033[{trail}C")
                                    sys.stdout.flush()
                        elif not (fin.isalpha() or fin == "~"):
                            # Extended sequence — drain until terminator
                            while True:
                                r3, _, _ = _sel.select([fd], [], [], 0.05)
                                if not r3: break
                                b = _readbyte()
                                if b.isalpha() or b == "~": break
                        # Other alpha keys (F-keys etc) — consumed, ignore

            elif ch >= " ":
                with _OUTPUT_LOCK:
                    _g_buf.insert(_g_cur, ch)
                    _g_cur += 1
                    if _tui_active:
                        # Always use _redraw_input_unsafe in TUI so the
                        # windowed display is applied — prevents long input
                        # from wrapping into the message / separator rows.
                        _redraw_input_unsafe()
                    elif _g_cur == len(_g_buf):
                        sys.stdout.write(ch)
                        sys.stdout.flush()
                    else:
                        sys.stdout.write(ch)
                        _inline_redraw()
            # ── Resize check after every keystroke ───────────────────────────
            if _resize_pending[0] and _tui_active:
                _resize_pending[0] = False
                with _OUTPUT_LOCK:
                    _tui_size()            # must happen before redraw
                    # Re-assert scroll region with new dimensions then full redraw
                    rows2, cols2, vs, ve, sr, ir = _tui_layout()
                    sys.stdout.write(f"\033[{vs};{ve}r")  # reset scroll region
                    _tui_full_redraw_unsafe()

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
