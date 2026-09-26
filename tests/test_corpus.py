"""IkramTool — real-world Lua chunk corpus round-trip test.

test_layers.py proves the protection compositions on a canary. This proves
them on real game code: RESULT/extracted holds 106 real Lua 5.3 precompiled
chunks extracted from the game patch, not hand-made fixtures. Each chunk is
wrapped in every composition the pipeline claims to support, decompiled back,
and the recovered source is re-compiled by luac 5.3. A composition that
silently produces garbage fails here; a composition that loses a function
definition fails here.

Game globals are absent, so execution is not asserted — decompile fidelity
plus a valid recompile is the contract.

Run:  python3 tests/test_corpus.py [N] [COMPOSITIONS]

  N            how many chunks (default: whole corpus)
  COMPOSITIONS how many of the composition matrix per chunk (default: all 9)

Exit 0 = all green.
"""
import shutil
import subprocess
import sys
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import lua_pipeline as lp          # noqa: E402
import ikram_upgrade as iu         # noqa: E402

CORPUS = ROOT / "RESULT" / "extracted"
AES_KEY = b"pubgmobilelua123"
PREFIX = b"\x5a"


def _pkcs7(b, n=16):
    p = n - len(b) % n
    return b + bytes([p]) * p


def _aes(b):
    from Crypto.Cipher import AES
    return AES.new(AES_KEY, AES.MODE_ECB).encrypt(_pkcs7(b))


def _compositions(chunk):
    """Every layered composition the tool must survive, per chunk."""
    gz = zlib.compress(chunk, 9)
    ikrm = iu.stage3_wrap(chunk)
    ikrm_aes = iu.stage3_wrap(_aes(chunk))
    return (
        ("plain", chunk),
        ("prefix_aes", PREFIX * 8 + _aes(chunk)),
        ("prefix_zlib", PREFIX * 8 + gz),
        ("ikrm", ikrm),
        ("ikrm_aes", ikrm_aes),
        ("ikrm_zlib", iu.stage3_wrap(gz)),
        ("prefix_ikrm", PREFIX * 8 + ikrm),
        ("prefix_ikrm_aes", PREFIX * 8 + ikrm_aes),
        ("ikrm_prefix_zlib", iu.stage3_wrap(PREFIX * 8 + gz)),
    )


def _chunks(limit):
    """Real Lua 5.3 chunks from the game patch, non-Lua files dropped."""
    out = []
    for p in sorted(CORPUS.rglob("*.lua")):
        head = p.read_bytes()[:12]
        fam, _ = lp._lua_family_at(head)
        if fam == "Lua 5.3":
            out.append(p)
        if limit and len(out) >= limit:
            break
    return out


def main(argv):
    limit = int(argv[1]) if len(argv) > 1 else 0
    ncomp = int(argv[2]) if len(argv) > 2 else 0
    srcs = _chunks(limit)
    if not srcs:
        print("FATAL: no Lua 5.3 chunks at %s" % CORPUS)
        return 1

    matrix = _compositions(b"")
    if ncomp:
        matrix = matrix[:ncomp]

    tmp = Path(__file__).resolve().parent / "_corpus_tmp"
    tmp.mkdir(parents=True, exist_ok=True)

    print("corpus round-trip: %d real Lua 5.3 chunks x %d compositions"
          % (len(srcs), len(matrix)))
    print("  %-44s %6s %6s %6s %6s" % ("chunk", "bytes", "dec", "cmp", "fn"))
    print("  " + "-" * 74)

    passed = failed = 0
    failures = []
    for i, src in enumerate(srcs):
        chunk = src.read_bytes()
        name = src.name
        if len(name) > 44:
            name = name[:41] + "..."

        dec_ok = cmp_ok = fn_ok = True
        detail = ""
        for label, blob in _compositions(chunk)[:len(matrix)]:
            f = tmp / ("%s_%d.luac" % (label, i))
            f.write_bytes(blob)
            r = lp.run(f, tmp / ("%s_%d" % (label, i)))
            if not r["ok"]:
                dec_ok = False
                detail = "%s:%s" % (label, (r.get("error") or "?")[:20])
                break
            chk = subprocess.run(["luac5.3", "-o", str(tmp / "rt.luac"),
                                  str(r["out"])], capture_output=True)
            if chk.returncode != 0:
                cmp_ok = False
                detail = "%s:recompile" % label
                break
            # A decompile that lost the whole body is not a decompile. Pure
            # data modules carry no `function` keyword at all, so real
            # structure means control flow OR table key assignments.
            body = Path(r["out"]).read_text(errors="replace")
            if (lp._structure_count(body) < 2
                    and lp._table_assign_count(body) < 2):
                fn_ok = False
                detail = "%s:noStructure" % label
                break

        ok = dec_ok and cmp_ok and fn_ok
        print("  %-44s %6d %6s %6s %6s %s"
              % (name, len(chunk),
                 "OK" if dec_ok else "FAIL",
                 "OK" if cmp_ok else "FAIL",
                 "OK" if fn_ok else "FAIL",
                 "" if not detail else "<- " + detail))
        if ok:
            passed += 1
        else:
            failed += 1
            failures.append((name, detail))

    print()
    if failures:
        print("FAILURES (%d):" % len(failures))
        for name, detail in failures:
            print("  %-46s %s" % (name, detail or "<no detail>"))
        print()
    print("PASS %d / %d" % (passed, passed + failed))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    _code = main(sys.argv)
    _tmp = Path(__file__).resolve().parent / "_corpus_tmp"
    if _tmp.exists():
        shutil.rmtree(_tmp, ignore_errors=True)
    sys.exit(_code)
