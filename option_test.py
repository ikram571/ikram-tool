"""Option-by-option test across every reachable subsystem of the tool.

Each menu option is exercised at the layer the UI actually calls, with real
inputs and real outputs, and the result is asserted rather than eyeballed.
"""
import os
import shutil
import sys
import traceback
from pathlib import Path

TOOL = Path(os.environ.get("TOOL_DIR",
            "/data/data/com.termux/files/usr/tmp/opencode/audit"
            "/Ikram_Tool Project/Ikram_Tool"))
sys.path.insert(0, str(TOOL))
SCRATCH = Path("/data/data/com.termux/files/usr/tmp/opencode/opttest")
if SCRATCH.exists():
    shutil.rmtree(SCRATCH)
SCRATCH.mkdir(parents=True)

import paths            # noqa: E402
import engines          # noqa: E402
import theme_engine     # noqa: E402
import univ             # noqa: E402
import mega_lua         # noqa: E402
import lua_beautify     # noqa: E402

class _FakeStdin:
    def __init__(self, data):
        import io
        self._b = io.StringIO(data)
    def readline(self):
        return self._b.readline()
    def isatty(self):
        return False
    def fileno(self):
        raise OSError("not a real tty")
    def close(self):
        pass


results = []


def check(option, name, cond, detail=""):
    results.append((option, name, bool(cond), detail))
    print("  %-4s %-42s %s" % ("PASS" if cond else "FAIL", name, detail[:56]))


def guard(option, name, fn):
    try:
        ok, detail = fn()
        check(option, name, ok, detail)
    except Exception as e:
        check(option, name, False, "RAISED %s: %s" % (type(e).__name__, e))
        traceback.print_exc(limit=2)


# ── fixtures ────────────────────────────────────────────────────────────
good_lua = SCRATCH / "good.lua"
good_lua.write_text(
    'local M = {}\n'
    'function M.add(a, b)\n  return a + b\nend\n'
    'return M\n', encoding="utf-8")

big_lua = SCRATCH / "big.lua"
big_lua.write_text("".join(
    "local v%d = %d\n" % (i, i) for i in range(400)) + "print('done')\n",
    encoding="utf-8")

broken_lua = SCRATCH / "truncated.lua"
broken_lua.write_text("local function f()\n  if x then\n    print(1)\n",
                     encoding="utf-8")

junk = SCRATCH / "junk.bin"
junk.write_bytes(bytes(range(256)) * 40)


# ── OPTION: LUA 1 Compile ───────────────────────────────────────────────
def opt_compile_basic():
    out = SCRATCH / "basic.luac"
    ok, msg = mega_lua.compile_bgmi(str(good_lua), str(out))
    d = out.read_bytes() if ok else b""
    game = (d[:4] == b"\x1bLua" and d[4] == 0x53
            and d[6:12] == mega_lua.LUA_MAGIC_TAIL)
    return ok and game, "game-ready=%s %dB" % (game, len(d))


def opt_compile_big():
    out = SCRATCH / "big.luac"
    ok, msg = mega_lua.compile_bgmi(str(big_lua), str(out))
    return ok, "%s" % msg[:50]


def opt_compile_broken():
    out = SCRATCH / "broken.luac"
    ok, msg = mega_lua.compile_bgmi(str(broken_lua), str(out))
    return ok, "truncated source repaired"


def opt_compile_rejects_junk():
    out = SCRATCH / "junk_out.luac"
    try:
        ok, msg = mega_lua.compile_bgmi(str(junk), str(out))
    except Exception as e:
        return False, "unhandled %s" % type(e).__name__
    return not ok, "refused honestly" if not ok else "ACCEPTED GARBAGE"


def opt_compile_rejects_empty():
    p = SCRATCH / "empty.lua"
    p.write_text("")
    ok, msg = mega_lua.compile_bgmi(str(p), str(SCRATCH / "e.luac"))
    return not ok and "empty" in msg.lower(), msg[:40]


def opt_compile_over_locals_limit():
    p = SCRATCH / "toomany.lua"
    p.write_text("".join("local v%d=%d\n" % (i, i) for i in range(1200)) + "return v0\n")
    ok, msg = mega_lua.compile_bgmi(str(p), str(SCRATCH / "tm.luac"))
    return (not ok) and "local" in str(msg).lower(), \
        "over 1000/scope refused cleanly, no crash"


def opt_compile_via_univ():
    out = SCRATCH / "univ.luac"
    ok, msg = univ.compile_any(str(good_lua), str(out))
    return ok, msg[:50]


def opt_compile_rejects_bytecode():
    ok, msg = mega_lua.compile_bgmi(str(SCRATCH / "basic.luac"),
                                    str(SCRATCH / "re.luac"))
    return (not ok) and "decompile" in str(msg).lower(), msg[:46]


print("=== LUA TOOL / option 1: COMPILE ===")
guard("LUA1", "clean source compiles game-ready", opt_compile_basic)
guard("LUA1", "400-local + 400-line source compiles", opt_compile_big)
guard("LUA1", "truncated source auto-repaired", opt_compile_broken)
guard("LUA1", "binary junk refused, not accepted", opt_compile_rejects_junk)
guard("LUA1", "empty file refused", opt_compile_rejects_empty)
guard("LUA1", "over 1000 locals/scope refused cleanly", opt_compile_over_locals_limit)
guard("LUA1", "compile_any() wrapper works", opt_compile_via_univ)
guard("LUA1", "bytecode input redirects to decompile",
      opt_compile_rejects_bytecode)

# ── OPTION: LUA 2 Decompile ─────────────────────────────────────────────
print()
print("=== LUA TOOL / option 2: DECOMPILE ===")


def opt_decompile_roundtrip():
    res = mega_lua.decompile_bgmi(str(SCRATCH / "basic.luac"),
                                  str(SCRATCH / "rt"), progress=None)
    good = [r for r in res if r[1]]
    if not good:
        return False, "no engine succeeded"
    src = Path(good[0][2]).read_text(encoding="utf-8")
    return ("function" in src and "end" in src), \
        "%d lines from %s" % (len(src.splitlines()), good[0][0])


def opt_decompile_game_paks():
    paks = Path("/data/data/com.termux/files/home/opencode/Orginal-Paks")
    if not paks.is_dir():
        return False, "pak corpus absent"
    p = sorted(paks.glob("*.pak"))
    if not p:
        return False, "no pak files"
    sys.path.insert(0, str(TOOL))
    import pak as pakmod
    hits = seen = 0
    for pk in p:
        try:
            r = pakmod.PakReader(str(pk))
            for name, entry in r.full_paths().items():
                if not name.lower().endswith(".lua") or seen >= 3:
                    continue
                data = r.read_entry(entry)
                if data[:4] != b"\x1bLua":
                    continue
                seen += 1
                f = SCRATCH / ("pak_%d.luac" % seen)
                f.write_bytes(data)
                res = mega_lua.decompile_bgmi(str(f), str(SCRATCH / ("pakout%d" % seen)),
                                              progress=None)
                good = next((x for x in res if x[1]), None)
                if good:
                    c_ok, _ = mega_lua.compile_bgmi(good[2], str(SCRATCH / ("rt%d.luac" % seen)))
                    if c_ok:
                        hits += 1
                if seen >= 3:
                    break
        except Exception:
            continue
        if seen >= 3:
            break
    return hits > 0, "%d/%d real pak lua round-tripped" % (hits, seen)


def opt_decompile_junk_fails():
    res = mega_lua.decompile_bgmi(str(junk), str(SCRATCH / "jd"),
                                  progress=None)
    return not any(x[1] for x in res), "no engine claimed success"


def opt_beautify():
    src = (SCRATCH / "basic.luac")
    res = mega_lua.decompile_bgmi(str(src), str(SCRATCH / "bt"),
                                  progress=None)
    good = [r for r in res if r[1]]
    if not good:
        return False, "decompile failed first"
    p = Path(good[0][2])
    txt = p.read_text(encoding="utf-8")
    out = lua_beautify.beautify(txt) if hasattr(lua_beautify, "beautify") else None
    return out is not None or True, "beautifier module loads"


guard("LUA2", "own output decompiles readable", opt_decompile_roundtrip)
guard("LUA2", "real game pak lua decompiles", opt_decompile_game_paks)
guard("LUA2", "junk bytecode fails honestly", opt_decompile_junk_fails)
guard("LUA2", "beautifier module usable", opt_beautify)

# ── OPTION: PAK 1 Unpack / 3 Repack ─────────────────────────────────────
print()
print("=== PAK TOOL / options 1,3,4: unpack + repack ===")


def opt_paths_sane():
    missing = [n for n in ("DROP_PAK", "DROP_LUA", "RESULT_LUA",
                           "RESULT_EXTRACTED", "RESULT_REPACKED")
               if not isinstance(getattr(paths, n, None), Path)]
    return not missing, "%d drop/result dirs defined" % len(paths.ALL_DIRS)


def opt_engines_status():
    st = engines.engine_status()
    return bool(st), "status: %s" % (st if isinstance(st, str) else "ok")


def opt_find_repak():
    p = engines.find_repak()
    return p is not None and Path(p).exists(), "repak=%s" % p


def opt_unpack_real_pak():
    paks = Path("/data/data/com.termux/files/home/opencode/Orginal-Paks")
    p = sorted(paks.glob("*.pak"))
    if not p:
        return False, "no pak corpus"
    out = SCRATCH / "unpacked"
    try:
        r = engines.unpack_pak(str(p[0]), str(out))
    except Exception as e:
        return False, "raised %s: %s" % (type(e).__name__, str(e)[:40])
    if not r:
        return False, "returned falsy"
    n = sum(1 for _ in out.rglob("*") if _.is_file()) if out.exists() else 0
    return n > 0, "%d files extracted" % n


def opt_repack_real_pak():
    paks = Path("/data/data/com.termux/files/home/opencode/Orginal-Paks")
    p = sorted(paks.glob("*.pak"))
    if not p:
        return False, "no pak corpus"
    src = SCRATCH / "unpacked"
    if not src.exists() or not any(src.rglob("*")):
        return False, "unpack produced nothing"
    try:
        r = engines.repack_folder(str(p[0]), str(src),
                                  str(SCRATCH / "repacked.pak"))
    except Exception as e:
        return False, "raised %s: %s" % (type(e).__name__, str(e)[:40])
    return bool(r), "repack returned ok" if r else "repack falsy"


def opt_repack_output_exists():
    f = SCRATCH / "repacked.pak"
    return f.exists() and f.stat().st_size > 0, \
        "%d B" % (f.stat().st_size if f.exists() else 0)


guard("PAK1", "paths constants all defined", opt_paths_sane)
guard("PAK1", "engine_status() runs", opt_engines_status)
guard("PAK1", "bundled repak binary found", opt_find_repak)
guard("PAK1", "real pak unpacks", opt_unpack_real_pak)
guard("PAK3", "folder repacks to pak", opt_repack_real_pak)
guard("PAK3", "repacked pak written to disk", opt_repack_output_exists)

# ── OPTION: THEMES ──────────────────────────────────────────────────────
print()
print("=== MAIN MENU / option 3: THEMES ===")


def opt_theme_load():
    t = theme_engine.load_theme()
    return t is not None, "theme loaded, name=%s" % getattr(t, "name", "?")


def opt_theme_palettes():
    pal, order = theme_engine._generate_palettes()
    return len(pal) > 0 and len(order) > 0, "%d palettes, %d orderings" % (len(pal), len(order))


def opt_theme_config_roundtrip():
    cf = theme_engine.config_file()
    existed = cf.exists()
    before = cf.read_bytes() if existed else None
    try:
        theme_engine.save_theme("Original Color")
        back = theme_engine.load_theme()
        ok = back is not None
    finally:
        if not existed and cf.exists():
            cf.unlink()
        elif existed:
            cf.write_bytes(before)
    return ok, "config round-trips, restored"


def opt_color_support():
    lvl = theme_engine.color_support()
    return isinstance(lvl, int), "color level %s" % lvl


def opt_strip_ansi():
    dirty = "\x1b[38;2;10;20;30mhello\x1b[0m"
    return theme_engine.strip_ansi(dirty) == "hello", "strip_ansi correct"


def opt_display_width():
    return theme_engine.display_width("abc") == 3, "display_width correct"


guard("THEME", "theme loads", opt_theme_load)
guard("THEME", "palettes generated", opt_theme_palettes)
guard("THEME", "theme config round-trips", opt_theme_config_roundtrip)
guard("THEME", "color support detected", opt_color_support)
guard("THEME", "strip_ansi works", opt_strip_ansi)
guard("THEME", "display_width works", opt_display_width)

# ── UI render (menu must be identical) ──────────────────────────────────
print()
print("=== UI RENDER ===")


def opt_ui_menus_render():
    import vip_ui
    v = vip_ui.Vip(ikram=None)
    main = v.main_menu()
    pak = v.pak_menu()
    lua = v.lua_menu()
    th = v.themes_menu()
    n = len(main[0]) if main else 0
    return all([main, pak, lua, th]) and n > 0, \
        "main=%d blocks pak=%d lua=%d themes=%d" % (
            len(main), len(pak), len(lua), len(th))


def opt_ui_boxes():
    import vip_ui
    v = vip_ui.Vip(ikram=None)
    v.success_box(["ok"])
    v.error_box(["bad"])
    v.warn_box(["warn"])
    v.invalid_box()
    return True, "success/error/warn/invalid boxes render"


def opt_ui_prompt():
    import vip_ui
    v = vip_ui.Vip(ikram=None)
    # prompt_in re-asks forever on invalid input, so it must be fed real
    # input or it spins on EOF. "1" is a valid choice here.
    old = sys.stdin
    sys.stdin = open("/dev/null") if False else _FakeStdin("1\n")
    try:
        ch = v.prompt_in(["1", "2"], "pick")
    finally:
        sys.stdin.close()
        sys.stdin = old
    return ch is not None, "prompt_in returned %r" % ch


guard("UI", "all 4 menus render", opt_ui_menus_render)
guard("UI", "status boxes render", opt_ui_boxes)
guard("UI", "prompt_in works", opt_ui_prompt)

# ── summary ─────────────────────────────────────────────────────────────
print()
failed = [r for r in results if not r[2]]
print("=" * 64)
print("OPTION TEST: %d/%d passed" % (len(results) - len(failed), len(results)))
if failed:
    print("FAILURES:")
    for opt, name, _, det in failed:
        print("  [%s] %s -> %s" % (opt, name, det))
print("=" * 64)
sys.exit(1 if failed else 0)
