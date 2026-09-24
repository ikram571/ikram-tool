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
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

RUNNER = Path(__file__).resolve().parent / "_runner.py"

FIX_DIR = Path(os.environ.get(
    "FIX_ROOT",
    "/data/data/com.termux/files/home/opencode/IkramTool Project/Pakfiles For Testing"))
FIX_PAK = FIX_DIR / "core_patch_4.6.0.21537.pak" if FIX_DIR.is_dir() else None

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
    run_case("shell", {
        "steps": [{"script": ["0"],
                   "expect": {"brand": ["IkramTool", "v113"],
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
                                   "RESULT/extracted/core"]}}]})

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
                             "RESULT/Repacked/core.pak"]}}]})

        # 7 ---- costom pak skeleton (empty ENTER = full skeleton)
        run_case("costom_real", {
            "fixtures": dict(pak),
            "exists": ["RESULT/CostomPak/core.pak"],
            "steps": [{"script": ["1", "4", "", "", "0", "0"],
                       "expect": {"costom done":
                                  ["Costom Pak ready",
                                   "RESULT/CostomPak/core.pak"]}}]})

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