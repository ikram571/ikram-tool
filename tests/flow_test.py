"""IkramTool V112 — end-to-end flow tests (Section A + E).

Each scenario runs in a FRESH subprocess (`tests/_runner.py`) so the loaded
compiled core + module-global state cannot leak between flows, matching how a
real user runs the tool (one process per launch). The runner remaps DROP/RESULT
into a temp tree, scripts inputs, captures all output, and verifies original
behaviour strings + on-disk state.

Deep PAK scenarios run whenever FIX (the Tencent test pak) exists.

Run:  python3 tests/flow_test.py
Exit 0 = all green.
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

RUNNER = Path(__file__).resolve().parent / "_runner.py"

import paths as _p  # noqa: E402  (layout of the tree under test)

# install layout prints real lowercase result paths; release layout uppercase
_RES = Path(_p.RESULT_DIR).name


def _f(s):
    """Map hardcoded RESULT/ path substrings onto the layout's real casing."""
    return s.replace("RESULT/", _RES + "/")

FIX_DIR = Path(os.environ.get(
    "FIX_ROOT",
    "/data/data/com.termux/files/home/opencode/IkramTool Project/Pakfiles For Testing"))
FIX_PAK = FIX_DIR / "core_patch_4.6.0.21537.pak" if FIX_DIR.is_dir() else None


def synth_pak():
    """Build a real UE4 pak with the bundled repak.

    The upstream fixture is a Tencent pak that is not in the repo, which used
    to skip every real-PAK scenario. A genuine pak of either kind is still a
    real pak for the purposes of these flows, so generate one instead of
    leaving options 1-4 untested.
    """
    import shutil
    import subprocess
    repak = _p.ROOT / "repak"
    if not repak.is_file():
        return None
    out = Path(tempfile.mkdtemp(prefix="ikram_synthpak_"))
    tree = out / "tree" / "ShadowTrackerExtra"
    (tree / "Config").mkdir(parents=True, exist_ok=True)
    (tree / "Content").mkdir(parents=True, exist_ok=True)
    (tree / "Config" / "GameUserSettings.ini").write_bytes(b"res=1080p\n")
    (tree / "Content" / "gameplay.lua").write_bytes(b"return 42\n")
    (tree / "Content" / "data.lua").write_bytes(b"a,b=1,2\n")
    pak = out / "synth.pak"
    r = subprocess.run(
        [str(repak), "pack", str(out / "tree"), "--mount-point", "../../../",
         "--version", "V8B", "--compression", "Zlib", str(pak)],
        capture_output=True, text=True)
    if r.returncode != 0 or not pak.is_file():
        shutil.rmtree(out, ignore_errors=True)
        return None
    return pak

FAILS = []


def check(name, cond, extra=""):
    if cond:
        print("PASS  %s" % name)
    else:
        FAILS.append(name)
        print("FAIL  %s  %s" % (name, extra))


def run_case(name, plan, timeout=420):
    r = subprocess.run(
        [sys.executable, str(RUNNER), name, json.dumps(plan)],
        capture_output=True, text=True, timeout=timeout)
    for line in r.stdout.splitlines():
        if line.startswith("OK   "):
            check("%s: %s" % (name, line[5:].strip()), True)
        elif line.startswith("FAIL "):
            check("%s: %s" % (name, line[5:].strip()), False)
    if r.returncode != 0 and "SCENARIO_OK" not in r.stdout:
        check("scenario %s completes" % name, False,
              "; ".join(r.stdout.splitlines()[-6:]))
    return r


def main():
    FIX = str(FIX_PAK) if FIX_PAK and FIX_PAK.is_file() else None

    # 1 ---- V112 shell: brand, folder status, exit (asserts inside runner)
    # The version in the banner must come from the VERSION file, not a
    # hardcoded literal here: a literal like "v11" silently matched v110-v119
    # and then failed for v120, which is how drift hides.
    _ver = (_p.ROOT / "VERSION").read_text(encoding="utf-8").strip().lower()
    run_case("shell", {
        "steps": [{"script": ["0"],
                   "expect": {"brand": ["IkramTool", _ver],
                              "status": ["DROP/pak/", "(empty)"],
                              "exit": ["Thanks for using IkramTool"]}}]})

    # 2 ---- clear utils (isolated DROP)
    run_case("clear_file", {
        "fixtures": {"DROP/pak/dummy.pak": "/dev/null"},
        "gone": ["DROP/pak/dummy.pak"],
        "steps": [{"script": ["1", "c", "y", "", "0", "0"],
                   "expect": {"cleared": ["Cleared 1 file(s)"]}}]})

    # 3 ---- unpack empty (original compiled error)
    run_case("unpack_empty", {
        "steps": [{"script": ["1", "1", "", "0", "0"],
                   "expect": {"original error":
                              ["No PAK/asset files found in DROP/pak"]}}]})

    if FIX:
        pak = {"DROP/pak/core.pak": FIX}

        # 4 ---- unpack ONE: original success text + tree + sidecars
        run_case("unpack_real", {
            "fixtures": dict(pak),
            "exists": ["RESULT/extracted/core"],
            "steps": [{"script": ["1", "1", "1", "", "", "0", "0"],
                       "expect": {"unpack done":
                                  ["files unpacked",
                                   _f("RESULT/extracted/core")]}}]})

        # 5 ---- inject ONE file through the compiled wizard
        run_case("inject_real", {
            "fixtures": dict(pak),
            "inject": True,
            "steps": [{"script": ["1", "2", "1", "2", "", "", "0", "0"],
                       "expect": {"inject done":
                                  ["INJECTED", "injected"]}}]})

        # 6 ---- repack the just-extracted folder (same env, two steps)
        run_case("repack_real", {
            "fixtures": dict(pak),
            "exists": ["RESULT/Repacked/core.pak"],
            "steps": [
                {"script": ["1", "1", "1", "", "", "0", "0"]},
                {"script": ["1", "3", "1", "", "0", "0"],
                 "expect": {"repack done":
                            ["files repacked",
                             _f("RESULT/Repacked/core.pak")]}}]})

        # 7 ---- costom pak against a real template, if one is present.
        #         The output name carries a timestamp, so match it by glob and
        #         the confirmation text is the new one, not the old wording.
        run_case("costom_real", {
            "fixtures": dict(pak),
            "exists": ["RESULT/CostomPak/costom_*.pak"],
            "steps": [{"script": ["1", "4", "y", "", "0", "0"],
                       "expect": {"costom done": ["Costom PAK created"]}}]})

    # 7b ---- same four PAK options against a GENERATED ue4 pak, so they are
    #          covered even when the upstream Tencent fixture is absent.
    SYNTH = synth_pak()
    if SYNTH:
        spak = {"DROP/pak/synth.pak": str(SYNTH)}
        run_case("synth_unpack", {
            "fixtures": dict(spak),
            "exists": [_f("RESULT/processed")],
            "steps": [{"script": ["1", "1", "1", "", "", "0", "0"],
                       "expect": {"unpack done": ["files unpacked"]}}]})

        run_case("synth_inject", {
            "fixtures": dict(spak),
            "inject": True,
            "exists": [_f("RESULT/injected")],
            "steps": [{"script": ["1", "2", "1", "", "2", "", "0", "0"],
                       "expect": {"inject done": ["INJECTED", "injected"]}}]})

        # repack needs a folder that was unpacked first
        run_case("synth_repack", {
            "fixtures": dict(spak),
            "exists": [_f("RESULT/Repacked")],
            "steps": [
                {"script": ["1", "1", "1", "", "", "0", "0"]},
                {"script": ["1", "3", "1", "", "0", "0"],
                 "expect": {"repack done": ["files repacked"]}}]})

        # option 4: costom pak. Y=proceed, ENTER=every path (all empty bodies)
        run_case("synth_costom", {
            "fixtures": dict(spak),
            "steps": [{"script": ["1", "4", "y", "", "0", "0"],
                       "expect": {"costom built": ["Costom PAK created"]}}]})

        # option 4 again, but one FOLDER only (the menu numbers folders)
        run_case("synth_costom_one", {
            "fixtures": dict(spak),
            "steps": [{"script": ["1", "4", "y", "3", "0", "0"],
                       "expect": {"costom one": ["2 path(s)"]}}]})

        # option 4 with a typed path: that branch COPIES the real bytes
        run_case("synth_costom_copy", {
            "fixtures": dict(spak),
            "steps": [{"script": ["1", "4", "y", "data.lua", "0", "0"],
                       "expect": {"costom copy": ["COPIED from the original"]}}]})

        # option 4 with nothing to read: clean error, no crash
        run_case("synth_costom_nopak", {
            "steps": [{"script": ["1", "4", "", "0", "0"],
                       "expect": {"costom no pak": ["No PAK found"]}}]})
    else:
        print("SKIP  synth_* (could not build a pak with repak)")

    # 8 ---- lua compile + decompile python round-trip, same env
    import base64 as _b64
    code = _b64.b64encode(
        b"def add(a, b):\n"
        b"    if a > b:\n"
        b"        return a\n"
        b"    return b\n"
        b"print(add(1, 3))\n").decode()
    run_case("lua_roundtrip", {
        "fixtures": {"DROP/lua/helper.py": {"b64_text": code}},
        "exists": ["RESULT/lua/helper.pyc"],
        "steps": [
            {"script": ["2", "1", "", "0", "0"],
             "expect": {"compile py": ["Compiled"]}},
            {"script": ["2", "2", "", "0", "0"],
             "expect": {"decompile pyc": ["Decompiled"]}},
        ]})

    # runner-level diagnostics
    print()
    if FAILS:
        print("%d FAILED: %s" % (len(FAILS), ", ".join(FAILS)))
        sys.exit(1)
    print("ALL FLOW TESTS GREEN")
    sys.exit(0)


if __name__ == "__main__":
    main()