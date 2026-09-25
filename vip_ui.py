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

VERSION = "v117"
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
    """V111 number colour cycle: 0→183, 1→45, 2→51, 3→39, 4→118, 5→119.
    Other themes map the same six slots through their own palette so the
    UI shape stays byte-identical everywhere."""
    if theme_name == "Original Color":
        return {"0": 183, "1": 45, "2": 51, "3": 39, "4": 118, "5": 119}
    base = pal.get("number", 45)
    return {"0": base, "1": base, "2": pal.get("secondary", 51),
            "3": pal.get("accent", 141), "4": pal.get("warn", 214),
            "5": pal.get("primary", 228)}


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
        """Read one line. Overridable in tests."""
        try:
            ans = input(prompt)
        except EOFError:
            return ""
        except KeyboardInterrupt:
            return ""
        if is_tty():
            # Termux doesn't echo the Enter newline — advance the cursor so
            # the next screen/panel starts on a fresh line, never glued to
            # the "Choose ..." prompt.
            self.write("\n")
        return ans

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
        self.write(self.box.draw_box(rows, "thick", title="Proceed?") + "\n")
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
            self.write("\n\n".join(self.lua_menu()) + "\n")
            got = self.prompt_in(("1", "2", "c", "r", "0"), "➜ SELECT:")
            if got == "0":
                return
            self.cls()
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
            self.write("\n\n".join(self.themes_menu()) + "\n")
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
                _sync_compiled_theme(self)
            self.cls()
            self.write(self.box.draw_box([
                self.theme.apply(name, "primary"),
            ], "rounded", title="Theme set") + "\n")
            self.pause(1.5)
            return  # back to MAIN menu, not to the theme list