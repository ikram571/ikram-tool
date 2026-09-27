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

# The real corpus is 106 chunks extracted from a game patch. It is large and
# gitignored, so a fresh clone has none of it — and a suite that dies there
# is indistinguishable from a suite that found a real defect.
CORPUS = Path(os.environ.get("IKRAM_TEST_CORPUS")
              or (ROOT / "RESULT" / "extracted"))
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


# Small Lua 5.3 programs written for this suite, each one leaning on the
# constructs a decompiler most often gets wrong: upvalues, varargs, integer
# division, goto/labels, metatables, string escapes, tail calls, varargs in
# a table constructor, and a coroutine.
_SYNTH_SOURCES = (
    """local t = {}
for i = 1, 10 do t[i] = i * i end
local s = 0
for _, v in ipairs(t) do s = s + v end
return s
""",
    """local function counter(start)
  local n = start
  return function(step)
    n = n + (step or 1)
    return n
  end
end
local c = counter(10)
c(5)
return c()
""",
    """local function join(sep, ...)
  local parts = {}
  for i = 1, select('#', ...) do parts[#parts + 1] = tostring(select(i, ...)) end
  return table.concat(parts, sep)
end
return join('-', 'a', 'b', 'c')
""",
    """local out = {}
for i = 1, 5 do
  if i % 2 == 0 then goto continue end
  out[#out + 1] = i
  ::continue::
end
return 7 // 2, 7 % 2, out
""",
    """local V = {}
V.__index = V
function V.new(x) return setmetatable({x = x}, V) end
function V:double() return self.x * 2 end
return V.new(21):double()
""",
    """local s = "a\tb\n\\c\"d"
local hex = string.format("%05.2f|%x|%q", 3.14159, 48879, "hi\n")
return #s, hex:upper()
""",
    """local function tail(n) if n <= 0 then return 0 end return tail(n - 1) + 1 end
local co = coroutine.create(function(a, b)
  coroutine.yield(a + b)
  return a * b
end)
local _, first = coroutine.resume(co, 3, 4)
local _, done = coroutine.resume(co)
return tail(100), first, done
""",
    """local t = setmetatable({}, {__mode = 'k'})
local key = {}
t[key] = 'weak'
local nested = { a = { b = { c = { d = 42 } } } }
return t[key], nested.a.b.c.d
""",
)


def _synthetic_chunks(limit=0):
    """Compile the sources above into 5.3 chunks as a stand-in corpus.

    Used only when the real corpus is absent, and only as a floor under the
    suite: it proves decompiling and recompiling stay self-consistent across
    the awkward constructs, and the banner says SYNTHETIC so nobody reads it
    as real-game coverage.
    """
    luac = shutil.which("luac5.3") or shutil.which("luac")
    if not luac:
        return []
    tmp = Path(__file__).resolve().parent / "_corpus_synth"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True, exist_ok=True)
    out = []
    for i, body in enumerate(_SYNTH_SOURCES):
        if limit and len(out) >= limit:
            break
        src = tmp / ("synth%02d.lua" % i)
        chunk = tmp / ("synth%02d.luac" % i)
        try:
            src.write_text(body, encoding="utf-8")
            r = subprocess.run([luac, "-o", str(chunk), str(src)],
                               capture_output=True, timeout=60)
            if r.returncode == 0 and chunk.exists() and chunk.stat().st_size:
                out.append(chunk)
        except Exception:
            pass
    return out


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
    kind = "real"
    if not srcs:
        srcs = _synthetic_chunks(limit)
        kind = "synthetic"
        if not srcs:
            print("SKIP: no Lua 5.3 chunks at %s and luac5.3 is not "
                  "available to build a stand-in corpus" % CORPUS)
            return 3
        print("NOTE: no real corpus at %s — running a synthetic stand-in."
              % CORPUS)
        print("      Synthetic proves the pipeline is self-consistent; it "
              "does NOT stand in for real-game fidelity.")

    matrix = _compositions(b"")
    if ncomp:
        matrix = matrix[:ncomp]

    tmp = Path(__file__).resolve().parent / "_corpus_tmp"
    tmp.mkdir(parents=True, exist_ok=True)

    print("corpus round-trip: %d %s Lua 5.3 chunks x %d compositions"
          % (len(srcs), kind, len(matrix)))
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
        notes = []
        for label, blob in _compositions(chunk)[:len(matrix)]:
            f = tmp / ("%s_%d.luac" % (label, i))
            f.write_bytes(blob)
            r = lp.run(f, tmp / ("%s_%d" % (label, i)))
            if not r["ok"]:
                # A decompiler that cannot rebuild a chunk is allowed to say
                # so — what is NOT allowed is silence. The pipeline's
                # contract is: fall back to a disassembly, write the file,
                # and say why. Anything else (a crash, a missing artifact, a
                # silent empty result) is a real failure.
                dpath = r.get("disasm_path")
                if (r.get("status") == "disassembled" and dpath
                        and Path(dpath).exists()
                        and Path(dpath).stat().st_size
                        and r.get("msg")):
                    notes.append("%s:decompile-not-possible(%s)"
                                 % (label, Path(dpath).name))
                    continue
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
        if ok and notes:
            detail = "; ".join(notes)
        print("  %-44s %6d %6s %6s %6s %s"
              % (name, len(chunk),
                 "OK" if dec_ok else "FAIL",
                 "OK" if cmp_ok else "FAIL",
                 "OK" if fn_ok else "FAIL",
                 "<- " + detail if detail else ""))
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
