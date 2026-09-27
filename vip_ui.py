"""IkramTool — VIP shell.

Owns the screen: header, menu loops, submenus, folder status, prompts,
PROCEED box, progress frames, status boxes, invalid-input box, theme
switcher, clears, exit + terminal restore. Every menu option is dispatched
to a REAL handler in menus.py or lua_pipeline.py. Nothing on screen is
un-boxed; the only non-boxed line allowed anywhere is the Press-ENTER
`minimal` divider.

All user input funnels through `_ask()`, so tests can script whole flows
without a terminal.
"""
import re
import sys
import time
import unicodedata

from theme_engine import Theme, load_theme, save_theme, THEMES, is_tty
from box_engine import BoxEngine, SEP, vip_num_cycle
import paths


def _read_version():
    """Single source of truth is the VERSION file next to this module.

    There is deliberately no hardcoded version literal in this function. The
    literal that used to sit here was worse than no fallback at all: every
    sandbox that remaps paths away from the repo has no VERSION file, so the
    banner silently showed that frozen literal instead of the real version —
    which is how a version bump can pass the unit suites and still ship a
    wrong banner.

    Fallback chain, in order of authority:
      1. the VERSION file
      2. ikram_key.json, which the updater rewrites on every install
      3. "unknown" — loud and obviously wrong, never a plausible number
    """
    try:
        v = (paths.ROOT / "VERSION").read_text(encoding="utf-8").strip()
        if v:
            return v.lower()
    except Exception:
        pass
    try:
        import json
        v = json.loads((paths.ROOT / "ikram_key.json").read_text(
            encoding="utf-8")).get("version", "")
        if v:
            return str(v).strip().lower()
    except Exception:
        pass
    return "unknown"


VERSION = _read_version()
BRAND = "IkramTool"
C = "\x1b["
RESET = C + "0m"
CLS = C + "3J" + C + "2J" + C + "H" + C + "0m"

CLEAR_PAK_DROP = "CLEAR DROP FOLDER"
CLEAR_RESULT = "CLEAR RESULT FOLDER"


def _w(text):
    sys.stdout.write(text)
    sys.stdout.flush()


def _markup(code: int) -> str:
    """Compiled engine markup colour `color(N)` from a theme palette code."""
    return "color(%d)" % code


# compiled ikram module attributes -> theme roles (A-to-Z theming)
_ATTR_ROLE = {
    "INP": "prompt", "ACCENT": "accent", "VIP": "accent", "VIP2": "secondary",
    "CYAN": "secondary", "MUTED": "dim", "SUCCESS": "success",
    "ERROR": "error", "ERROR_TITLE": "error", "WARN": "warn",
    "BORDER": "border", "BORDER_DARK": "border_dark", "LINE": "border",
    "TITLE": "title", "GOLD": "secondary", "GOLD_BRIGHT": "primary",
    "MATRIX": "accent",
}


def _vip_num_cycle(pal, theme_name="Original Color"):
    """V111 number colour cycle, from the one definition in box_engine.

    Default theme: 0→183, 1→45, 2→51, 3→39, 4→118, 5→119, unchanged. Any
    other theme maps the same six slots through its own palette, so the
    numbers follow the theme everywhere they are painted — renderer and
    compiled core alike — instead of only in half the tool.
    """
    return vip_num_cycle(pal, theme_name)


def _sync_compiled_theme(vip):
    """Push the active theme into the compiled engine's global colour attrs,
    so the WHOLE tool — welcome, key screen, wizards, numbers, every menu —
    follows the chosen theme."""
    ik = vip.ikram
    if ik is None:
        return
    pal = vip.theme._pal
    for attr, role in _ATTR_ROLE.items():
        if hasattr(ik, attr):
            setattr(ik, attr, _markup(pal.get(role, 231)))
    if hasattr(ik, "_vip"):
        codes = [pal.get(r, 231) for r in ("number", "accent", "secondary")]
        ik._vip = lambda i, _c=codes: "bold color(%d)" % _c[i % len(_c)]
    if hasattr(ik, "_vip_num"):
        cyc = _vip_num_cycle(pal, vip.theme.name)
        ik._vip_num = lambda n, _m=cyc: "bold color(%d)" % _m.get(
            str(n), _m.get("5", 228))


class ProgressFrame:
    """A box that redraws in place (TTY) or as sequential frames (pipe)."""

    def __init__(self, vip, title="Working...", total=None):
        self.vip = vip
        self.title = title
        self.total = total
        self._height = None

    def show(self, pct=None, done=None, total=None, cur=None,
             speed=None, eta=None):
        total = total if total is not None else self.total
        box = self.vip.box.draw_progress(
            pct=pct, done=done, total=total, cur=cur, speed=speed, eta=eta,
            title=self.title)
        self.vip._paint_frame(box)

    def phase(self, text):
        self.show(cur=text)


# --------------------------------------------------------------- key screen
# The key screen is drawn by the compiled core, so what is fixed here is
# patched onto the strings on their way to the terminal. Nothing on the
# screen is redrawn — the prompt, the banner and the colours are untouched.
_BAD_KEY_MARK = "Invalid key!"
_KEY_PROMPT_MARK = "\U0001f511 Enter key:"

_TAG = re.compile(r"\[[^\[\]]*\]")
_BORDER = re.compile(r"[╭╰](?P<run>─+)[╮╯]")
_ROW_END = re.compile(r"^(?P<head>.*\])(?P<fill>[ \t]+)\u2502\[/\]$")


def _width(text):
    """Columns the terminal will actually spend on `text`.

    Markup is dropped first, and anything double-width (the key glyph, any
    CJK or emoji) is charged two columns, which is what a terminal does.
    """
    total = 0
    for ch in _TAG.sub("", text):
        if unicodedata.combining(ch):
            continue
        total += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
    return total


def _fix_bottom_corner(text):
    """The compiled bottom border closes with a top-right corner.

    It is built as '╰' + '─'*n + '╮', so the box shows '╮' exactly where a
    '╯' belongs. Only a line that already opens with '╰' is touched, which
    is the bottom border and nothing else on the screen.
    """
    if "╰" not in text:
        return text
    lines = text.split("\n")
    for i, line in enumerate(lines):
        if "╰" in line and line.rstrip().endswith("╮[/]"):
            lines[i] = line.rstrip()[:-len("╮[/]")] + "╯[/]"
    return "\n".join(lines)


class _KeyScreen:
    """Runs the compiled key screen under the rules it is missing.

    The compiled loop has no attempt counter and no end-of-input check, so
    a wrong key spins forever and a closed stdin hangs on the prompt with
    nothing on screen. Both are fixed here, from the outside, without
    redrawing a single line of the key screen itself.
    """

    MAX_ATTEMPTS = 3

    def __init__(self, vip):
        self.vip = vip
        self.ik = vip.ikram
        self.bad = 0
        self.inner = None        # dashes in the key box's top border
        self.prompt_w = None     # columns the prompt already spent
        self._console = None
        self._input = None

    # -- the two things the compiled screen gets wrong -------------------
    def _fit_row(self, text):
        """Size the key row's fill so the row lands on the border.

        The compiled core pads the row by arithmetic on len() of the label,
        which does not know that the key glyph renders two columns wide, so
        the row overshot the right border and wrapped. Rather than guess an
        offset, the fill is solved for: whatever makes the whole line exactly
        as wide as the border it sits between.
        """
        m = _ROW_END.match(text)
        if not m or self.inner is None or self.prompt_w is None:
            return text
        want = self.inner + 2 - self.prompt_w     # the two bars are counted
        have = _width(m.group("head") + m.group("fill") + "│")
        fill = m.group("fill")
        if have == want:
            return text
        pad = max(1, len(fill) + (want - have))
        return m.group("head") + " " * pad + "│[/]"

    def _print(self, *args, **kwargs):
        if args and isinstance(args[0], str):
            text = args[0]
            text = self._fit_row(text)
            text = _fix_bottom_corner(text)
            if _KEY_PROMPT_MARK in text:
                self.prompt_w = _width(text)
            else:
                b = _BORDER.search(_TAG.sub("", text))
                if b is not None:
                    self.inner = len(b.group("run"))
            if _BAD_KEY_MARK in text:
                self.bad += 1
            args = (text,) + args[1:]
        self._console.print(*args, **kwargs)
        if self.bad >= self.MAX_ATTEMPTS:
            # SystemExit is a BaseException: the compiled `except Exception`
            # around the prompt cannot swallow it, so this unwinds the loop
            # for good instead of re-asking a fourth time.
            raise SystemExit(1)

    def _ask(self, prompt=""):
        try:
            return self._input(prompt)
        except (EOFError, KeyboardInterrupt):
            raise SystemExit(1)

    # -- lifecycle --------------------------------------------------------
    def __enter__(self):
        import builtins
        self._console = self.ik.console
        self._input = builtins.input
        self.ik.console = _KeyConsole(self)
        builtins.input = self._ask
        return self

    def __exit__(self, *exc):
        import builtins
        if self._console is not None:
            self.ik.console = self._console
        builtins.input = self._input
        return False


class _KeyConsole:
    """Thin stand-in for the compiled core's rich Console during the key."""

    def __init__(self, screen):
        self._screen = screen
        self._real = screen._console

    def print(self, *args, **kwargs):
        self._screen._print(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._real, name)



class Vip:
    def __init__(self, ikram=None, stream=None):
        self.ikram = ikram
        self.stream = stream or sys.stdout
        self.theme = load_theme()
        self.box = BoxEngine(self.theme)
        self._frame_no = 0
        _sync_compiled_theme(self)

    # ------------------------------------------------------ io primitives
    def write(self, text):
        try:
            self.stream.write(text)
            flush = getattr(self.stream, "flush", None)
            if flush:
                flush()
        except Exception:
            _w(text)

    def _ask(self, prompt):
        """Read one line. Overridable in tests.

        Sets `_eof` when the input stream is gone. Every re-prompt loop must
        check it: input() keeps raising EOFError forever on a closed stdin, so
        a naive "not valid -> ask again" loop spins at 100% CPU instead of
        letting the tool exit.
        """
        self._eof = False
        try:
            ans = input(prompt)
        except EOFError:
            self._eof = True
            return ""
        except KeyboardInterrupt:
            self._eof = True
            return ""
        if is_tty():
            # Termux doesn't echo the Enter newline — advance the cursor so
            # the next screen/panel starts on a fresh line, never glued to
            # the "Choose ..." prompt.
            self.write("\n")
        return ans

    def _eof_answered(self, prompt=""):
        """_ask() plus a flag telling the caller the stream just closed."""
        return self._ask(prompt), bool(getattr(self, "_eof", False))

    def cls(self):
        if is_tty():
            self.write(CLS)

    def reset_term(self):
        if is_tty():
            self.write(C + "0m")

    def pause(self, sec=1.0):
        try:
            time.sleep(sec)
        except Exception:
            pass

    def wait_enter(self, label="Press ENTER to continue"):
        if label:
            self.write(self.theme.apply("  " + label + " ", "dim") + "\n")
        self._ask("")

    def _paint_frame(self, box):
        h = box.count("\n") + 1
        if not is_tty():
            self._frame_no += 1
            self.write("\n" + box + "\n")
            self.write(self.theme.apply("  [frame %d]  " % self._frame_no, "dim") + "\n")
            return
        if self._frame_no == 0:
            self.write(box + "\n")
        else:
            self.write(C + "%dA" % h + C + "J" + box + "\n")
        self._frame_no += 1

    # ------------------------------------------------------------- screens
    def header(self):
        return self.box.draw_box([], "thick", title="%s  %s" % (BRAND, VERSION),
                                 padding=0)

    def folder_rows(self):
        lines = []
        for label, folder in (("DROP/pak/", paths.DROP_PAK),
                              ("DROP/lua/", paths.DROP_LUA),
                              ("DROP/inject/", paths.DROP_INJECT)):
            files = paths.list_drop(folder)
            if files:
                n = len(files)
                size = paths.human(sum(f.stat().st_size for f in files))
                line = (self.theme.apply(label, "text")
                        + self.theme.apply(" %d files   %s" % (n, size),
                                           "success"))
            else:
                line = (self.theme.apply(label, "text")
                        + self.theme.apply(" (empty)", "dim"))
            lines.append(line)
        return [(None, lines)]

    def main_menu(self):
        blocks = [
            self.box.draw_menu([
                ("1", "📦 PAK TOOL (UNPACK, INJECT, REPACK)",
                 ["unpack, inject, repack pak files",
                  "COSTOM PAK: make empty pak all-in-one (option 4)"]),
                ("2", "📜 LUA TOOL (COMPILING, DECOMPILING)",
                 ["compile / decompile lua (auto-detect)"]),
                ("3", "🎨 THEMES",
                 ["switch the color theme of the whole tool"]),
            ] + self.folder_rows() + [
                ("0", "EXIT", ["close the tool"]),
            ], title="MAIN MENU (%s)" % VERSION.upper(), subtitle="choose a number"),
        ]
        return blocks

    def pak_menu(self):
        opts = [
            ("1", "📦 Unpack PAK",
             ["WORK: take all files out of the pak.",
              "PUT FILE IN: DROP/pak",
              "OUTPUT: RESULT/extracted/"]),
            ("2", "📦 Inject File",
             ["WORK: put any file (lua/uasset/asset) into the pak —",
              "type is found automatically and added to the game.",
              "1 file or all files at once — auto or manual path.",
              "PUT FILE IN: DROP/inject + DROP/pak",
              "OUTPUT: RESULT/injected/"]),
            ("3", "📦 Repack PAK",
             ["WORK: build the pak again.",
              "1) first UNPACK the pak",
              "2) edit files in RESULT/extracted",
              "3) old pak files are NEVER touched",
              "OUTPUT: RESULT/Repacked/"]),
            ("4", "📦 Costom Pak",
             ["WORK: make an empty pak.",
              "ENTER (no typing) = ALL folders + all file names",
              "but EMPTY files (real in game when injected).",
              "number = pick 1 folder · typed path = only that",
              "path + its files copied (not empty).",
              "PUT FILE IN: DROP/pak",
              "OUTPUT: RESULT/CostomPak/"]),
        ]
        rows = list(opts)
        rows += [
            ("C", "Clear DROP/pak/", ["wipe every file inside DROP/pak/"]),
            ("R", "Clear RESULT/", ["wipe every file inside RESULT/"]),
            ("0", "← Back", []),
        ]
        return [self.box.draw_menu(rows, title="📦 PAK TOOL 📦")]

    def lua_menu(self):
        opts = [
            ("1", "📜 Compile",
             ["WORK: make a game-ready compiled file from source.",
              "PUT FILE IN: DROP/lua",
              "OUTPUT: RESULT/lua/"]),
            ("2", "📜 Decompile",
             ["WORK: make readable source from a compiled file.",
              "accepts any compiled file type (lua, uasset, uexp, ir, bin, dat).",
              "PUT FILE IN: DROP/lua",
              "OUTPUT: RESULT/lua/"]),
        ]
        rows = list(opts)
        rows += [
            ("C", "Clear DROP/lua/", ["wipe every file inside DROP/lua/"]),
            ("R", "Clear RESULT/lua/", ["wipe every file inside RESULT/lua/"]),
            ("0", "← Back", []),
        ]
        return [self.box.draw_menu(rows, title="📜 LUA TOOL 📜")]

    def themes_menu(self):
        rows = []
        for i, name in enumerate(THEMES, 1):
            th = Theme(name)
            line = (self.theme.apply(str(i), "number") + "  "
                    + th.emoji() + " "
                    + th.apply(name, "primary"))
            if name == self.theme.name:
                line += self.theme.apply("   ← ✓", "success")
            rows.append(line)
        rows.append(("0", "← Back", []))
        return [self.box.draw_menu(rows, title="🎨 THEMES 🎨")]

    def _opt(self, digit, label, role="text"):
        cyc = _vip_num_cycle(self.theme._pal, self.theme.name)
        n = self.theme.paint_code(str(digit), cyc.get(str(digit), cyc["5"]))
        return "  " + n + "  " + self.theme.apply(label, role)

    def _opt_box(self, opt, style="light"):
        digit, name, help_lines = opt
        rows = [self._opt(digit, name, "primary")]
        for h in help_lines:
            rows.append("    " + self.theme.apply(h, "dim"))
        return self.box.draw_box(rows, style)

    # ------------------------------------------------------------- flows
    def prompt_in(self, choices, label):
        while True:
            self.write("  " + self.theme.apply(label, "prompt") + " ")
            ans, eof = self._eof_answered("")
            ans = ans.strip().lower()
            if ans in choices:
                return ans
            if eof:
                # stdin is gone: treat as back so the menu unwinds instead of
                # re-asking forever.
                return choices[-1] if choices else "0"
            self.invalid_box()

    def invalid_box(self):
        self._status_box([
            "✗ Invalid option",
            "Enter a number from the menu",
        ], "light", "warn")
        self.pause(0.6)

    def _status_box(self, lines, style, role):
        b = self.box.draw_box(lines, style, color_role=role)
        self.write(b + "\n")

    def success_box(self, lines):
        self._status_box(lines, "rounded", "success")

    def error_box(self, lines, next_step=None):
        rows = list(lines)
        if next_step:
            rows.append("")
            rows.append("Next : " + next_step)
        self._status_box(rows, "thick", "error")

    def warn_box(self, lines):
        self._status_box(lines, "light", "warn")

    def proceed_box(self, operation, src_label, files, out_label, extra=None):
        rows = [
            self.box.draw_labeled_row("Operation", str(operation), "secondary", "accent"),
            self.box.draw_labeled_row("Input", str(src_label)),
        ]
        if files:
            shown = list(files[:3])
            if len(files) > 3:
                shown.append("  … +%d more" % (len(files) - 3))
            for f in shown:
                rows.append(self.theme.apply("  • " + str(f), "text"))
        rows.append(self.box.draw_labeled_row("Output", str(out_label)))
        if extra:
            for e in extra:
                rows.append(self.theme.apply("  " + str(e), "secondary"))
        rows.append(SEP)
        rows.append("  " + self.theme.apply("[ Y ] Proceed", "success")
                    + "      " + self.theme.apply("[ N ] Cancel", "warn"))
        self.write(self.box.draw_box(rows, "thick", title="Proceed?") + "\n")
        self.write("  " + self.theme.apply("Proceed? (Y/N) ", "prompt") + " ")
        ans, eof = self._eof_answered("")
        ans = ans.strip().lower()
        while ans not in ("y", "n"):
            if eof:
                return False
            self.invalid_box()
            self.write("  " + self.theme.apply("Proceed? (Y/N) ", "prompt") + " ")
            ans, eof = self._eof_answered("")
            ans = ans.strip().lower()
        return ans == "y"

    def confirm_box(self, title, label, yes_label="Delete"):
        self.write(self.box.draw_box([
            "  " + self.theme.apply(label, "text"),
            SEP,
            "  " + self.theme.apply("[ Y ] %s" % yes_label, "error")
            + "      " + self.theme.apply("[ N ] Cancel", "warn"),
        ], "heavy", title=title) + "\n")
        self.write("  " + self.theme.apply("Confirm? (Y/N) ", "prompt") + " ")
        ans, eof = self._eof_answered("")
        ans = ans.strip().lower()
        while ans not in ("y", "n"):
            if eof:
                return False
            self.invalid_box()
            self.write("  " + self.theme.apply("Confirm? (Y/N) ", "prompt") + " ")
            ans, eof = self._eof_answered("")
            ans = ans.strip().lower()
        return ans == "y"

    # ------------------------------------------------------------- returns
    def exit_screen(self):
        self.cls()
        self.write(self.box.draw_box([
            self.theme.apply("Thanks for using %s" % BRAND, "primary"),
        ], "rounded", title="%s  %s" % (BRAND, VERSION)) + "\n")
        self.pause(1.0)
        self.reset_term()

    def _key_gate(self):
        """True = key accepted, carry on. False = leave, tool is done.

        The screen is the compiled core's own; this only supplies the two
        rules it lacks — three strikes and a real answer to a closed stdin.
        """
        screen = _KeyScreen(self)
        try:
            with screen:
                ok = self.ikram.key_lock()
        except SystemExit:
            if screen.bad >= screen.MAX_ATTEMPTS:
                self.cls()
                err = getattr(self.ikram, "ERROR", "color(196)")
                # rich markup, printed by rich — the key screen's own
                # messages go through the console and this one matches them.
                self.ikram.console.print(
                    "\n[bold %s]✘ Too many attempts. Exiting.[/]" % err)
                self.reset_term()
            return False
        return bool(ok)

    # ------------------------------------------------------------- run
    def run(self):
        paths.ensure_dirs()
        if self.ikram is not None:
            if not self._key_gate():
                return
            self.ikram.welcome_splash()
        got = None
        try:
            while True:
                self.cls()
                self.write("\n\n".join(self.main_menu()) + "\n")
                got = self.prompt_in(("1", "2", "3", "0"), "➜ SELECT:")
                if got == "0":
                    self.exit_screen()
                    return
                self.cls()
                if got == "1":
                    self.run_pak()
                elif got == "2":
                    self.run_lua()
                elif got == "3":
                    self.run_themes()
        except KeyboardInterrupt:
            self.exit_screen()
        except Exception as e:
            self.cls()
            self.reset_term()
            import traceback
            self.error_box(["✗ Unexpected error",
                            str(e)[:80]],
                           next_step="Restart and try again.")
            return

    # ------------------------------------------------------------- actions
    def logged(self, name, **extra):
        """Record an action that needs no call of its own (a setting, say)."""
        import telemetry
        return telemetry.send_event(name, status="OK", **extra)

    def act(self, name, fn, *args, **kwargs):
        """Run one menu action, and write it to the local action log.

        Every choice in every menu goes through here, which is the only way
        to guarantee an action is never run unlogged: the log line is
        written after the action returns, and a failure is recorded before
        the exception is allowed to keep travelling. The log is local
        (telemetry.log beside the tool) and a failed write is ignored, so
        this can never turn a working action into a broken one.
        """
        import telemetry
        started = time.time()
        try:
            out = fn(*args, **kwargs)
        except BaseException as exc:                   # noqa: BLE001
            telemetry.send_error(exc, extra=name)
            raise
        self.logged(name, ms=int((time.time() - started) * 1000))
        return out

    def run_pak(self):
        import menus
        while True:
            self.cls()
            self.write("\n\n".join(self.pak_menu()) + "\n")
            got = self.prompt_in(("1", "2", "3", "4", "c", "r", "0"), "➜ SELECT:")
            if got == "0":
                return
            self.cls()
            if got == "1":
                self.act("pak.unpack", menus.pak_unpack, self)
            elif got == "2":
                self.act("pak.inject", menus.pak_inject, self)
            elif got == "3":
                self.act("pak.repack", menus.pak_repack, self)
            elif got == "4":
                self.act("pak.custom", menus.pak_custom, self)
            elif got == "c":
                self.act("pak.clear_drop", menus.clear_drop_pak, self)
            elif got == "r":
                self.act("pak.clear_result", menus.clear_result, self)

    def run_lua(self):
        import menus
        import lua_pipeline
        if not getattr(self, "_deps_checked", False):
            self._deps_checked = True
            deps = lua_pipeline.deps_status()
            if deps["missing"]:
                self.cls()
                want = self.confirm_box(
                    "DEPENDENCY CHECK",
                    "Some Lua tools are missing:\n  %s\n\n  Install them now?"
                    % "\n  ".join(deps["missing"][:6]),
                    yes_label="Install")
                if want:
                    frame = ProgressFrame(self, title="Installing missing tools")
                    results = lua_pipeline.install_missing(progress=frame)
                    frame.show(pct=100, cur="Finished")
                    ok_n = sum(1 for _c, ok, _t in results if ok)
                    self.cls()
                    self.write(self.box.draw_box([
                        self.theme.apply("✓ Tools installed: %d/%d"
                                         % (ok_n, len(results)), "success"),
                    ], "rounded", title="Setup") + "\n")
                    self.pause(1.5)
        while True:
            self.cls()
            self.write("\n\n".join(self.lua_menu()) + "\n")
            got = self.prompt_in(("1", "2", "c", "r", "0"), "➜ SELECT:")
            if got == "0":
                return
            self.cls()
            if got == "1":
                self.act("lua.compile", menus.lua_compile, self)
            elif got == "2":
                self.act("lua.decompile", menus.lua_decompile, self)
            elif got == "c":
                self.act("lua.clear_drop", menus.clear_drop_lua, self)
            elif got == "r":
                self.act("lua.clear_result", menus.clear_result_lua, self)

    def run_themes(self):
        while True:
            self.cls()
            self.write("\n\n".join(self.themes_menu()) + "\n")
            got = self.prompt_in(
                tuple(str(i) for i in range(1, len(THEMES) + 1)) + ("0",),
                "Choose theme")
            if got == "0":
                return
            name = THEMES[int(got) - 1]
            changed = name != self.theme.name
            if changed:
                save_theme(name)
                self.theme = Theme(name)
                self.box = BoxEngine(self.theme)
                _sync_compiled_theme(self)
            self.logged("theme.set", file=name, changed=changed)
            self.cls()
            self.write(self.box.draw_box([
                self.theme.apply(name, "primary"),
            ], "rounded", title="Theme set") + "\n")
            self.pause(1.5)
            return  # back to MAIN menu, not to the theme list