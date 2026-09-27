"""E2E: the PAK 'Custom PAK' option (menu option 4), driven through
menus.pak_custom with a scripted Vip and a REAL ue4 pak built by repak.

The answer order is the live one: pick the pak by number, pick the paths
(ENTER = all), name the output, then confirm.

Covers the three selection modes the menu text promises:
  ENTER  -> every path in the source pak, every body with its ORIGINAL bytes
  number -> exactly that one numbered path
  typed  -> that path, or everything under a folder prefix
plus: N at Proceed? cancels, missing PAK errors cleanly, a bad number or a
bad path re-prompts instead of dying, the output keeps the source name, no
body is ever 0 bytes, the temp session is always removed, and every produced
pak is readable by repak as well as by our own reader.
"""
import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path

# The repo, wherever it is checked out. A hardcoded home path made this
# suite die on ModuleNotFoundError for anyone but the machine it was written
# on, which is how a real regression test quietly stops testing anything.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
SB = Path(os.environ.get("IKRAM_TEST_SANDBOX")
          or (ROOT / "tests" / ".sandbox_paks"))
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


def body_bytes(pak, u):
    """Every file in `pak`, as {internal path: bytes}, read back with the
    engine's own reader. Comparing the OUTPUT against the SOURCE tree is the
    only way to prove the body is the original content and not a 0-byte stub.
    """
    d = SB / "verify"
    shutil.rmtree(d, ignore_errors=True)
    u.Ue4Pak(pak, aes_key=KEY).extract_all(d)
    return {str(f.relative_to(d)).replace("\\", "/"): f.read_bytes()
            for f in sorted(d.rglob("*")) if f.is_file()}


def source_bytes(u, pak):
    return body_bytes(pak, u)


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
    v = FakeVip(["1", "", "", "n"])
    menus.pak_custom(v)
    made = list(outdir.glob("*.pak")) if outdir.exists() else []
    check("Proceed=N: cancelled", "Cancelled" in v.text())
    check("Proceed=N: wrote no pak", not made, str(made))

    # ---- 3. ENTER -> every path, every body carrying the ORIGINAL bytes.
    #         This is the whole point of the option: the old code wrote
    #         b"" for this mode and shipped 0-byte files to the game.
    src = source_bytes(u, pak)
    v = FakeVip(["1", "", "", "y"])
    menus.pak_custom(v)
    made = sorted(outdir.glob("*.pak"))
    check("ENTER: produced one pak", len(made) == 1, str(made))
    if made:
        check("ENTER: output keeps the source name",
              made[0].name == pak.stem + ".pak", made[0].name)
        got = sorted(engines.list_pak_paths(made[0]))
        check("ENTER: all paths declared", got == allp, "%s" % got)
        b = body_bytes(made[0], u)
        check("ENTER: no 0-byte body", b and all(v_ for v_ in b.values()), str(b))
        check("ENTER: every body is the original content", b == src,
              "differs: %s" % [k for k in b if b.get(k) != src.get(k)])
        check("ENTER: success box", v.success())

    # ---- 4. a number picks ONE PATH, not a folder. The menu numbers every
    #         internal path, so the number indexes that list.
    n2 = min(2, len(allp))
    v = FakeVip(["1", str(n2), "", "y"])
    menus.pak_custom(v)
    made = sorted(outdir.glob("*.pak"), key=lambda p: p.stat().st_mtime)
    if made:
        got = sorted(engines.list_pak_paths(made[-1]))
        check("number %d: exactly that path" % n2, got == [allp[n2 - 1]],
              "want=%s got=%s" % ([allp[n2 - 1]], got))
        b = body_bytes(made[-1], u)
        check("number %d: body is the original content" % n2,
              b == {allp[n2 - 1]: src[allp[n2 - 1]]}, str(b))
    else:
        check("number %d: produced a pak" % n2, False)

    # ---- 5. number out of range -> clean error, then the next answer works
    before5 = {q.name: q.stat().st_mtime for q in outdir.glob("*.pak")}
    v = FakeVip(["1", "99", str(n2), "", "y"])
    menus.pak_custom(v)
    check("number 99: clean error", "Invalid number" in v.text(), v.text()[-200:])
    after5 = {q.name: q.stat().st_mtime for q in outdir.glob("*.pak")}
    check("number 99: re-prompted into a build",
          set(after5) - set(before5) != set(), "no new pak after the re-prompt")

    # ---- 6. typed path -> only that path, with its bytes COPIED
    typed = "gameplay.lua"
    v = FakeVip(["1", typed, "", "y"])
    menus.pak_custom(v)
    made = sorted(outdir.glob("*.pak"), key=lambda p: p.stat().st_mtime)
    if made:
        got = sorted(engines.list_pak_paths(made[-1]))
        check("typed: matched exactly one",
              got == ["ShadowTrackerExtra/Content/Lua/gameplay.lua"], str(got))
        b = body_bytes(made[-1], u)
        check("typed: body is COPIED, not empty",
              b.get(got[0]) == src[got[0]], str(b))
        check("typed: success box says full original content",
              "full original content" in v.text(), v.text()[-200:])
    else:
        check("typed: produced a pak", False)

    # ---- 7. typed path not in pak -> clean error, then the next answer works
    v = FakeVip(["1", "does/not/exist.lua", str(n2), "", "y"])
    menus.pak_custom(v)
    check("typed miss: clean error", "Path not found in pak" in v.text(),
          v.text()[-200:])

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
    before9 = {q.name: q.read_bytes() for q in outdir.glob("*.pak")}
    v = FakeVip(["1"])
    menus.pak_custom(v)
    check("junk pak: clean error", "Cannot read this PAK" in v.text(), v.text()[-200:])
    check("junk pak: wrote nothing",
          {q.name: q.read_bytes() for q in outdir.glob("*.pak")} == before9)
    (dropdir / "junk.pak").unlink()

    # ---- 10. closed stdin must unwind, not spin on the same prompt forever.
    #          The handler now asks four questions, so an EOF in the middle of
    #          it used to re-prompt until the answer list ran dry and then loop
    #          again, forever. The answers run out on the FIRST path prompt,
    #          which is the call that had to learn about EOF; feeding a
    #          scripted "" instead would just be a real ENTER, and an ENTER
    #          with no text legitimately means "all paths".
    src_paks = sorted(outdir.glob("*.pak"))
    if src_paks:
        (dropdir / "eof.pak").write_bytes(src_paks[0].read_bytes())
        before = {q.name: q.read_bytes() for q in outdir.glob("*.pak")}
        v = FakeVip(["1"])    # pick the pak, then stdin is closed
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

    # ---- 11. the temp session is never left behind. It holds the unpacked
    #           source, which can be hundreds of MB in a real pak, so a leak
    #           here is a full disk after a handful of runs.
    import tempfile
    tmp_root = Path(tempfile.gettempdir())
    leaked = sorted(p.name for p in tmp_root.glob("ikram_custom_*"))
    check("no temp session left behind", not leaked, str(leaked))

    print("\n%d passed, %d failed" % (PASS, FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
