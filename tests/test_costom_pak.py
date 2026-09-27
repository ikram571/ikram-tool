"""E2E: the PAK 'Costom PAK' option, driven through menus.pak_custom with a
scripted Vip and a REAL ue4 pak built by repak.

Covers the three selection modes the menu text promises:
  ENTER  -> every path in the template pak, all bodies 0 bytes
  number -> exactly that one path
  typed  -> only paths matching what was typed
plus: N at Proceed? cancels, missing PAK errors cleanly, and the tencent
branch is reported as unsupported rather than crashing.
"""
import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path("/data/data/com.termux/files/home/opencode/ikram_work/ikram-tool")
sys.path.insert(0, str(ROOT))
SB = Path("/data/data/com.termux/files/usr/tmp/opencode/paksb")
KEY = "8A75AFDF1C74AB55B79DC1DD4ABE4B01360A059D77F243EF4EFADA41A59D71A0"
REPAK = str(ROOT / "repak")

import paths as P
import menus
import engines

PASS = FAIL = 0


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok   %s" % name)
    else:
        FAIL += 1
        print("  FAIL %s   %s" % (name, extra))


class FakeVip:
    """Minimal Vip stand-in: records output, feeds scripted answers."""

    def __init__(self, answers):
        self.answers = list(answers)
        self.out = []
        self.theme = self._T()
        self.box = self._Box()
        self.frames = 0

    def _paint_frame(self, text):
        self.frames += 1

    class _Box:
        def draw_progress(self, **kw):
            return "  [progress %s%%] %s" % (kw.get("pct", "?"), kw.get("cur", ""))

        def draw_box(self, lines, *a, **kw):
            return "\n".join(str(x) for x in lines)

        def draw_labeled_row(self, k, v, *a, **kw):
            return "  %s: %s" % (k, v)

    def write(self, s=""):
        self.out.append(str(s))

    def _ask(self, prompt=""):
        return self.answers.pop(0) if self.answers else ""

    def _eof_answered(self, default=""):
        # running out of scripted answers is EOF, but a scripted "" is a real
        # ENTER the user pressed. The real Vip tells those apart by looking at
        # readline(), not the string, so mirror that instead of guessing on
        # the value.
        if not self.answers:
            return default, True
        return self.answers.pop(0), False

    wait_enter = _ask

    def proceed_box(self, operation, src, files, out, extra=None):
        self.out.append(str(operation))
        if extra:
            self.out.extend("  " + str(e) for e in extra)
        return self._ask("Proceed? ").strip().lower() == "y"

    def confirm_box(self, title, label, yes_label="Delete"):
        self.out.append(str(title) + " " + str(label))
        return self._ask("Confirm? ").strip().lower() == "y"

    def error_box(self, lines, next_step=None):
        self.out.extend(str(x) for x in lines)
        if next_step:
            self.out.append("Next : " + str(next_step))

    def success_box(self, lines):
        self.out.extend(str(x) for x in lines)

    warn_box = success_box

    class _T:
        def apply(self, s, role=None):
            return s

    def __getattr__(self, name):
        def _noop(*a, **k):
            self.out.append(" ".join(str(x) for x in a))
        return _noop

    def text(self):
        return "".join(self.out)

    def error(self):
        return "✗" in self.text()

    def success(self):
        return "✓" in self.text()


def load_ue4():
    spec = importlib.util.spec_from_file_location("ue4_probe", ROOT / "ue4.pyc")
    m = importlib.util.module_from_spec(spec)
    sys.modules["ue4_probe"] = m
    spec.loader.exec_module(m)
    return m


def build_template():
    shutil.rmtree(SB, ignore_errors=True)
    tree = SB / "tree" / "ShadowTrackerExtra"
    (tree / "Config").mkdir(parents=True, exist_ok=True)
    (tree / "Content" / "Lua").mkdir(parents=True, exist_ok=True)
    (tree / "Config" / "GameUserSettings.ini").write_bytes(b"res=1080p\n")
    (tree / "Content" / "Lua" / "data.lua").write_bytes(b"a,b,c=1,2,3\n")
    (tree / "Content" / "Lua" / "gameplay.lua").write_bytes(b"return 42\n")
    pak = SB / "base.pak"
    r = subprocess.run([REPAK, "pack", str(SB / "tree"), "--mount-point", "../../../",
                        "--version", "V8B", "--compression", "Zlib", str(pak)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit("repak pack failed: %s %s" % (r.stdout, r.stderr))
    return pak, sorted(engines.list_pak_paths(pak))


def body_sizes(pak, u):
    d = SB / "verify"
    shutil.rmtree(d, ignore_errors=True)
    u.Ue4Pak(pak, aes_key=KEY).extract_all(d)
    return {str(f.relative_to(d)): f.stat().st_size
            for f in sorted(d.rglob("*")) if f.is_file()}


def main():
    u = load_ue4()
    pak, allp = build_template()
    print("template pak: %d paths" % len(allp))

    outdir = P.RESULT_CUSTOMPAK
    dropdir = P.DROP_PAK
    shutil.rmtree(outdir, ignore_errors=True)
    dropdir.mkdir(parents=True, exist_ok=True)
    dst = dropdir / pak.name
    shutil.copy2(pak, dst)

    # ---- 1. no pak at all -> clean error, no crash
    saved = list(dropdir.iterdir())
    for f in saved:
        f.unlink()
    v = FakeVip([""])
    menus.pak_custom(v)
    check("no-pak: clean error box", v.error() and "No PAK found" in v.text())
    check("no-pak: no exception leaked", True)

    shutil.copy2(pak, dst)

    # ---- 2. Proceed? = N -> cancelled, nothing written
    v = FakeVip(["n"])
    menus.pak_custom(v)
    made = list(outdir.glob("*.pak")) if outdir.exists() else []
    check("Proceed=N: cancelled", "Cancelled" in v.text())
    check("Proceed=N: wrote no pak", not made, str(made))

    # ---- 3. ENTER -> all paths, all 0 bytes
    v = FakeVip(["y", ""])
    menus.pak_custom(v)
    made = sorted(outdir.glob("*.pak"))
    check("ENTER: produced one pak", len(made) == 1, str(made))
    if made:
        got = sorted(engines.list_pak_paths(made[0]))
        check("ENTER: all paths declared", got == allp, "%s" % got)
        b = body_sizes(made[0], u)
        check("ENTER: every body 0 bytes", b and all(v_ == 0 for v_ in b.values()), str(b))
        check("ENTER: success box", v.success())

    # ---- 4. a number picks a FOLDER, and every file under it comes along.
    #         The menu says "number = pick 1 folder", so the number indexes
    #         engines.pack_folders(), not the raw path list.
    folders = engines.pack_folders(allp)
    n2 = min(2, len(folders))
    want2 = [p for p in allp if p == folders[n2 - 1]
             or p.startswith(folders[n2 - 1] + "/")]
    v = FakeVip(["y", str(n2)])
    menus.pak_custom(v)
    made = sorted(outdir.glob("*.pak"), key=lambda p: p.stat().st_mtime)
    if made:
        got = sorted(engines.list_pak_paths(made[-1]))
        check("number %d: that folder's paths" % n2, got == sorted(want2),
              "folder=%s want=%s got=%s" % (folders[n2 - 1], sorted(want2), got))
        b = body_sizes(made[-1], u)
        check("number %d: bodies 0 bytes" % n2,
              bool(b) and all(x == 0 for x in b.values()), str(b))
    else:
        check("number %d: produced a pak" % n2, False)

    # ---- 5. number out of range -> clean error
    v = FakeVip(["y", "99"])
    menus.pak_custom(v)
    check("number 99: clean error", "No such number" in v.text(), v.text()[-200:])

    # ---- 6. typed path -> only that path, and its bytes are COPIED, not
    #         emptied. This is the one branch the menu describes as copied.
    typed = "gameplay.lua"
    v = FakeVip(["y", typed])
    menus.pak_custom(v)
    made = sorted(outdir.glob("*.pak"), key=lambda p: p.stat().st_mtime)
    if made:
        got = sorted(engines.list_pak_paths(made[-1]))
        check("typed: matched exactly one",
              got == ["ShadowTrackerExtra/Content/Lua/gameplay.lua"], str(got))
        b = body_sizes(made[-1], u)
        check("typed: body is COPIED, not empty",
              bool(b) and all(x > 0 for x in b.values()), str(b))
        check("typed: success box says copied", "COPIED" in v.text(),
              v.text()[-200:])
    else:
        check("typed: produced a pak", False)

    # ---- 7. typed path not in pak -> clean error
    v = FakeVip(["y", "does/not/exist.lua"])
    menus.pak_custom(v)
    check("typed miss: clean error", "not in this PAK" in v.text(), v.text()[-200:])

    # ---- 8. every produced pak is readable by repak too (engine interop)
    bad = []
    for q in sorted(outdir.glob("*.pak")):
        r = subprocess.run([REPAK, "-a", KEY, "unpack", str(q),
                            "--output", str(SB / "interop"), "-f"],
                           capture_output=True, text=True)
        if r.returncode != 0:
            bad.append(q.name)
    check("repak can read every costom pak", not bad, str(bad))

    # ---- 9. corrupt / non-pak input is reported, not a crash
    for f in list(dropdir.iterdir()):
        f.unlink()
    (dropdir / "junk.pak").write_bytes(b"not a pak at all")
    v = FakeVip([""])
    menus.pak_custom(v)
    check("junk pak: clean error", "Cannot read this PAK" in v.text(), v.text()[-200:])
    (dropdir / "junk.pak").unlink()

    # ---- 10. closed stdin must unwind, not spin on the same prompt forever.
    #          This handler grew a whole extra ask() call, so an EOF in the
    #          middle of it used to re-prompt until the answer list was empty
    #          and then loop again, forever. The answers run out only on the
    #          path prompt, which is the call that had to learn about EOF;
    #          feeding a scripted "" instead would just be a real ENTER, and
    #          an ENTER with no text legitimately means "all paths".
    src = sorted(outdir.glob("*.pak"))
    if src:
        (dropdir / "eof.pak").write_bytes(src[0].read_bytes())
        before = {q.name: q.read_bytes() for q in outdir.glob("*.pak")}
        v = FakeVip(["1", "y"])    # pick the pak, say yes, then stdin is closed
        try:
            menus.pak_custom(v)
            unwound = True
        except Exception as e:
            unwound = False
            v.write("RAISED %s: %s" % (type(e).__name__, e))
        check("closed stdin unwinds instead of looping", unwound, v.text()[-200:])
        check("closed stdin cancels instead of building",
              "Cancelled" in v.text(), v.text()[-200:])
        check("closed stdin builds nothing",
              {q.name: q.read_bytes() for q in outdir.glob("*.pak")} == before,
              "a pak appeared from an EOF run")
        (dropdir / "eof.pak").unlink()

    print("\n%d passed, %d failed" % (PASS, FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
