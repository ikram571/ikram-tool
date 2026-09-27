"""Regression for the Baki (secondary) 'COSTOM PAK' path.

The VIP menu's Custom PAK wrote 0-byte bodies, and the Baki menu had the same
defect independently: its ENTER branch went through _inject_skeleton, which
stubs every file. Both are fixed by routing ENTER through
_build_full_content_custom -> engines.build_custom_pak, but only the VIP menu
had a test. This suite pins the Baki side so it cannot drift back.

Drives ikram_patch._make_costom_pak directly with target=_SKELETON, which is
what the Baki ENTER branch passes, against a REAL ue4 pak built by repak, then
reads the output back with the engine's own reader and compares every body to
the source. Also asserts the temp session is removed, and that a targeted
(non-ENTER) build still behaves.
"""
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
SB = Path(os.environ.get("IKRAM_TEST_SANDBOX")
          or (ROOT / "tests" / ".sandbox_baki"))
KEY = "8A75AFDF1C74AB55B79DC1DD4ABE4B01360A059D77F243EF4EFADA41A59D71A0"
REPAK = str(ROOT / "repak")

import engines
import ikram_patch

PASS = FAIL = 0


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok   %s" % name)
    else:
        FAIL += 1
        print("  FAIL %s  %s" % (name, extra))


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
    (tree / "Config" / "GameUserSettings.ini").write_bytes(b"res=1440p\n")
    (tree / "Content" / "Lua" / "data.lua").write_bytes(b"x,y,z=9,8,7\n")
    (tree / "Content" / "Lua" / "gameplay.lua").write_bytes(b"return 7\n")
    (tree / "Content" / "Lua" / "ui.lua").write_bytes(b"-- ui\n")
    pak = SB / "base.pak"
    r = subprocess.run([REPAK, "pack", str(SB / "tree"),
                        "--mount-point", "../../../",
                        "--version", "V8B", "--compression", "Zlib",
                        str(pak)], capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit("repak pack failed: %s %s" % (r.stdout, r.stderr))
    return pak, sorted(engines.list_pak_paths(pak))


def body_bytes(pak, u):
    d = SB / "verify"
    shutil.rmtree(d, ignore_errors=True)
    u.Ue4Pak(pak, aes_key=KEY).extract_all(d)
    return {str(f.relative_to(d)).replace("\\", "/"): f.read_bytes()
            for f in sorted(d.rglob("*")) if f.is_file()}


def sessions():
    """Live custom-build sessions in the platform temp dir. The prefix and the
    temp root are read from engines rather than hardcoded: gettempdir() is the
    Termux package dir here, and a literal /tmp would look empty and pass
    vacuously."""
    root = Path(tempfile.gettempdir())
    if not root.exists():
        return []
    return [q for q in root.iterdir()
            if q.name.startswith(engines.CUSTOM_SESSION_PREFIX)]


def main():
    u = load_ue4()
    pak, allp = build_template()
    print("template pak: %d paths" % len(allp))
    src = body_bytes(pak, u)
    check("source bodies are non-empty", all(src.values()), str(src))

    outdir = SB / "out"
    outdir.mkdir(parents=True, exist_ok=True)

    # --- ENTER (target=_SKELETON): the branch that used to write 0-byte bodies
    before = sessions()
    out = outdir / "baki_enter.pak"
    ikram_patch._make_costom_pak(pak, out, ikram_patch._SKELETON,
                                 kind="ue4", aes_key=KEY)
    check("ENTER: produced a pak", out.exists(), str(out))
    got = body_bytes(out, u)
    check("ENTER: every source path present", sorted(got) == allp,
          "%s" % sorted(set(allp) ^ set(got)))
    check("ENTER: no 0-byte body", all(got.values()), str(got))
    check("ENTER: every body is the ORIGINAL content", got == src,
          str({k: (got.get(k), src.get(k)) for k in set(got) | set(src)
               if got.get(k) != src.get(k)}))

    # repak must accept it too, not just our own reader
    r = subprocess.run([REPAK, "list", str(out)],
                       capture_output=True, text=True)
    check("ENTER: repak can read the output", r.returncode == 0,
          r.stderr[-200:])

    # --- the non-ENTER branch: it builds an empty shell by design (it packs an
    # empty tempdir and returns (0, 0)), so assert that guarantee rather than
    # inventing a content requirement it never made.
    target = allp[0]
    out2 = outdir / "baki_one.pak"
    ndirs, nfiles = ikram_patch._make_costom_pak(
        pak, out2, target, kind="ue4", aes_key=KEY)
    check("targeted: produced a non-empty pak",
          out2.exists() and out2.stat().st_size > 0, str(out2))
    check("targeted: reports no copied files", (ndirs, nfiles) == (0, 0),
          str((ndirs, nfiles)))
    r2 = subprocess.run([REPAK, "list", str(out2)],
                        capture_output=True, text=True)
    check("targeted: repak can read the shell", r2.returncode == 0,
          r2.stderr[-200:])

    # --- temp session hygiene
    after = sessions()
    check("no temp session left behind", after == before,
          str([str(p) for p in after]))

    shutil.rmtree(SB, ignore_errors=True)
    print("\n%d passed, %d failed" % (PASS, FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
