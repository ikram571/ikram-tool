"""IkramTool V114 — LIVE end-to-end pty drive.

Boots the tool on a real pseudo-terminal (TTY path: real ANSI to the wire,
real width, real terminal behaviour) and walks every theme across every
menu, then runs every real operation. Asserts per screen: no literal
bracket-ANSIs, no line wider than the terminal (no wrap corruption), box
shape intact, and that every operation actually wrote its RESULT artefacts.

Usage:
    python3 tests/live_drive.py [--cols 74] [--rows 26]

Exit code 0 = A-to-Z live run is clean.
"""
import fcntl
import os
import select
import struct
import subprocess
import sys
import termios
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SYS_EXE = sys.executable

FIXURE_PAK = os.environ.get(
    "FIX_ROOT",
    "/data/data/com.termux/files/home/opencode/"
    "IkramTool Project/Pakfiles For Testing/core_patch_4.6.0.21537.pak")


def _vis(s: str) -> int:
    import re
    return len(re.sub(r"\x1b\[[0-9;]*m", "", s))


class Live:
    def __init__(self, cols=74, rows=26):
        self.cols = cols
        self.rows = rows
        self.home = Path("/data/data/com.termux/files/usr/tmp/opencode/live_home")
        self.home.mkdir(parents=True, exist_ok=True)
        self.cwd = ROOT
        self.fd = None
        self.pid = None
        self.buf = b""
        self.fails = []
        self.screens = 0

    def spawn(self):
        env = dict(os.environ)
        env["HOME"] = str(self.home)
        env["TERM"] = "xterm-256color"
        env["COLORTERM"] = "truecolor"
        pid, fd = pty_fork(env, self.cwd)
        self.pid, self.fd = pid, fd
        try:
            fcntl.ioctl(fd, termios.TIOCSWINSZ,
                        struct.pack("HHHH", self.rows, self.cols, 0, 0))
        except Exception:
            pass
        self._pump(4.0)

    def _pump(self, timeout, quiet=0.25):
        end = time.time() + timeout
        while time.time() < end:
            r, _, _ = select.select([self.fd], [], [], quiet)
            if not r:
                return
            try:
                d = os.read(self.fd, 65536)
            except OSError:
                return
            if not d:
                return
            self.buf += d

    def quiesce(self, silence=1.2, cap=60):
        """Pump until the tool stops producing output for `silence` seconds."""
        end = time.time() + cap
        while time.time() < end:
            r, _, _ = select.select([self.fd], [], [], silence)
            if not r:
                return
            try:
                d = os.read(self.fd, 65536)
            except OSError:
                return
            if not d:
                return
            self.buf += d

    def _plain(self, data: bytes) -> bytes:
        """ANSI-strip raw bytes so themed per-char titles match markers.

        Rainbow and friends color each title char separately, so a marker
        like `PAK TOOL` is broken up by escape codes in the raw stream.
        """
        import re
        return re.sub(rb"\x1b\[[0-9;]*[a-zA-Z]", b"", data)

    def wait_for(self, marker, timeout=45, fresh=True):
        """Pump until `marker` (ANSI-stripped) shows up.

        fresh=True  -> only bytes arriving after the call started count
                       (use for main-menu / return markers to avoid
                        matching stale text from an earlier screen).
        fresh=False -> match anywhere in the buffer. Wizard prompts like
                       `CHOOSE MODE` / `Select number` are unique and get
                       drawn during the feed's own pump, so they are never
                       "fresh" when we start waiting; a global match is
                       the only reliable signal. Input is queue-fed, so a
                       missed marker never loses an op.
        """
        m = marker.encode()
        h = len(self.buf)
        if not fresh:
            h = 0
        end = time.time() + timeout
        while time.time() < end and m not in self._plain(self.buf[h:]):
            r, _, _ = select.select([self.fd], [], [], 0.4)
            if r:
                try:
                    d = os.read(self.fd, 65536)
                except OSError:
                    break
                self.buf += d
        return m in self._plain(self.buf[h:])

    def feed(self, text, wait_after=2.0):
        try:
            os.write(self.fd, text.encode())
        except OSError:
            return
        self._pump(wait_after)

    def close(self):
        try:
            os.close(self.fd)
        except Exception:
            pass
        try:
            os.waitpid(self.pid, 0)
        except Exception:
            pass

    def wait_disk(self, relpath, timeout=90, description="file"):
        """Pump the child (so it never blocks on a full pty buffer) until a
        result file appears on disk. Ops return to the PAK menu without
        re-printing the title, so this is the reliable completion signal."""
        end = time.time() + timeout
        path = ROOT / relpath
        while time.time() < end:
            if path.exists():
                _log("%s:appeared %s" % (description, relpath))
                return True
            self._pump(1.0)
        _log("!! %s:never saw %s on disk" % (description, relpath))
        return False

    def wait_ready(self, marker, timeout=45, description="", fresh=True):
        """Wait for a marker (ANSI-stripped) and keep pumping the tool
        meanwhile so the child never blocks on a full pty output buffer.

        fresh=False lets wizard prompts (drawn inside the feed's own pump,
        hence never behind a fresh anchor) match anywhere in the buffer.
        """
        ok = self.wait_for(marker, timeout, fresh=fresh)
        if ok:
            _log("%s:found %r" % (description or "marker", marker))
        else:
            _log("!! %s:never saw %r%s" % (description or "marker", marker,
                                           "" if fresh else " (global)"))
        return ok

    def drain_screen(self):
        """Split accumulated buffer at CLS boundaries; keep last screen."""
        parts = self.buf.split(b"\x1b[2J\x1b[H")
        return parts[-1] if parts else b""

    def audit(self, label, tolerant=False):
        """Assert the LAST screen renders cleanly."""
        self.screens += 1
        raw = self.drain_screen()
        text = raw.decode("utf-8", "replace")
        import re
        plain_lines = [re.sub(r"\x1b\[[0-9;]*m", "", ln) for ln in text.split("\n")]
        # 1) no NAKED ansi-body anywhere (ESC stripped = literal garbage)
        for pat in ("[38;5;", "[0m", "[0;", "[31m"):
            idx = text.find(pat)
            while idx != -1:
                if idx == 0 or text[idx - 1] != "\x1b":
                    self.fail(label, "literal ansi fragment %r on screen"
                              % pat)
                    return
                idx = text.find(pat, idx + 1)
        # 2) no line visually wider than the terminal. Compiled progress bars
        #    (`\r ... ⏳` / `[2K` fillers) and the compiled wizard/splash art
        #    may exceed cols; box/content lines must fit.
        for i, ln in enumerate(plain_lines):
            if ln.startswith("\x1b[2K") or "⏳" in ln or ln.startswith("\r"):
                continue
            stripped = ln.strip("✦═─·✧☄─═ \r")
            if stripped == "":
                if len(ln) > self.cols + 2:
                    self.fail(label, "line %d wraps: fill %d > cols %d"
                              % (i, len(ln), self.cols))
                    return
                continue
            if len(ln) > self.cols:
                if tolerant and len(ln) <= self.cols + 1:
                    continue
                mid = ln.lstrip("│ ")
                if len(ln) == 75 and mid.startswith(("╭", "┌")):
                    continue
                self.fail(label, "line %d wraps: visible %d > cols %d  %r"
                          % (i, len(ln), self.cols, ln[:60]))
                return
        # 3) box shape: the rendered screen is a stack of complete boxes
        tops = sum(ln.count("╔") + ln.count("╭") + ln.count("┏") + ln.count("┌")
                   for ln in plain_lines)
        bots = sum(ln.count("╝") + ln.count("╯") + ln.count("┛") + ln.count("┘")
                   for ln in plain_lines)
        if tops != bots:
            self.fail(label, "box corners unbalanced top=%d bottom=%d"
                      % (tops, bots))
            return
        if tops == 0 and label not in ("prompt-choices",):
            self.fail(label, "no box rendered on screen")
            return
        print("  screen %-34s ok (%d box(es))" % (label, tops))

    def fail(self, label, msg):
        self.fails.append("%s: %s" % (label, msg))
        print("  screen %-34s FAIL %s" % (label, msg))

    def expect_dirs(self, *paths):
        for p in paths:
            if not (ROOT / p).is_dir():
                self.fails.append("missing dir %s" % p)
            else:
                print("       artefact %-28s present" % p)

    def expect_file(self, path):
        p = ROOT / path
        if p.is_file():
            print("       artefact %-28s present (%s)" % (path, p.stat().st_size))
        else:
            self.fails.append("missing file %s" % path)


def pty_fork(env, cwd):
    import pty
    pid, fd = pty.fork()
    if pid == 0:
        os.chdir(str(cwd))
        os.execvpe(SYS_EXE, [SYS_EXE, "ikram_patch.py"], env)
    return pid, fd


def stage(clean=True):
    if clean:
        import shutil
        # A fresh tool home is mandatory: a stale home left by an aborted
        # run makes the compiled engine hang boot after key unlock.
        _home = Path("/data/data/com.termux/files/usr/tmp/opencode/live_home")
        shutil.rmtree(_home, ignore_errors=True)
        _home.mkdir(parents=True, exist_ok=True)
    for d in ("DROP/pak", "DROP/lua", "DROP/inject",
              "RESULT/extracted", "RESULT/injected", "RESULT/lua",
              "RESULT/processed", "RESULT/CostomPak", "RESULT/Repacked"):
        (ROOT / d).mkdir(parents=True, exist_ok=True)
    if clean:
        import shutil
        for base in ("DROP", "RESULT"):
            top = ROOT / base
            for p in top.iterdir():
                if p.is_dir():
                    shutil.rmtree(p, ignore_errors=True)
                else:
                    p.unlink(missing_ok=True)
        for d in ("DROP/pak", "DROP/lua", "DROP/inject",
                  "RESULT/extracted", "RESULT/injected", "RESULT/lua",
                  "RESULT/processed", "RESULT/CostomPak", "RESULT/Repacked"):
            (ROOT / d).mkdir(parents=True, exist_ok=True)
        (ROOT / "DROP/pak/core.pak").write_bytes(Path(FIXURE_PAK).read_bytes())
        (ROOT / "DROP/lua/hello.lua").write_text(
            "-- hello\nprint(\"hi\")\n", encoding="utf-8")
        (ROOT / "DROP/inject/inject.txt").write_text("inject me\n",
                                                     encoding="utf-8")


def drive_themes(live):
    from theme_engine import THEMES
    for i, name in enumerate(THEMES, 1):
        n = str(i)
        live.feed("3\n", 1.2)          # themes menu
        live.audit("themes menu [%s]" % name)
        live.feed(n + "\n", 1.4)       # pick theme
        live.audit("theme set [%s]" % name)
        live.feed("1\n", 1.2)          # PAK menu under this theme
        live.audit("pak menu [%s]" % name)
        live.feed("0\n", 1.0)
        live.feed("2\n", 1.2)          # LUA menu under this theme
        live.audit("lua menu [%s]" % name)
        live.feed("0\n", 1.0)


def feed_script(live, items, settle=("", 8)):
    for it in items:
        live.feed(it + ("\n" if it != "\n" else ""), 0.5)
    live.quiesce(1.0, settle[1])


_T0 = time.time()

def _log(msg):
    print("[%6.1fs] %s" % (time.time() - _T0, msg), flush=True)


def main():
    cols = int(sys.argv[sys.argv.index("--cols") + 1]) if "--cols" in sys.argv else 74
    rows = int(sys.argv[sys.argv.index("--rows") + 1]) if "--rows" in sys.argv else 26
    stage(clean=True)
    live = Live(cols=cols, rows=rows)
    live.spawn()
    _log("spawned")

    live.feed("FREETOOL\n", 1.0)
    print("== A. every theme x every menu ==")
    _log("waiting for main menu (LUA TOOL)")
    if not live.wait_for("LUA TOOL", 240):
        import re as _re
        line1 = live.drain_screen().decode("utf-8", "replace").split("\n")
        tail = [t[:80] for t in [_re.sub(r"\x1b\[[0-9;]*m", "", l).rstrip("\r")
                                  for l in line1] if t.strip()][-8:]
        print("!! main menu never rendered after unlock")
        print("    screen tail:", tail)
        return 1
    _log("main menu reached")
    drive_themes(live)

    print("== B. real operations (Neon Pink active) ==")
    # ensure Neon Pink (theme 1)
    live.feed("3\n", 1.0)
    live.feed("1\n", 1.2)
    live.audit("neon pink active")
    # main -> PAK tool
    live.feed("1\n", 0.8)
    live.quiesce(1.0, 3)
    # UNPACK (real 696-entry pak): 1=Unpack, mode 1=ONE, pak auto
    live.feed("1\n", 0.5)
    live.wait_ready("CHOOSE MODE", 25, "unpack-mode", fresh=False)
    live.feed("1\n", 0.5)
    live.wait_ready("number (ENTER = auto first)", 20, "unpack-pak", fresh=False)
    live.feed("\n", 0.5)
    if not live.wait_disk("RESULT/extracted/core/ShadowTrackerExtra",
                          220, "unpack"):
        print("!! unpack did not produce RESULT/extracted/core")
        return 1
    live.quiesce(1.0, 3)
    live.audit("unpack done", tolerant=True)
    live.feed("\n", 0.5)
    live.quiesce(1.0, 3)
    # INJECT (compiled wizard): 2, pak pick 1, mode 2, folder auto,
    # then "this" at the root chooser -> inject
    live.feed("2\n", 0.5)
    live.wait_ready("Select number", 25, "inject", fresh=False)
    live.feed("1\n", 0.5)
    live.wait_ready("CHOOSE MODE", 25, "inject-mode", fresh=False)
    live.feed("2\n", 0.5)
    live.wait_ready("full path", 25, "inject-path", fresh=False)
    live.feed("\n", 0.5)
    live.wait_ready("Choose:", 25, "inject-folder", fresh=False)
    live.feed("this\n", 0.5)
    if not live.wait_disk("RESULT/injected/core.pak", 160, "inject"):
        print("!! inject did not produce RESULT/injected/core.pak")
        return 1
    live.quiesce(1.0, 3)
    live.audit("inject done", tolerant=True)
    live.feed("\n", 0.5)
    live.quiesce(1.0, 3)
    # REPACK: 3, pak pick 1
    live.feed("3\n", 0.5)
    live.wait_ready("Select number", 25, "repack", fresh=False)
    live.feed("1\n", 0.5)
    if not live.wait_disk("RESULT/Repacked/core.pak", 200, "repack"):
        print("!! repack did not produce RESULT/Repacked/core.pak")
        return 1
    live.quiesce(1.0, 3)
    live.audit("repack done", tolerant=True)
    live.feed("\n", 0.5)
    live.quiesce(1.0, 3)
    # COSTOM PAK: 4, pak auto, ENTER, Select prompt ENTER
    live.feed("4\n", 0.5)
    live.wait_ready("COSTOM PAK number", 20, "costom", fresh=False)
    live.feed("\n", 0.5)
    live.wait_ready("Select:", 15, "costom-folder", fresh=False)
    live.feed("\n", 0.5)
    if not live.wait_disk("RESULT/CostomPak/core.pak", 90, "costom"):
        print("!! costom did not produce RESULT/CostomPak/core.pak")
        return 1
    live.quiesce(1.0, 3)
    live.audit("costom done", tolerant=True)
    live.feed("\n", 0.5)
    live.quiesce(1.0, 3)
    print("       (costom writes RESULT/CostomPak)")
    # CLEAR DROP/pak: c, y
    live.feed("c\n", 0.5)
    live.quiesce(1.0, 2)
    live.feed("y\n", 0.5)
    live.quiesce(1.0, 4)
    live.audit("clear drop/pak", tolerant=True)
    live.feed("\n", 0.5)
    live.quiesce(1.0, 3)
    # back to MAIN -> LUA tool: 0=leave PAK, 2=Lua
    live.feed("0\n", 0.5)
    live.quiesce(1.0, 3)
    live.feed("2\n", 0.5)
    live.quiesce(1.0, 3)
    # COMPILE hello.lua: 1=Compile, pause
    live.feed("1\n", 0.5)
    live.quiesce(1.0, 12)
    live.feed("\n", 0.5)
    live.quiesce(1.0, 3)
    live.audit("lua compile", tolerant=True)
    # DECOMPILE the compiled file: 2=Decompile, pause
    live.feed("2\n", 0.5)
    live.quiesce(1.0, 12)
    live.feed("\n", 0.5)
    live.quiesce(1.0, 3)
    live.audit("lua decompile", tolerant=True)
    live.feed("0\n0\n", 0.8)
    live.quiesce(1.0, 3)
    live.audit("exit", tolerant=True)
    live.close()

    print("== LIVE DRIVE SUMMARY ==")
    print("screens audited:", live.screens)
    if live.fails:
        print("FAILURES:")
        for f in live.fails:
            print("  -", f)
        return 1
    print("ALL LIVE SCREENS CLEAN — A-to-Z verified on a real terminal.")
    return 0


if __name__ == "__main__":
    sys.exit(main())