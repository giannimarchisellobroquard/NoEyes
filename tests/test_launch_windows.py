#!/usr/bin/env python3
"""
test_launch_windows.py — Self-test suite for launch.py Windows code paths.
Mocks msvcrt to simulate Windows keypresses on Linux/macOS.
Run with: python test_launch_windows.py
"""

import sys, os, types, io, unittest, importlib, importlib.util, builtins
from unittest.mock import patch, MagicMock

LAUNCH_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "NoEyes/NoEyes-main/launch.py")

# ── Shared keypress queue ─────────────────────────────────────────────────────
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

# ── Load launch.py with termios/tty blocked to force _UNIX=False ──────────────
_real_import = builtins.__import__
def _win_import(name, *args, **kwargs):
    if name in ("termios", "tty"):
        raise ImportError(f"Simulated Windows: no '{name}'")
    return _real_import(name, *args, **kwargs)

builtins.__import__ = _win_import
try:
    spec = importlib.util.spec_from_file_location("launch_win", LAUNCH_PATH)
    launch = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(launch)
finally:
    builtins.__import__ = _real_import

assert launch._UNIX is False, f"Expected _UNIX=False, got {launch._UNIX}"

# ── capture(): redirect stdout AND stub _tty() so fileno() is never called ────
def capture(fn, *args, **kwargs):
    buf = io.StringIO()
    with patch("sys.stdout", buf), patch.object(launch, "_tty", return_value=False):
        result = fn(*args, **kwargs)
    return result, buf.getvalue()

# ─────────────────────────────────────────────────────────────────────────────
class TestGetchWindows(unittest.TestCase):
    def setUp(self): clear_queue()

    def test_regular_char(self):
        queue_keys("a"); self.assertEqual(launch.getch(), "a")

    def test_enter_normalised(self):
        queue_keys("\r"); self.assertEqual(launch.getch(), "\n")

    def test_arrow_up_xe0(self):
        queue_keys("\xe0","H"); self.assertEqual(launch.getch(), "UP")

    def test_arrow_down_xe0(self):
        queue_keys("\xe0","P"); self.assertEqual(launch.getch(), "DOWN")

    def test_arrow_left_xe0(self):
        queue_keys("\xe0","K"); self.assertEqual(launch.getch(), "LEFT")

    def test_arrow_right_xe0(self):
        queue_keys("\xe0","M"); self.assertEqual(launch.getch(), "RIGHT")

    def test_arrow_up_null_prefix(self):
        queue_keys("\x00","H"); self.assertEqual(launch.getch(), "UP")

    def test_arrow_down_null_prefix(self):
        queue_keys("\x00","P"); self.assertEqual(launch.getch(), "DOWN")

    def test_unknown_special_key(self):
        queue_keys("\xe0","Z"); self.assertEqual(launch.getch(), "ESC")

    def test_ctrl_c(self):
        queue_keys("\x03"); self.assertEqual(launch.getch(), "\x03")

    def test_space(self):
        queue_keys(" "); self.assertEqual(launch.getch(), " ")

    def test_sequential_calls(self):
        queue_keys("x","y","z")
        self.assertEqual(launch.getch(), "x")
        self.assertEqual(launch.getch(), "y")
        self.assertEqual(launch.getch(), "z")

# ─────────────────────────────────────────────────────────────────────────────
class TestInputLineWindows(unittest.TestCase):
    def setUp(self): clear_queue()

    def _run(self, keys, prompt="Input: ", default=""):
        queue_keys(*keys)
        return capture(launch.input_line, prompt, default)

    def test_simple_word(self):
        r, _ = self._run(["h","e","l","l","o","\r"]); self.assertEqual(r, "hello")

    def test_enter_returns_default(self):
        r, _ = self._run(["\r"], default="mydefault"); self.assertEqual(r, "mydefault")

    def test_override_default(self):
        r, _ = self._run(["n","e","w","\r"], default="old"); self.assertEqual(r, "new")

    def test_backspace_del(self):
        r, _ = self._run(["h","i","\x7f","\r"]); self.assertEqual(r, "h")

    def test_backspace_0x08(self):
        r, _ = self._run(["h","i","\x08","\r"]); self.assertEqual(r, "h")

    def test_backspace_at_start(self):
        r, _ = self._run(["\x7f","a","\r"]); self.assertEqual(r, "a")

    def test_left_right_insert_middle(self):
        r, _ = self._run(["a","c","\xe0","K","b","\r"]); self.assertEqual(r, "abc")

    def test_right_at_end_does_nothing(self):
        r, _ = self._run(["a","\xe0","M","\xe0","M","\r"]); self.assertEqual(r, "a")

    def test_left_at_start_does_nothing(self):
        r, _ = self._run(["a","\xe0","K","\xe0","K","\r"]); self.assertEqual(r, "a")

    def test_up_fills_default(self):
        r, _ = self._run(["\xe0","H","\r"], default="defval"); self.assertEqual(r, "defval")

    def test_up_no_default_does_nothing(self):
        r, _ = self._run(["\xe0","H","x","\r"]); self.assertEqual(r, "x")

    def test_ctrl_c_raises(self):
        queue_keys("\x03")
        with self.assertRaises(KeyboardInterrupt):
            capture(launch.input_line, "Input: ", "")

    def test_ctrl_d_raises(self):
        queue_keys("\x04")
        with self.assertRaises(EOFError):
            capture(launch.input_line, "Input: ", "")

    def test_strips_whitespace(self):
        r, _ = self._run([" ","h","i"," ","\r"]); self.assertEqual(r, "hi")

    def test_multichar(self):
        r, _ = self._run(list("NoEyes")+["\r"]); self.assertEqual(r, "NoEyes")

    def test_delete_all_retype(self):
        r, _ = self._run(["a","b","\x7f","\x7f","c","d","\r"]); self.assertEqual(r, "cd")

    def test_prompt_in_output(self):
        _, out = self._run(["x","\r"], prompt="Enter name: ")
        self.assertIn("Enter name: ", out)

# ─────────────────────────────────────────────────────────────────────────────
class TestMenuWindows(unittest.TestCase):
    OPTIONS = [("Option A","desc a"),("Option B","desc b"),("Option C","desc c")]

    def setUp(self): clear_queue()

    def _run_menu(self, keys, options=None):
        queue_keys(*keys)
        with patch("sys.stdout", io.StringIO()), \
             patch.object(launch, "clear"), \
             patch.object(launch, "_tty", return_value=False):
            return launch.menu("Test Menu", options or self.OPTIONS)

    def test_select_first(self):
        self.assertEqual(self._run_menu(["\r"]), 0)

    def test_down_one(self):
        self.assertEqual(self._run_menu(["\xe0","P","\r"]), 1)

    def test_down_two(self):
        self.assertEqual(self._run_menu(["\xe0","P","\xe0","P","\r"]), 2)

    def test_up_wraps_to_last(self):
        self.assertEqual(self._run_menu(["\xe0","H","\r"]), 2)

    def test_down_wraps_to_first(self):
        self.assertEqual(self._run_menu(["\xe0","P","\xe0","P","\xe0","P","\r"]), 0)

    def test_down_then_up(self):
        self.assertEqual(self._run_menu(["\xe0","P","\xe0","H","\r"]), 0)

    def test_ctrl_c_raises(self):
        with self.assertRaises(KeyboardInterrupt): self._run_menu(["\x03"])

    def test_vim_j_down(self):
        self.assertEqual(self._run_menu(["j","\r"]), 1)

    def test_vim_k_up(self):
        self.assertEqual(self._run_menu(["k","\r"]), 2)

# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 60)
    print("  NoEyes — Windows code path self-test suite")
    print("  Simulating Windows (msvcrt) on Linux/macOS")
    print("=" * 60)
    unittest.main(verbosity=2)
