"""The update gate: it must run BEFORE the key screen, compare versions as
integers, and apply the install transactionally.

The compiled core in ikram.pyc always did all of this in main() -- check,
install, re-exec, then the key screen -- but the live launcher never called
main(). It went straight to vip_ui.Vip.run(), which opened the key screen and
nothing else. The code was right and the reachable path was wrong, so an old
install stayed on its old version forever.

Nothing here touches the network. do_install() downloads a release, so it is
driven with a stub and the filesystem transaction is tested through
_clean_replace, which is where the data-loss bug lived.
"""
import inspect
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO))

import update as u  # noqa: E402

WORK = REPO / ".update_gate_test"
PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print("  %s  %s%s" % ("PASS" if cond else "FAIL", name,
                          "" if cond else "   " + str(extra)[:150]))


def fake_vip(rec):
    """Enough Vip for the gate; records the order of the calls."""
    class T:
        def apply(self, s, role=None):
            return s

    class B:
        def draw_box(self, lines, *a, **k):
            return "\n".join(str(x) for x in lines)

        def draw_labeled_row(self, label, value, *a, **k):
            return "  %s : %s" % (label, value)

    class V:
        theme = T()
        box = B()

        def __getattr__(self, name):
            def _noop(*a, **k):
                rec.append(("noop:" + name, None))
            return _noop

        def write(self, s=""):
            rec.append(("write", str(s)[:70]))

        def pause(self, *a, **k):
            rec.append(("pause", None))

    return V()


def test_version_compare():
    print("\n[1] version comparison is integer-based, not string-based")
    # "V100" > "V119" as text, but 100 < 119 as numbers.
    check("V100 is OLDER than V119", u.version_tuple("V100") < u.version_tuple("V119"))
    check("V9 is older than V10", u.version_tuple("V9") < u.version_tuple("V10"))
    check("equal versions are not newer",
          not u.version_tuple("V120") > u.version_tuple("v120"))
    check("a leading v and a newline both parse",
          u.version_tuple("v122\n") == u.version_tuple("V122") == [122])
    # An empty or corrupt VERSION must not block an update: it reads as 0,
    # older than every real release, so the tool offers to update.
    for junk, why in (("", "empty"), ("abc", "no digits"), ("V", "bare v"),
                      ("V12x3", "mixed")):
        check("%s version reads as 0, not an error" % why,
              u.version_tuple(junk) == [0], u.version_tuple(junk))
    check("a corrupt local version never outranks a real release",
          u.version_tuple("abc") < u.version_tuple("V119"))


def test_gate():
    print("\n[2] the update gate runs, and returns before the key screen")
    import os

    import vip_ui
    saved = (u.latest_remote, u.do_install, vip_ui._read_version, os.execv)

    def remote(tag):
        return {"version": tag, "url": "https://example.invalid/IkramTool.zip"}

    def run(rec, tag, local, ok):
        u.latest_remote = lambda: remote(tag)
        u.do_install = lambda *a, **k: rec.append(("install", tag)) or ok
        vip_ui._read_version = lambda *a, **k: local
        # The gate finishes by re-execing the interpreter. Let it: this
        # process IS the tool as far as the gate is concerned, and replacing
        # it would take the test runner with it. Record the call instead.
        os.execv = lambda exe, argv, *a, **k: rec.append(("execv", argv))
        v = fake_vip(rec)
        try:
            vip_ui.Vip._update_gate(v)
            return True
        except SystemExit as e:
            rec.append(("sysexit", e.code))
            return False
        finally:
            os.execv = saved[3]

    try:
        rec = []
        fell_through = run(rec, "V123", "V122", True)
        check("a newer version triggers do_install", ("install", "V123") in rec, rec)
        check("the gate re-execs into the new build",
              any(k == "execv" for k, _ in rec), rec)
        check("it does not fall through to the key screen",
              fell_through and rec[-1][0] == "execv", rec[-3:])

        rec = []
        survived = run(rec, "V123", "V122", False)
        check("a failed install does not restart into a broken tool", survived)
        check("a failed install says so and continues",
              any(k == "write" and "could not be applied" in str(v)
                  for k, v in rec), rec)

        rec = []
        run(rec, "V122", "V122", True)
        check("same version installs nothing",
              not any(k == "install" for k, _ in rec), rec)

        rec = []
        run(rec, "V100", "V122", True)
        check("an older remote version is not installed",
              not any(k == "install" for k, _ in rec), rec)

        rec = []
        run(rec, "V123", "", True)
        check("a corrupt local VERSION still lets the update through",
              ("install", "V123") in rec, rec)

        for label, boom in (("no network", OSError("no route to host")),
                            ("no published release", None)):
            rec = []
            u.latest_remote = boom if isinstance(boom, Exception) else (lambda: None)
            if isinstance(boom, Exception):
                def raiser():
                    raise boom
                u.latest_remote = raiser
            os.execv = lambda exe, argv, *a, **k: rec.append(("execv", argv))
            v = fake_vip(rec)
            try:
                vip_ui.Vip._update_gate(v)
                alive = True
            except SystemExit:
                alive = False
            finally:
                os.execv = saved[3]
            check("%s is not fatal" % label, alive)
            check("%s never restarts" % label,
                  not any(k == "execv" for k, _ in rec), rec)
    finally:
        (u.latest_remote, u.do_install, vip_ui._read_version,
         os.execv) = saved


def test_order():
    print("\n[3] run() checks for an update BEFORE the key gate")
    import vip_ui
    src = inspect.getsource(vip_ui.Vip.run)
    i_up, i_key = src.find("_update_gate"), src.find("_key_gate")
    check("run() calls _update_gate", i_up != -1, src)
    check("run() calls _key_gate", i_key != -1, src)
    check("the update check comes first", 0 < i_up < i_key, src)


def test_protection():
    print("\n[4] user data is protected whatever case the folder is in")
    for n in ("DROP", "drop", "Drop", "dRoP", "RESULT", "result", "Result"):
        check("%s/ is protected" % n, u._is_protected(n))
    for n in ("ikram.pyc", "run.sh", "update.py", "aDROP", "DROPBOX",
              "RESULTING", "mydrop"):
        check("%s is NOT protected" % n, not u._is_protected(n))
    check("PROTECTED still names the real data dirs",
          "DROP" in u.PROTECTED and "RESULT" in u.PROTECTED, u.PROTECTED)
    # The version marker and the key are protected on purpose: the
    # transaction must not delete them, and do_install rewrites both right
    # after it moves the old tree aside.
    for n in ("VERSION", "ikram_key.json"):
        check("%s is protected" % n, u._is_protected(n))


def test_install_keeps_data():
    print("\n[5] the install transaction keeps user data in either case")
    saved_dir = u.TOOL_DIR
    # The installed layout spells them drop/ and result/; the release layout
    # spells them DROP/ and RESULT/. Only the second pair was in the old
    # exact-match set, so a flat old install lost its data on update.
    cases = {"lowercase": ["drop", "result"], "UPPERCASE": ["DROP", "RESULT"],
             "MiXeD": ["Drop", "Result"]}
    try:
        for label, dirs in cases.items():
            live = WORK / ("live_" + label)
            live.mkdir(parents=True)
            for name in u.REQUIRED_ENTRIES:
                (live / name).write_text("# V122 live %s\n" % name)
            (live / "VERSION").write_text("V122\n")
            (live / "ikram_key.json").write_text(
                '{\n  "version": "V122",\n  "key_hash": "7360b6c"\n}\n')
            (live / "stale_from_v118.py").write_text("stale\n")
            for d in dirs:
                (live / d / "pak").mkdir(parents=True)
                (live / d / "pak" / "mine.pak").write_text("MY PAK in " + d)
                (live / d / "out.lua").write_text("-- MINE in " + d + "\n")

            payload = WORK / ("payload_" + label)
            payload.mkdir(parents=True)
            for name in u.REQUIRED_ENTRIES:
                (payload / name).write_text("# V123 payload %s\n" % name)
            (payload / "VERSION").write_text("V123\n")
            (payload / "brand_new.py").write_text("added in V123\n")
            # The transaction refuses a payload that looks truncated, so give
            # it the file count of a real release.
            for i in range(45):
                (payload / ("mod_%02d.py" % i)).write_text("V123 module %d\n" % i)

            u.TOOL_DIR = live
            ok = u._clean_replace(payload)
            check("%s: the install succeeds" % label, ok, ok)
            check("%s: the new version's file is in place" % label,
                  (live / "brand_new.py").exists())
            check("%s: a stale file from the old build is gone" % label,
                  not (live / "stale_from_v118.py").exists())
            for d in dirs:
                check("%s: %s/pak survived" % (label, d),
                      (live / d / "pak" / "mine.pak").exists()
                      and (live / d / "pak" / "mine.pak").read_text()
                      == "MY PAK in " + d)
                check("%s: %s/ output survived" % (label, d),
                      (live / d / "out.lua").read_text() == "-- MINE in " + d + "\n")
            check("%s: no backup directory left behind" % label,
                  not (live / u.BACKUP_DIR).exists(), u.BACKUP_DIR)
    finally:
        u.TOOL_DIR = saved_dir


def main():
    shutil.rmtree(WORK, ignore_errors=True)
    WORK.mkdir(parents=True, exist_ok=True)
    try:
        test_version_compare()
        test_gate()
        test_order()
        test_protection()
        test_install_keeps_data()
    finally:
        shutil.rmtree(WORK, ignore_errors=True)
    print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
    if FAIL:
        print("failing: " + "; ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
