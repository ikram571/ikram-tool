"""IkramTool V112 — VIP shell.

Owns the screen: header, menu loops, submenus, folder status, prompts,
PROCEED box, progress frames, status boxes, invalid-input box, theme
switcher, clears, exit + terminal restore. Every menu option is dispatched
to a REAL handler in menus.py or lua_pipeline.py. Nothing on screen is
un-boxed; the only non-boxed line allowed anywhere is the Press-ENTER
`minimal` divider.

All user input funnels through `_ask()`, so tests can script whole flows
without a terminal.
"""
import sys
import time

from theme_engine import Theme, load_theme, save_theme, THEMES, is_tty
from box_engine import BoxEngine, SEP
import paths

VERSION = "v112"
BRAND = "IkramTool"
C = "\x1b["
RESET = C + "0m"
CLS = C + "2J" + C + "H" + C + "0m"

CLEAR_PAK_DROP = "CLEAR DROP FOLDER"
CLEAR_RESULT = "CLEAR RESULT FOLDER"


def _w(text):
    sys.stdout.write(text)
    sys.stdout.flush()


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


class Vip:
    def __init__(self, ikram=None, stream=None):
        self.ikram = ikram
        self.stream = stream or sys.stdout
        self.theme = load_theme()
        self.box = BoxEngine(self.theme)
        self._frame_no = 0

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
        """Read one line. Overridable in tests."""
        try:
            return input(prompt)
        except EOFError:
            return ""
        except KeyboardInterrupt:
            return ""

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
        return self.box.draw_box([], "heavy", title="%s  %s" % (BRAND, VERSION),
                                 padding=0)

    def folder_rows(self):
        rows = []
        for label, folder in (("DROP/pak/", paths.DROP_PAK),
                              ("DROP/lua/", paths.DROP_LUA),
                              ("DROP/inject/", paths.DROP_INJECT)):
            files = paths.list_drop(folder)
            if files:
                n = len(files)
                size = paths.human(sum(f.stat().st_size for f in files))
                rows.append("  " + self.theme.apply(label, "dim")
                            + self.theme.apply(" %d files   %s" % (n, size),
                                               "success"))
            else:
                rows.append("  " + self.theme.apply(label, "dim")
                            + self.theme.apply(" (empty)", "dim"))
        return rows

    def main_menu(self):
        rows = [
            self._opt("1", "PAK Tool"),
            self._opt("2", "Lua Tool"),
            self._opt("3", "Themes"),
            SEP,
        ] + self.folder_rows() + [
            SEP,
            self._opt("0", "Exit"),
        ]
        return rows

    def pak_menu(self):
        return [
            self._opt("1", "Unpack"),
            self._opt("2", "Inject"),
            self._opt("3", "Repack"),
            self._opt("4", "Costom Pak"),
            SEP,
            self._opt("C", "Clear DROP/pak/"),
            self._opt("R", "Clear RESULT/"),
            SEP,
            self._opt("0", "← Back"),
        ]

    def lua_menu(self):
        return [
            self._opt("1", "Compile"),
            self._opt("2", "Decompile"),
            SEP,
            self._opt("C", "Clear DROP/lua/"),
            self._opt("R", "Clear RESULT/lua/"),
            SEP,
            self._opt("0", "← Back"),
        ]

    def themes_menu(self):
        rows = []
        for name in THEMES:
            th = Theme(name)
            mark = "   ← ✓" if name == self.theme.name else ""
            row = "  " + th.emoji() + " " + th.apply(name, "primary")
            if mark:
                row += self.theme.apply(mark, "success")
            rows.append(row)
        rows.append(SEP)
        rows.append(self._opt("0", "← Back"))
        return rows

    def _opt(self, digit, label, role="text"):
        return "  " + self.theme.apply(digit, "number") + "  " + self.theme.apply(label, role)

    # ------------------------------------------------------------- flows
    def prompt_in(self, choices, label):
        while True:
            self.write("  " + self.theme.apply(label, "prompt") + " ")
            ans = self._ask("").strip().lower()
            if ans in choices:
                return ans
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
        self.write(self.box.draw_box(rows, "heavy", title="Proceed?") + "\n")
        self.write("  " + self.theme.apply("Proceed? (Y/N) ", "prompt") + " ")
        ans = self._ask("").strip().lower()
        while ans not in ("y", "n"):
            self.invalid_box()
            self.write("  " + self.theme.apply("Proceed? (Y/N) ", "prompt") + " ")
            ans = self._ask("").strip().lower()
        return ans == "y"

    def confirm_box(self, title, label, yes_label="Delete"):
        self.write(self.box.draw_box([
            "  " + self.theme.apply(label, "text"),
            SEP,
            "  " + self.theme.apply("[ Y ] %s" % yes_label, "error")
            + "      " + self.theme.apply("[ N ] Cancel", "warn"),
        ], "heavy", title=title) + "\n")
        self.write("  " + self.theme.apply("Confirm? (Y/N) ", "prompt") + " ")
        ans = self._ask("").strip().lower()
        while ans not in ("y", "n"):
            self.invalid_box()
            self.write("  " + self.theme.apply("Confirm? (Y/N) ", "prompt") + " ")
            ans = self._ask("").strip().lower()
        return ans == "y"

    # ------------------------------------------------------------- returns
    def exit_screen(self):
        self.cls()
        self.write(self.box.draw_box([
            self.theme.apply("Thanks for using %s" % BRAND, "primary"),
        ], "rounded", title="%s  %s" % (BRAND, VERSION)) + "\n")
        self.pause(1.0)
        self.reset_term()

    # ------------------------------------------------------------- run
    def run(self):
        paths.ensure_dirs()
        if self.ikram is not None:
            if not self.ikram.key_lock():
                return
            self.ikram.welcome_splash()
        got = None
        try:
            while True:
                self.cls()
                self.write(self.box.draw_box(self.main_menu(),
                                             "heavy", title="%s  %s" % (BRAND, VERSION)) + "\n")
                got = self.prompt_in(("1", "2", "3", "0"), "Choose")
                if got == "0":
                    self.exit_screen()
                    return
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

    def run_pak(self):
        import menus
        while True:
            self.cls()
            self.write(self.box.draw_box(self.pak_menu(),
                                         "heavy", title="PAK TOOL") + "\n")
            got = self.prompt_in(("1", "2", "3", "4", "c", "r", "0"), "Choose")
            if got == "0":
                return
            if got == "1":
                menus.pak_unpack(self)
            elif got == "2":
                menus.pak_inject(self)
            elif got == "3":
                menus.pak_repack(self)
            elif got == "4":
                menus.pak_custom(self)
            elif got == "c":
                menus.clear_drop_pak(self)
            elif got == "r":
                menus.clear_result(self)

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
                    frame.close(cur="Finished")
                    ok_n = sum(1 for _c, ok, _t in results if ok)
                    self.cls()
                    self.write(self.box.draw_box([
                        self.theme.apply("✓ Tools installed: %d/%d"
                                         % (ok_n, len(results)), "success"),
                    ], "rounded", title="Setup") + "\n")
                    self.pause(1.5)
        while True:
            self.cls()
            self.write(self.box.draw_box(self.lua_menu(),
                                         "heavy", title="LUA TOOL") + "\n")
            got = self.prompt_in(("1", "2", "c", "r", "0"), "Choose")
            if got == "0":
                return
            if got == "1":
                menus.lua_compile(self)
            elif got == "2":
                menus.lua_decompile(self)
            elif got == "c":
                menus.clear_drop_lua(self)
            elif got == "r":
                menus.clear_result_lua(self)

    def run_themes(self):
        while True:
            self.cls()
            self.write(self.box.draw_box(self.themes_menu(),
                                         "heavy", title="THEMES") + "\n")
            got = self.prompt_in(
                tuple(str(i) for i in range(1, len(THEMES) + 1)) + ("0",),
                "Choose theme")
            if got == "0":
                return
            name = THEMES[int(got) - 1]
            if name != self.theme.name:
                save_theme(name)
                self.theme = Theme(name)
                self.box = BoxEngine(self.theme)
            self.cls()
            self.write(self.box.draw_box([
                self.theme.apply(name, "primary"),
            ], "rounded", title="Theme set") + "\n")
            self.pause(1.5)
            return  # back to MAIN menu, not to the theme list