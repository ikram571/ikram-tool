"""Regression tests for the key screen.

The key screen is drawn by the compiled core, so what is under test here is
the wrapper that supplies the two rules the core lacks — an attempt cap and
an answer to a closed stdin — plus the two rendering defects that wrapper
repairs on the way out. Everything is driven against the real compiled
key_lock(), not a stand-in, so these tests fail if the real screen changes.
"""
import builtins
import io
import re
import sys
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from rich.console import Console                    # noqa: E402

import ikram_patch                                   # noqa: E402
from vip_ui import Vip, _KeyScreen, _width                       # noqa: E402

ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
BORDER = re.compile(r"[╭╰](?P<run>─+)[╮╯]")
KEYROW = re.compile(r"Enter key:")


def visible(line):
    return _width(ANSI.sub("", line))


class KeyScreenHarness(unittest.TestCase):
    """Drives the real key_lock through the real wrapper, with a fake tty."""

    def setUp(self):
        self.ik = ikram_patch.ikram
        self._real_key_lock = self.ik.key_lock
        self._pre_console = self.ik.console
        self._real_input = builtins.input
        self._answers = []
        self._eof = False

    def tearDown(self):
        self.ik.key_lock = self._real_key_lock
        self.ik.console = self._pre_console
        builtins.input = self._real_input

    def run_gate(self, answers=(), eof=False, timeout=20.0, width=100):
        """Returns the result and everything the key screen printed.

        The compiled core writes through its own rich Console, so the screen
        is captured by pointing that Console at a buffer for the run — the
        same swap _KeyScreen makes when it takes the screen over.
        """
        self._answers = list(answers)
        self._eof = eof
        self.buf = io.StringIO()
        # Vip() installs its own Console on the core, so build it first and
        # only then take the screen over — that is also the order the real
        # launch path uses.
        v = Vip(ikram=self.ik, stream=self.buf)
        sink = Console(file=self.buf, width=width, legacy_windows=False)
        self.ik.console = sink

        def answer(prompt=""):
            if self._eof or not self._answers:
                raise EOFError
            return self._answers.pop(0)

        out = {}
        err = []

        def body():
            try:
                out["ok"] = v._key_gate()
            except BaseException as exc:               # noqa: BLE001
                err.append(exc)
                out["ok"] = "raised:%s" % type(exc).__name__

        builtins.input = answer
        t = threading.Thread(target=body, daemon=True)
        t.start()
        t.join(timeout)
        result = {
            "ok": out.get("ok", "HUNG"),
            "hung": t.is_alive(),
            "text": ANSI.sub("", self.buf.getvalue()),
            "error": err[0] if err else None,
            "sink": sink,
            "pre_input": answer,
            "post_input": builtins.input,
            "post_console": self.ik.console,
        }
        builtins.input = self._real_input
        self.ik.console = self._pre_console
        return result

    # -- the attempt cap -------------------------------------------------
    def test_three_strikes_and_out(self):
        r = self.run_gate(answers=["nope"] * 5)
        self.assertFalse(r["hung"], "key gate hung on wrong keys")
        self.assertFalse(r["ok"])
        self.assertEqual(r["text"].count("Invalid key!"), 3,
                         "expected exactly 3 attempts, got %d"
                         % r["text"].count("Invalid key!"))
        self.assertIn("Too many attempts", r["text"])

    def test_fourth_attempt_is_never_asked(self):
        r = self.run_gate(answers=["nope"] * 9)
        self.assertEqual(r["text"].count("Enter key:"), 3,
                         "prompt redrawn more than 3 times")

    def test_cap_does_not_fire_before_three(self):
        r = self.run_gate(answers=["nope", "nope", "quit"])
        self.assertEqual(r["text"].count("Invalid key!"), 2)
        self.assertNotIn("Too many attempts", r["text"])

    # -- end of input ---------------------------------------------------
    def test_closed_stdin_exits_instead_of_hanging(self):
        r = self.run_gate(eof=True)
        self.assertFalse(r["hung"], "closed stdin left the tool hanging")
        self.assertFalse(r["ok"])

    def test_stdin_running_out_mid_prompt_exits(self):
        r = self.run_gate(answers=["nope"])     # nothing left to answer with
        self.assertFalse(r["hung"])
        self.assertFalse(r["ok"])

    # -- unchanged behaviour --------------------------------------------
    def test_quit_is_graceful_and_silent(self):
        for word in ("exit", "quit", "q", "EXIT", " Quit "):
            with self.subTest(word=word):
                r = self.run_gate(answers=[word])
                self.assertFalse(r["hung"])
                self.assertFalse(r["ok"])
                self.assertEqual(r["text"].count("Invalid key!"), 0,
                                 "%r should not count as a bad key" % word)

    def test_accepted_key_returns_true(self):
        self.ik.key_lock = lambda: True
        r = self.run_gate(answers=[])
        self.assertTrue(r["ok"])
        self.assertIs(r["post_input"], r["pre_input"],
                      "builtins.input was left patched")
        self.assertIs(r["post_console"], r["sink"],
                      "ikram.console was left swapped for the wrapper")

    def test_wrapper_restores_globals_on_the_error_path(self):
        r = self.run_gate(answers=["nope"] * 4)
        self.assertIs(r["post_input"], r["pre_input"])
        self.assertIs(r["post_console"], r["sink"])
        self.assertNotIsInstance(
            getattr(r["post_input"], "__self__", None), _KeyScreen,
            "the gate's input proxy outlived the gate")

    # -- the box geometry ------------------------------------------------
    def _box_lines(self, key):
        r = self.run_gate(answers=[key, "quit"])
        lines = [ln for ln in r["text"].split("\n")
                 if "─" in ln or KEYROW.search(ln)]
        return lines

    def test_bottom_border_uses_the_bottom_right_corner(self):
        for key in ("x", "a-longer-key", "z" * 40):
            with self.subTest(key=key):
                lines = self._box_lines(key)
                bottoms = [ln for ln in lines if "╰" in ln]
                self.assertTrue(bottoms, "no bottom border drawn")
                for ln in bottoms:
                    self.assertIn("╯", ln,
                                  "bottom border closed with the wrong corner")
                    self.assertNotIn("╮", ln.rstrip()[-3:],
                                     "bottom border kept a top-right corner")

    #: the box is 44 columns: 2 bars, 16 of prompt, so 26 fit the key
    FITTING = ("x", "abc", "a-longer-key", "z" * 12, "", "Z" * 26)

    def test_every_row_is_exactly_as_wide_as_the_border(self):
        for key in self.FITTING:
            with self.subTest(key=key):
                lines = self._box_lines(key)
                widths = {visible(ln) for ln in lines if "─" in ln}
                self.assertEqual(len(widths), 1,
                                 "border widths disagree: %s" % widths)
                border_w = widths.pop()
                for ln in lines:
                    if "─" not in ln and ln.strip():
                        self.assertEqual(
                            visible(ln), border_w,
                            "row %r is %d wide, border is %d"
                            % (ln.strip(), visible(ln), border_w))

    def test_no_row_wraps_onto_a_second_line(self):
        # _box_lines drives a bad key and then an exit, so the screen is drawn
        # twice: one row per attempt, each of them a whole line of its own.
        for key in self.FITTING:
            with self.subTest(key=key):
                lines = self._box_lines(key)
                rows = [ln for ln in lines if KEYROW.search(ln)]
                prompts = sum(1 for ln in lines if "Enter key:" in ln)
                self.assertEqual(len(rows), prompts,
                                 "a key row split across lines")
                for ln in rows:
                    self.assertTrue(ln.rstrip().endswith("│"),
                                    "key row lost its closing bar: %r" % ln)

    def test_key_longer_than_the_box_still_closes_it(self):
        # A key wider than the 26 free columns cannot fit; the core always
        # echoed it in full, so it is left alone — but the border must still
        # be drawn and nothing may be corrupted on the way.
        lines = self._box_lines("Z" * 40)
        self.assertTrue([ln for ln in lines if "╰" in ln and "╯" in ln],
                        "over-long key swallowed the bottom border")

    # -- markup must survive the repair ----------------------------------
    def test_repair_never_unbalances_markup(self):
        from rich.errors import MarkupError
        for key in ("x", "y" * 60, "a-longer-key", ""):
            with self.subTest(key=key):
                r = self.run_gate(answers=[key, "quit"])
                c = Console(file=io.StringIO(), width=100)
                for line in r["text"].split("\n"):
                    stripped = ANSI.sub("", line)
                    if not stripped.strip():
                        continue
                    try:
                        c.print(stripped)
                    except MarkupError as exc:
                        self.fail("markup broken for %r: %s" % (key, exc))

    def test_repair_is_a_noop_off_the_key_screen(self):
        from vip_ui import _fix_bottom_corner
        for text in ("plain line", "[bold red]hi[/]", "╭─╮", "╰─╮"):
            with self.subTest(text=text):
                self.assertEqual(_fix_bottom_corner(text), text)


class KeyScreenUnit(unittest.TestCase):
    """The width ruler, on its own, against hand-built lines."""

    def test_width_counts_wide_glyphs_as_two_columns(self):
        self.assertEqual(_width("│ 🔑 Enter key: "), 16)
        self.assertEqual(_width("[bold color(51)]wrong[/]"), 5)
        self.assertEqual(_width("╭" + "─" * 42 + "╮"), 44)

    def test_row_end_captures_the_fill_not_the_markup(self):
        import vip_ui
        m = vip_ui._ROW_END.match("[bold c]wrong[/][bold c]" + " " * 25 + "│[/]")
        self.assertIsNotNone(m)
        self.assertEqual(len(m.group("fill")), 25,
                         "greedy head ate the padding")
        self.assertEqual(_width(m.group("head")), 5)

    def test_border_capture_reads_the_inner_run(self):
        b = BORDER.search(ANSI.sub("", "╭" + "─" * 42 + "╮"))
        self.assertEqual(len(b.group("run")), 42)


if __name__ == "__main__":
    unittest.main(verbosity=2)
