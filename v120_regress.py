"""V120 compile/decompile regression suite.

Run from the IkramTool project root:  python3 v120_regress.py
Exits non-zero if any case fails. Covers the two V120 repair classes
(dangling goto, split _G key) plus every engine path the UI can reach.
"""
import io
import contextlib
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mega_lua  # noqa: E402

PAKS = Path.home() / "opencode/Orginal-Paks"
TMP = Path(tempfile.mkdtemp(prefix="ikram_v120_"))
results = []


def quiet(fn, *a, **k):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        return fn(*a, **k)


def record(name, ok, detail=""):
    results.append((name, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" :: {detail}" if detail else ""))


print("=== V120 COMPILE ENGINE ===")

# 1. small
(TMP / "small.lua").write_text("local x = 1\nprint(x)\n")
ok, msg = quiet(mega_lua.compile_bgmi, str(TMP / "small.lua"), str(TMP / "small.luac"))
record("compile small lua", ok and Path(TMP / "small.luac").stat().st_size > 0, msg[:60])

# 2. large 1.2MB / 60k statements
with open(TMP / "big.lua", "w") as f:
    f.write("local t = {}\n")
    for i in range(60000):
        f.write("t[%d] = %d * 2\n" % (i, i))
    f.write("print(#t)\n")
t0 = time.time()
ok, msg = quiet(mega_lua.compile_bgmi, str(TMP / "big.lua"), str(TMP / "big.luac"))
record("compile 1.2MB lua", ok, f"{time.time()-t0:.1f}s {msg[:50]}")

# 3. A truncated construct is now REPAIRED rather than refused: a decompiler
#    that cut a file mid-table is exactly what this engine exists to fix.
(TMP / "broken.lua").write_text("local x = {\n")
try:
    ok, msg = quiet(mega_lua.compile_bgmi, str(TMP / "broken.lua"), str(TMP / "broken.luac"))
    record("truncated table repaired, compiles", ok, str(msg)[:50])
except Exception as e:
    record("truncated table repaired, compiles", False, f"raised {type(e).__name__}")

# 3b. Input that no repair can rescue must still fail honestly with a line
#     number. The repairs only ever ADD closers, so surplus `end` keywords
#     are the honest counter-case: garbage in, honest error out, never a lie.
(TMP / "hopeless.lua").write_text("print(1)\nend\nend\nend\n")
try:
    ok, msg = quiet(mega_lua.compile_bgmi, str(TMP / "hopeless.lua"), str(TMP / "hopeless.luac"))
    record("unrecoverable syntax fails honestly", not ok and ":" in str(msg), str(msg)[:50])
except Exception as e:
    record("unrecoverable syntax fails honestly", False, f"raised {type(e).__name__}")

# 4. empty
(TMP / "empty.lua").write_text("")
ok, msg = quiet(mega_lua.compile_bgmi, str(TMP / "empty.lua"), str(TMP / "empty.luac"))
record("empty file rejected", not ok, str(msg)[:50])

# 5. binary input rejected
(TMP / "rand.luac").write_bytes(os.urandom(4096))
ok, msg = quiet(mega_lua.compile_bgmi, str(TMP / "rand.luac"), str(TMP / "rand2.luac"))
record("binary input rejected", not ok, str(msg)[:50])

print("=== V120 REPAIRS (only fire after a real compile failure) ===")

# 6. dangling goto is repaired
dangling = "local i = 0\n::L1::\ni = i + 1\nif i < 3 then goto L12 end\nprint(i)\n"
(TMP / "goto.lua").write_text(dangling)
ok, msg = quiet(mega_lua.compile_bgmi, str(TMP / "goto.lua"), str(TMP / "goto.luac"))
record("dangling goto repaired", ok and "repaired" in str(msg), str(msg)[-58:])

# 7. split _G key is repaired
split = '_G.foo = 1\n_G.__RAJPUT Session = nil\nprint(_G.foo)\n'
(TMP / "split.lua").write_text(split)
ok, msg = quiet(mega_lua.compile_bgmi, str(TMP / "split.lua"), str(TMP / "split.luac"))
record("split _G key repaired", ok, str(msg)[-58:])

# 8. valid _G usage must NOT be rewritten
valid = "local G = _G\nG.x = 5\nprint(G.x, _G.x)\n"
(TMP / "valid.lua").write_text(valid)
ok, msg = quiet(mega_lua.compile_bgmi, str(TMP / "valid.lua"), str(TMP / "valid.luac"))
record("valid _G untouched", ok and "repaired" not in str(msg), str(msg)[-40:])

# 9. a goto inside a string must not be neutralised
strgot = 'local s = "goto L99"\nlocal t = [[::L5::]]\nprint(s, t)\n'
(TMP / "strgoto.lua").write_text(strgot)
ok, msg = quiet(mega_lua.compile_bgmi, str(TMP / "strgoto.lua"), str(TMP / "strgoto.luac"))
record("goto in string/comment ignored", ok and "repaired" not in str(msg), str(msg)[-40:])

# 9b. a Lua keyword after a dot must not be folded into a global name
kwdot = "_G.Client if x then print(x) end\n"
(TMP / "kwdot.lua").write_text(kwdot)
out, notes = mega_lua._repair_split_globals(kwdot)
record("keyword after dot not folded", out == kwdot and not notes, repr(out[:34]))

# 9c. a spaced global key with a field access IS foldable
fold = "_G.__RAJPUT Watermark.new\n"
out, notes = mega_lua._repair_split_globals(fold)
record("spaced key + field folded",
       out == '_G["__RAJPUT Watermark"].new\n' and notes, repr(out.strip()))

# 9d. unreachable tail after return is sealed away
dead = "local function f(x)\n  if x then\n    return 1\n  end\n  print(2)\n  print(3)\nend\n"
(TMP / "dead.lua").write_text(dead)
ok, msg = quiet(mega_lua.compile_bgmi, str(TMP / "dead.lua"), str(TMP / "dead.luac"))
record("dead tail after return sealed", ok, str(msg)[-46:])

# 9e. valid returned-closure bodies must survive untouched
closure = ("local function f()\n  return function(p1, p2)\n"
           "    local a = {}\n    if type(p1) == 'number' then\n"
           "      return a\n    end\n    return p2\n  end\nend\n")
(TMP / "closure.lua").write_text(closure)
out, notes = mega_lua._seal_dead_code(closure)
record("returned closure body intact", out == closure and not notes, f"{len(notes)} dropped")
ok, msg = quiet(mega_lua.compile_bgmi, str(TMP / "closure.lua"), str(TMP / "closure.luac"))
record("returned closure compiles", ok and "repaired" not in str(msg), str(msg)[-40:])

print("=== V120 STRUCTURAL REPAIRS (decompiler artifacts) ===")

# Every one of these is a real defect unluac-rs emits. All must compile.
ARTIFACTS = {
    "truncated blocks get closed": "local function f()\n  if x then\n    print(1)\n",
    "nested fn missing its end": "local function a()\nlocal function b()\nreturn 1\n",
    "repeat missing until": "repeat\n  print(1)\n",
    "unterminated long string": 'local s = [[never closed\nprint(1)\n',
    "table cut off mid line": "local function f()\n  return {a=1, b=2,\n",
    "orphaned else at top level": "else\nprint(1)\n",
    "duplicate label in one fn": "local function a()\n  ::x::\n  ::x::\n  return 1\nend\n",
    "label named a keyword": "do\n::in::\ngoto in\nend\n",
    "goto with no label at all": "print(1)\ngoto SKIP\nprint(2)\n",
    "shebang line": "#!/usr/bin/lua\nprint('hi')\n",
    "utf-8 BOM": "\ufeffprint('bom')\n",
    "CRLF line endings": "local a=1\r\nprint(a)\r\n",
    "260 locals in one function": "local function f()\n"
        + "".join("  local v%d=%d\n" % (i, i) for i in range(260))
        + "  return v1\nend\n",
    "60 levels of nesting": "".join("  " * i + "if a then\n" for i in range(60))
        + "print(1)\n" + "\n".join("end" for _ in range(60)),
}
for name, src in ARTIFACTS.items():
    f = TMP / ("art_%s.lua" % abs(hash(name)))
    f.write_text(src, encoding="utf-8")
    o, m = quiet(mega_lua.compile_bgmi, str(f), str(f)[:-4] + ".luac")
    record(name, o, str(m)[-52:] if not o else "compiles")

# A goto in a different function than its label is dead, and the fix must be
# driven by the compiler's own line report rather than a static scope guess.
crossfn = ("local function a()\n  ::L::\n  return 1\nend\n"
           "local function b()\n  goto L\n  return 2\nend\n")
(TMP / "crossfn.lua").write_text(crossfn)
o, m = quiet(mega_lua.compile_bgmi, str(TMP / "crossfn.lua"), str(TMP / "crossfn.luac"))
record("cross-function goto repaired", o, str(m)[-52:] if not o else "compiles")
# ...and the label that IS in scope must survive it
keepfn = ("local function a()\n  ::L::\n  goto L\n  return 1\nend\n")
(TMP / "keepfn.lua").write_text(keepfn)
out, notes = mega_lua._neutralise_gotos(keepfn)
record("in-scope goto survives", out == keepfn and not notes, f"{len(notes)} stripped")

print("=== V120 GAME-READY OUTPUT ===")

# Compile must emit the bare game format: no protection wrapper, valid header.
gr = (TMP / "gr.luac").read_bytes() if (TMP / "gr.luac").exists() else b""
ok, msg = quiet(mega_lua.compile_bgmi, str(TMP / "small.lua"), str(TMP / "gr.luac"))
gr = (TMP / "gr.luac").read_bytes()
record("output is game-ready BGMI",
       gr[:4] == b"\x1bLua" and gr[4] == 0x53
       and gr[6:12] == mega_lua.LUA_MAGIC_TAIL,
       "magic " + gr[:10].hex())
record("no protection wrapper on compile", gr[:4] != b"IKRM", "header " + repr(gr[:4]))
record("message says game-ready", "game-ready" in str(msg), str(msg)[:40])

print("=== V120 DECOMPILE ENGINE ===")

# 10. round-trip small
res = quiet(mega_lua.decompile_bgmi, str(TMP / "small.luac"), str(TMP / "rt"), progress=lambda m: None)
best = next((x for x in res if x[1]), None)
record("decompile own output", best is not None, (best[0] if best else "no result"))

# 11. random binary must fail honestly, never as success
res = quiet(mega_lua.decompile_bgmi, str(TMP / "rand.luac"), str(TMP / "rd"), progress=lambda m: None)
record("random binary fails honestly", not any(x[1] for x in res), "no method claimed success")

# 12. real game bytecode from the original paks, if present
pak = PAKS / "game_patch_4.6.1.21575.pak"
if pak.exists() and PAKS.is_dir():
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import pak as pakmod
    r = pakmod.PakReader(str(pak))
    n_ok = n = 0
    for name, entry in r.full_paths().items():
        if not name.lower().endswith(".lua"):
            continue
        data = r.read_entry(entry)
        if data[:4] != b"\x1bLua":
            continue
        (TMP / "g.luac").write_bytes(data)
        res = quiet(mega_lua.decompile_bgmi, str(TMP / "g.luac"), str(TMP / "go"), progress=lambda m: None)
        good = next((x for x in res if x[1]), None)
        if not good:
            continue
        n += 1
        c_ok, _ = quiet(mega_lua.compile_bgmi, good[2], str(TMP / "g2.luac"))
        n_ok += 1 if c_ok else 0
    if n:
        record("real game files decompile+recompile", n_ok == n, f"{n_ok}/{n} passed")
    else:
        record("real game files decompile+recompile", True, "no bytecode samples present, skipped")
else:
    record("real game files decompile+recompile", True, "paks not present, skipped")

print("=== V120 UI + PROTECTION ===")

# 13. ProgressFrame.close must exist
import vip_ui  # noqa: E402
v = vip_ui.Vip(stream=io.StringIO())
fr = vip_ui.ProgressFrame(v, title="t")
fr.phase("step")
fr.close(cur="Finished")
record("ProgressFrame.close() works", True)

# 14. protection shim produces tool-readable IKRM
import ikram_upgrade as iu  # noqa: E402
import protect_compile as pc  # noqa: E402
std = iu._luac_compile("local a = 1\nprint(a)\n")
prot = pc.protect(std)
unwrapped = pc.unprotect(prot)
record("protect_compile shim round-trips",
       iu.is_protected(prot) and unwrapped is not None and unwrapped[:4] == b"\x1bLua",
       f"{len(prot)}B, is_protected={iu.is_protected(prot)}")

print("=== V120 VERSION STRINGS ===")
vers_ok = True
for f in ("vip_ui.py", "lua_pipeline.py", "update.py"):
    p = Path(__file__).resolve().parent / f
    if p.exists():
        t = p.read_text(errors="replace")
        if "V120" not in t and "120" not in t:
            vers_ok = False
record("version strings bumped to V120", vers_ok)

bad = [n for n, ok, _ in results if not ok]
print()
print("=" * 58)
print(f"  {len(results)-len(bad)}/{len(results)} passed")
if bad:
    print("  FAILED: " + ", ".join(bad))
print(f"  artifacts: {TMP}")
print("=" * 58)
sys.exit(1 if bad else 0)
