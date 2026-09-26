"""IkramTool — layered-protection decompile tests.

Covers composed protection: a protection layer whose payload is itself
protected. Each case is built at run time from one known-good chunk, then
decompiled, recompiled with luac, and EXECUTED. A case only passes when the
recovered source produces the exact expected runtime line, so a validator that
merely looks plausible cannot pass this suite.

Run:  python3 tests/test_layers.py
Exit 0 = all green.
"""
import os
import shutil
import subprocess
import sys
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import lua_pipeline as lp          # noqa: E402
import ikram_upgrade as iu         # noqa: E402

CANARY_SRC = (
    "local t = {1, 2, 3}\n"
    "local s = 0\n"
    "for i = 1, #t do s = s + t[i] end\n"
    "io.write('CANARY-7F3A', '\\t', s, '\\t', 'x-y', '\\t', 15, '\\n')\n"
)
CANARY_OUT = "CANARY-7F3A\t6\tx-y\t15"
AES_KEY = b"pubgmobilelua123"
PREFIX = b"\x5a"


def _pkcs7(b, n=16):
    p = n - len(b) % n
    return b + bytes([p]) * p


def _aes(b):
    from Crypto.Cipher import AES
    return AES.new(AES_KEY, AES.MODE_ECB).encrypt(_pkcs7(b))


def _cases(chunk):
    """(name, blob) for every composition under test."""
    gz = zlib.compress(chunk, 9)
    ikrm_c = iu.stage3_wrap(chunk)
    ikrm_aes = iu.stage3_wrap(_aes(chunk))
    ikrm_gz = iu.stage3_wrap(gz)
    return [
        ("bare_chunk", chunk),
        ("prefix_aes", PREFIX * 8 + _aes(chunk)),
        ("prefix_zlib", PREFIX * 8 + gz),
        ("ikrm_aes", ikrm_aes),
        ("prefix_ikrm", PREFIX * 8 + ikrm_c),
        ("ikrm_zlib", ikrm_gz),
        ("prefix_ikrm_aes", PREFIX * 8 + ikrm_aes),
        ("ikrm_prefix_zlib", iu.stage3_wrap(PREFIX * 8 + gz)),
        ("prefix3_ikrm_zlib", PREFIX * 3 + ikrm_gz),
    ]


def main():
    tmp = Path(__file__).resolve().parent / "_layer_tmp"
    src = tmp / "canary.lua"
    tmp.mkdir(parents=True, exist_ok=True)
    src.write_text(CANARY_SRC, encoding="utf-8")

    comp = tmp / "canary.luac"
    subprocess.run(["luac5.3", "-o", str(comp), str(src)], check=True)
    chunk = comp.read_bytes()

    if not lp._lua_family_at(chunk[:12])[0]:
        print("FATAL: fixture chunk is not a valid lua chunk")
        return 1

    cases = _cases(chunk)
    print("layered-protection decompile: %d cases" % len(cases))
    print()
    print("  %-22s %-8s %-10s %s" % ("case", "decompile", "recompile", "runtime"))
    print("  " + "-" * 66)

    passed = failed = 0
    for name, blob in cases:
        f = tmp / ("%s.luac" % name)
        f.write_bytes(blob)
        r = lp.run(f, tmp / name)
        if not r["ok"]:
            print("  %-22s %-8s %-10s %s"
                  % (name, "FAIL", "-", (r.get("error") or "")[:24]))
            failed += 1
            continue
        out = Path(r["out"])
        rc = subprocess.run(["luac5.3", "-p", str(out)], capture_output=True)
        compiles = rc.returncode == 0
        try:
            run = subprocess.run(["lua5.3", str(out)], capture_output=True,
                                 timeout=20)
            got = run.stdout.decode(errors="replace").strip()
        except subprocess.TimeoutExpired:
            got = "<timeout>"
        if compiles and got == CANARY_OUT:
            print("  %-22s %-8s %-10s %s" % (name, "OK", "OK", "MATCH"))
            passed += 1
        else:
            print("  %-22s %-8s %-10s %s"
                  % (name, "OK", "OK" if compiles else "FAIL", repr(got[:28])))
            failed += 1

    print()
    # A file that decrypts to a valid header but a broken body must be
    # rejected, never written out as a "result".
    bad = bytearray(PREFIX * 8 + _aes(chunk))
    for i in range(8, min(64, len(bad))):
        bad[i] ^= 0xFF
    bf = tmp / "corrupt.luac"
    bf.write_bytes(bytes(bad))
    rb = lp.run(bf, tmp / "corrupt")
    rejected = not rb["ok"]
    print("  %-22s %-8s %-10s %s"
          % ("corrupt_body", "OK" if rejected else "FAIL",
             "-", "rejected" if rejected else "SHIPPED GARBAGE"))
    if rejected:
        passed += 1
    else:
        failed += 1

    print()
    print("PASS %d / %d" % (passed, passed + failed))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    _code = main()
    _tmp = Path(__file__).resolve().parent / "_layer_tmp"
    if _tmp.exists():
        shutil.rmtree(_tmp, ignore_errors=True)
    sys.exit(_code)
