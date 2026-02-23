#!/usr/bin/env python3
"""
anim_test.py — run this directly in your terminal to test the animation.
Usage: python anim_test.py
"""
import sys, os, time, random

print(f"stdout isatty    : {sys.stdout.isatty()}")
print(f"os.isatty(1)     : {os.isatty(1)}")
print(f"stdout fileno()  : {sys.stdout.fileno()}")
print()

# --- constants (same as utils.py) ---
RESET        = "\033[0m"
BOLD         = "\033[1m"
GREEN        = "\033[32m"
GREY         = "\033[90m"
BRIGHT_WHITE = "\033[1;37m"

_CIPHER_POOL = list(
    "─│┌┐└┘├┤┬┴┼╔╗╚╝╠╣╦╩╬═║"
    "░▒▓█▀▄▌▐▖▗▘▙▚▛▜▝▞▟"
    "⠿⠾⠽⠻⠷⠯⠟"
    "!#$%&*+/<=>?@^~|*+-=<>{}[]"
    "·×÷±∑∏∂∇∞∴≈≠≡≤≥"
)
_CIPHER_COLORS = [
    "\033[35m", "\033[1;35m", "\033[95m",
    "\033[34m", "\033[1;34m", "\033[36m",
]
_CIPHER_CHAR_DELAY = 0.022
_REVEAL_PAUSE      = 0.38
_PLAIN_CHAR_MAX    = 0.060
_PLAIN_TOTAL_CAP   = 2.0
_FLASH_DUR         = 0.028
_CUR_SAVE    = "\033[s"
_CUR_RESTORE = "\033[u"
_CUR_BACK1   = "\033[1D"
_ERASE_EOL   = "\033[K"

def animate(prefix, plaintext):
    n = len(plaintext)
    # Phase 1
    sys.stdout.write(prefix + _CUR_SAVE)
    sys.stdout.flush()
    for _ in range(n):
        sys.stdout.write(random.choice(_CIPHER_COLORS) + random.choice(_CIPHER_POOL) + RESET)
        sys.stdout.flush()
        time.sleep(_CIPHER_CHAR_DELAY)
    time.sleep(_REVEAL_PAUSE)
    # Phase 2
    sys.stdout.write(_CUR_RESTORE)
    sys.stdout.flush()
    per_char   = min(_PLAIN_CHAR_MAX, _PLAIN_TOTAL_CAP / n)
    settle_dur = max(0.0, per_char - _FLASH_DUR)
    for ch in plaintext:
        sys.stdout.write(BRIGHT_WHITE + ch + RESET)
        sys.stdout.flush()
        time.sleep(_FLASH_DUR)
        sys.stdout.write(_CUR_BACK1 + ch)
        sys.stdout.flush()
        time.sleep(settle_dur)
    sys.stdout.write(_ERASE_EOL + "\n")
    sys.stdout.flush()

print("Running animation test — you should see cipher noise then plaintext reveal:")
print()
time.sleep(0.5)

prefix = "\033[90m[12:00:00]\033[0m \033[1;32mbob\033[0m: "
animate(prefix, "hello this is a test message")

print()
prefix2 = "\033[90m[12:00:01]\033[0m \033[1;36m[PM from alice]\033[0m\033[32m✓\033[0m "
animate(prefix2, "private message test")

print()
print("Done. Did you see purple cipher chars then white reveal?")
