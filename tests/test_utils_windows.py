#!/usr/bin/env python3
"""
test_utils_windows.py — Self-test for utils.py Windows code path (read_line_noecho).
Run with: python test_utils_windows.py
"""

import sys, os, types, io, unittest, unittest.mock, importlib, importlib.util, builtins
from unittest.mock import patch, MagicMock

UTILS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "NoEyes/NoEyes-main/core/utils.py")

# ── Keypress queue ────────────────────────────────────────────────────────────
_getwch_queue = []
def queue_keys(*keys): _getwch_queue.extend(keys)
def clear_queue(): _getwch_queue.clear()

# ── Fake msvcrt ───────────────────────────────────────────────────────────────
fake_msvcrt = types.ModuleType("msvcrt")
def _mock_getwch():
    if not _getwch_queue:
        raise RuntimeError("getwch() called but no keys queued")
    return _getwch_queue.pop(0)
fake_msvcrt.getwch = _mock_getwch
sys.modules["msvcrt"] = fake_msvcrt

# ── Import blocker — applied both at load time AND during test execution ──────
_real_import = builtins.__import__
def _win_import(name, *args, **kwargs):
    if name in ("termios", "tty"):
        raise ImportError(f"Simulated Windows: no '{name}'")
    return _real_import(name, *args, **kwargs)

# ── Load utils.py ─────────────────────────────────────────────────────────────
builtins.__import__ = _win_import
try:
    spec = importlib.util.spec_from_file_location("utils_win", UTILS_PATH)
    utils = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(utils)
finally:
    builtins.__import__ = _real_import

# ── Run read_line_noecho with Windows simulation active ───────────────────────
def capture_readline(keys):
    queue_keys(*keys)
    buf = io.StringIO()
    fake_stdin = MagicMock()
    fake_stdin.isatty.return_value = True
    # Block termios DURING execution too, not just at import time
    builtins.__import__ = _win_import
    try:
        with patch("sys.stdout", buf), patch("sys.stdin", fake_stdin):
            result = utils.read_line_noecho()
    finally:
        builtins.__import__ = _real_import
    return result, buf.getvalue()

# ─────────────────────────────────────────────────────────────────────────────
class TestReadLineNoechoWindows(unittest.TestCase):

    def setUp(self): clear_queue()

    def test_simple_word(self):
        r, _ = capture_readline(["h","e","l","l","o","\r"])
        self.assertEqual(r, "hello")

    def test_enter_cr(self):
        r, _ = capture_readline(["h","i","\r"])
        self.assertEqual(r, "hi")

    def test_enter_lf(self):
        r, _ = capture_readline(["h","i","\n"])
        self.assertEqual(r, "hi")

    def test_backspace_del(self):
        r, _ = capture_readline(["h","i","\x7f","\r"])
        self.assertEqual(r, "h")

    def test_backspace_0x08(self):
        r, _ = capture_readline(["h","i","\x08","\r"])
        self.assertEqual(r, "h")

    def test_backspace_at_start_does_nothing(self):
        r, _ = capture_readline(["\x7f","a","\r"])
        self.assertEqual(r, "a")

    def test_left_right_insert_middle(self):
        r, _ = capture_readline(["a","c","\xe0","K","b","\r"])
        self.assertEqual(r, "abc")

    def test_right_at_end_does_nothing(self):
        r, _ = capture_readline(["a","\xe0","M","\xe0","M","\r"])
        self.assertEqual(r, "a")

    def test_left_at_start_does_nothing(self):
        r, _ = capture_readline(["a","\xe0","K","\xe0","K","\r"])
        self.assertEqual(r, "a")

    def test_ctrl_c_raises(self):
        queue_keys("\x03")
        fake_stdin = MagicMock(); fake_stdin.isatty.return_value = True
        builtins.__import__ = _win_import
        try:
            with patch("sys.stdout", io.StringIO()), patch("sys.stdin", fake_stdin):
                with self.assertRaises(KeyboardInterrupt):
                    utils.read_line_noecho()
        finally:
            builtins.__import__ = _real_import

    def test_ctrl_d_raises(self):
        queue_keys("\x04")
        fake_stdin = MagicMock(); fake_stdin.isatty.return_value = True
        builtins.__import__ = _win_import
        try:
            with patch("sys.stdout", io.StringIO()), patch("sys.stdin", fake_stdin):
                with self.assertRaises(EOFError):
                    utils.read_line_noecho()
        finally:
            builtins.__import__ = _real_import

    def test_multichar(self):
        r, _ = capture_readline(list("NoEyes") + ["\r"])
        self.assertEqual(r, "NoEyes")

    def test_delete_all_retype(self):
        r, _ = capture_readline(["a","b","\x7f","\x7f","c","d","\r"])
        self.assertEqual(r, "cd")

    def test_space_in_message(self):
        r, _ = capture_readline(["h","i"," ","t","h","e","r","e","\r"])
        self.assertEqual(r, "hi there")

    def test_null_prefix_arrows(self):
        r, _ = capture_readline(["a","c","\x00","K","b","\r"])
        self.assertEqual(r, "abc")

    def test_non_tty_falls_back_to_readline(self):
        """When stdin is not a tty, uses readline() not msvcrt."""
        fake_stdin = MagicMock()
        fake_stdin.isatty.return_value = False
        fake_stdin.readline.return_value = "piped input\n"
        with patch("sys.stdin", fake_stdin):
            r = utils.read_line_noecho()
        self.assertEqual(r, "piped input")

# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 60)
    print("  NoEyes — utils.py Windows path self-test")
    print("  Simulating Windows (msvcrt) on Linux/macOS")
    print("=" * 60)
    unittest.main(verbosity=2)
