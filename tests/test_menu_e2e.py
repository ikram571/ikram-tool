"""E2E for the VIP shell: dispatch, navigation, themes, and the real clears.

Real Vip subclass — only the terminal side effects (write/cls/pause/paint)
are neutralised, so menu rendering, prompt_in, run_pak/run_lua/run_themes
and the dispatch tables are the shipped code paths.

A. dispatch matrix: every advertised option reaches the right handler
B. themes: all 267 selectable, persisted, re-applied on a fresh load
C. navigation: invalid input re-prompts, 0 backs out of each level,
   0 at the main menu exits
D. real clears: CLEAR DROP FOLDER / CLEAR RESULT FOLDER actually purge
"""
import importlib
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import paths as P
import menus
import vip_ui
from vip_ui import Vip

PASS = FAIL = 0
FAILURES = []


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok   %s" % name)
    else:
        FAIL += 1
        FAILURES.append(name)
        print("  FAIL %s   %s" % (name, extra))


class ScriptedVip(Vip):
    """Real Vip, scripted input, recorded output, no terminal side effects."""

    def __init__(self, answers, ikram=None):
        self.answers = list(answers)
        self.log = []
        super().__init__(ikram=ikram, stream=io.StringIO())
        self.theme = vip_ui.load_theme()
        self.box = vip_ui.BoxEngine(self.theme)

    def write(self, text=""):
        self.log.append(str(text))

    def _ask(self, prompt=""):
        self.log.append(prompt)
        return self.answers.pop(0) if self.answers else "0"

    def cls(self):
        pass

    def reset_term(self):
        pass

    def pause(self, sec=1.0):
        pass

    def _paint_frame(self, box):
        self.log.append("FRAME")

    def out(self):
        return "".join(self.log)

    def asked(self, needle):
        return any(needle in x for x in self.log)


import io  # noqa: E402  (used by ScriptedVip.__init__)


RECORDED = []


def _recorder(name):
    def _f(vip):
        RECORDED.append(name)
        return None
    return _f


def stub_menus():
    """Replace every handler with a recorder so dispatch can be observed."""
    names = ("pak_unpack", "pak_inject", "pak_repack", "pak_custom",
             "clear_drop_pak", "clear_result",
             "lua_compile", "lua_decompile",
             "clear_drop_lua", "clear_result_lua")
    saved = {}
    for n in names:
        saved[n] = getattr(menus, n)
        setattr(menus, n, _recorder(n))
    return saved


def restore_menus(saved):
    for n, f in saved.items():
        setattr(menus, n, f)


# ----------------------------------------------------------------- A
def test_dispatch():
    print("\n[A] dispatch matrix")
    saved = stub_menus()
    try:
        cases = [
            # (script, expected handler sequence, label)
            (["1", "1", "0", "0"], ["pak_unpack"], "main1 -> pak1 unpack"),
            (["1", "2", "0", "0"], ["pak_inject"], "main1 -> pak2 inject"),
            (["1", "3", "0", "0"], ["pak_repack"], "main1 -> pak3 repack"),
            (["1", "4", "0", "0"], ["pak_custom"], "main1 -> pak4 costom"),
            (["1", "c", "0", "0"], ["clear_drop_pak"], "main1 -> pakC clear drop"),
            (["1", "r", "0", "0"], ["clear_result"], "main1 -> pakR clear result"),
            (["2", "1", "0", "0"], ["lua_compile"], "main2 -> lua1 compile"),
            (["2", "2", "0", "0"], ["lua_decompile"], "main2 -> lua2 decompile"),
            (["2", "c", "0", "0"], ["clear_drop_lua"], "main2 -> luaC clear drop"),
            (["2", "r", "0", "0"], ["clear_result_lua"], "main2 -> luaR clear result"),
            (["3", "0", "0"], [], "main3 themes -> back"),
            (["0"], [], "main0 exit"),
        ]
        for script, expect, label in cases:
            RECORDED.clear()
            v = ScriptedVip(script)
            v.run()
            check(label, RECORDED == expect, "got %s want %s" % (RECORDED, expect))
            check(label + " :: no unexpected-error box",
                  "Unexpected error" not in v.out(), v.out()[-200:])
    finally:
        restore_menus(saved)


def test_every_advertised_option_has_a_handler():
    print("\n[A2] every advertised option maps to a real callable")
    saved = stub_menus()
    try:
        # walk the pak and lua menus and check the declared choices dispatch
        for menu_choices, runner, label in (
                (("1", "2", "3", "4", "c", "r", "0"), Vip.run_pak, "pak"),
                (("1", "2", "c", "r", "0"), Vip.run_lua, "lua")):
            for ch in menu_choices:
                if ch == "0":
                    continue
                RECORDED.clear()
                v = ScriptedVip([ch, "0", "0", "0"])
                v._deps_checked = True
                getattr(v, runner.__name__)()
                check("%s option %r dispatched" % (label, ch),
                      len(RECORDED) == 1, str(RECORDED))
    finally:
        restore_menus(saved)


# ----------------------------------------------------------------- B
def test_themes():
    print("\n[B] themes: all 267 selectable + persisted + reapplied")
    from theme_engine import THEMES, Theme, load_theme, save_theme
    orig = load_theme().name
    try:
        check("267 themes defined", len(THEMES) == 267, str(len(THEMES)))
        check("theme names are unique", len(set(THEMES)) == len(THEMES),
              "%d unique of %d" % (len(set(THEMES)), len(THEMES)))

        # every single theme must be selectable AND persist to disk
        bad_select, bad_persist = [], []
        for i, name in enumerate(THEMES, start=1):
            v = ScriptedVip([str(i), "0", "0", "0"])
            v.run_themes()
            if "Unexpected error" in v.out():
                bad_select.append((i, name))
                continue
            if v.theme.name != name:
                bad_select.append((i, name, v.theme.name))
            # and it must survive a fresh load from disk
            if load_theme().name != name:
                bad_persist.append((i, name, load_theme().name))
        check("all 267 selectable via the menu", not bad_select,
              str(bad_select[:4]))
        check("all 267 persist to disk", not bad_persist, str(bad_persist[:4]))

        # a fresh Vip must come up wearing the persisted theme
        save_theme(THEMES[66])
        fresh = ScriptedVip(["0", "0", "0"])
        check("fresh Vip re-applies persisted theme",
              fresh.theme.name == THEMES[66],
              "%s want %s" % (fresh.theme.name, THEMES[66]))

        # themes must actually change the rendered output, not just the name.
        # Colour is off when stdout is not a TTY (by design), so force a
        # 256-colour terminal for this check or every theme renders plain.
        import theme_engine as _te
        real_support = _te.color_support
        _te.color_support = lambda: 256
        try:
            renders = {}
            for nm in THEMES:
                renders.setdefault(Theme(nm).apply("SAMPLE", "primary"), []).append(nm)
            check("themes produce many distinct renders (TTY)",
                  len(renders) > 20, "%d distinct renders" % len(renders))
            check("every role is coloured for a palette theme",
                  all(Theme(THEMES[66]).apply("S", r).startswith("\x1b[")
                      for r in _te.ROLES),
                  "a role rendered plain on a 256-colour terminal")
        finally:
            _te.color_support = real_support
        # now that the real detector is back in place, force the non-TTY case
        # and prove the escape codes really are dropped
        _te.color_support = lambda: False
        try:
            plain = Theme(THEMES[66]).apply("S", "primary")
            check("colours are disabled when not a TTY",
                  "\x1b[" not in plain and plain.strip() != "",
                  "render still had escapes: %r" % plain[:60])
            check("text still renders when colour is off", "S" in plain,
                  "role text lost: %r" % plain[:60])
        finally:
            _te.color_support = real_support
        bgs = {Theme(nm).bg for nm in THEMES}
        pals = {tuple(sorted(Theme(nm)._pal.items())) for nm in THEMES}
        check("themes have distinct backgrounds", len(bgs) > 20,
              "%d distinct bg" % len(bgs))
        check("themes have distinct palettes", len(pals) > 20,
              "%d distinct palettes" % len(pals))

        # out-of-range selection must be rejected, not crash
        before = load_theme().name
        v = ScriptedVip(["9999", "0", "0"])
        v.run_themes()
        check("out-of-range theme rejected cleanly",
              "Unexpected error" not in v.out() and "Invalid option" in v.out(),
              v.out()[-160:])
        check("out-of-range left theme unchanged", load_theme().name == before,
              "%s want %s" % (load_theme().name, before))

        # 0 backs out without changing anything
        before = load_theme().name
        v = ScriptedVip(["0"])
        v.run_themes()
        check("theme 0 exits without changing", load_theme().name == before)
    finally:
        save_theme(orig)


# ----------------------------------------------------------------- C
def test_navigation():
    print("\n[C] navigation: invalid input, back, exit")
    saved = stub_menus()
    try:
        # invalid main input re-prompts, then 1 enters pak and 1 unpacks
        RECORDED.clear()
        v = ScriptedVip(["9", "x", "1", "1", "0", "0"])
        v.run()
        check("invalid main input re-prompts",
              v.asked("SELECT") and "Unexpected error" not in v.out(),
              v.out()[-200:])
        check("invalid main input then reached pak", "pak_unpack" in RECORDED,
              str(RECORDED))

        # invalid pak input re-prompts
        RECORDED.clear()
        v = ScriptedVip(["1", "7", "1", "0", "0"])
        v.run()
        check("invalid pak input re-prompts, then runs",
              RECORDED == ["pak_unpack"], str(RECORDED))

        # 0 inside pak backs to main, then 0 exits
        RECORDED.clear()
        v = ScriptedVip(["1", "0", "0"])
        v.run()
        check("pak 0 backs to main, main 0 exits",
              RECORDED == [] and "Unexpected error" not in v.out(),
              str(RECORDED))

        # exit_screen ran
        v = ScriptedVip(["0"])
        v.run()
        check("main 0 calls exit_screen", "Bye" in v.out() or "exit" in v.out().lower(),
              v.out()[-120:])
    finally:
        restore_menus(saved)


# ----------------------------------------------------------------- D
def test_real_clears():
    print("\n[D] real clears purge the right folders")
    drop_pak = P.DROP_PAK
    res = P.RESULT_EXTRACTED
    # seed
    for d, name in ((drop_pak, "x.pak"), (res, "y.txt")):
        d.mkdir(parents=True, exist_ok=True)
        (d / name).write_bytes(b"seed")
    try:
        # clear drop/pak
        v = ScriptedVip(["y", ""])
        menus.clear_drop_pak(v)
        check("clear_drop_pak emptied DROP/pak",
              not any(drop_pak.glob("*.pak")), str(list(drop_pak.glob("*"))))
        check("clear_drop_pak left RESULT alone", (res / "y.txt").exists())

        # clear result
        v = ScriptedVip(["y", ""])
        menus.clear_result(v)
        check("clear_result emptied RESULT/extracted",
              not res.exists() or not any(res.iterdir()),
              str(list(res.glob("*")) if res.exists() else []))
    finally:
        for p in (drop_pak / "x.pak", res / "y.txt"):
            try:
                p.unlink()
            except FileNotFoundError:
                pass


def test_eof_no_hang():
    """Closed stdin must unwind, not spin re-prompting forever."""
    print("\n[E] closed stdin does not hang")

    class EofVip(ScriptedVip):
        def __init__(self, **kw):
            self.asks = 0
            super().__init__([], **kw)

        def _ask(self, prompt=""):
            self.asks += 1
            if self.asks > 200:
                raise AssertionError("re-prompt loop spun %d times" % self.asks)
            # exactly what Vip._ask leaves behind after EOFError
            self._eof = True
            return ""

    v = EofVip(ikram=None)
    got = v.prompt_in(("1", "2", "3", "0"), "SELECT:")
    check("prompt_in unwinds on EOF", got == "0" and v.asks == 1,
          "got %r after %d asks" % (got, v.asks))

    v = EofVip(ikram=None)
    r = v.proceed_box("op", "src", None, "out")
    check("proceed_box cancels on EOF", r is False and v.asks == 1,
          "got %r after %d asks" % (r, v.asks))

    v = EofVip(ikram=None)
    r = v.confirm_box("t", "l")
    check("confirm_box cancels on EOF", r is False and v.asks == 1,
          "got %r after %d asks" % (r, v.asks))

    # and the whole shell must exit rather than loop
    v = EofVip(ikram=None)
    try:
        v.run()
        check("full run() returns on closed stdin", True)
    except AssertionError as e:
        check("full run() returns on closed stdin", False, str(e))


def main():
    test_dispatch()
    test_every_advertised_option_has_a_handler()
    test_themes()
    test_navigation()
    test_real_clears()
    test_eof_no_hang()
    print("\n%d passed, %d failed" % (PASS, FAIL))
    if FAILURES:
        print("failed:", FAILURES)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
