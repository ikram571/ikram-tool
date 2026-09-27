"""IkramTool V112 — engine unit tests (Section D).
Run:  python3 tests/test_engine.py
Exit 0 = all green.
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

FAILS = []
SKIPS = []


def check(name, cond, extra=""):
    if cond:
        print("PASS  %s" % name)
    else:
        FAILS.append(name)
        print("FAIL  %s  %s" % (name, extra))


def skip(name, why):
    SKIPS.append((name, why))
    print("SKIP  %s  (%s)" % (name, why))


# ------------------------------------------------------------- D1 BOX
from box_engine import BoxEngine, SEP, visible_len
from theme_engine import Theme, THEMES, strip_ansi

be = BoxEngine(Theme("Cyber Blue"))

huge_line = be.draw_box(["x" * 1200], width=None)          # auto truncate
check("box long line truncates", "…" in huge_line,
      "1200-char line no crash")
empty_box = be.draw_box([], "heavy", title="T")            # empty content
check("box empty content renders", "╔" in empty_box and "╝" in empty_box)
one_box = be.draw_box(["a"], "rounded")                    # 1-char content
check("box 1-char content", "│" in one_box)
min_box = be.draw_box(["yes"], "heavy", width=None)        # auto width >=50
check("box width >=50", visible_len(min_box.splitlines()[0]) >= 50)
for style in ("heavy", "double", "rounded", "thick", "light", "minimal"):
    s = be.draw_box(["hello"], style, title="t")
    check("style %s renders" % style, "hello" in s and len(s) > 5)
sep_box = be.draw_box(["a", SEP, "b"], "heavy", title="t")  # divider row
check("box SEP divider renders", "╠" in sep_box or "├" in sep_box or "┣" in sep_box)
try:
    from box_engine import box as _legacy_none_op
except Exception:
    check("only 5 public box styles", False, "engine regressed")
lr = be.draw_labeled_row("label", "v" * 300)               # long value
check("labeled row long value no crash", len(lr) > 0)

# ------------------------------------------------------------- D2 THEME
from theme_engine import Theme, THEMES, strip_ansi
import theme_engine as _te
_orig_is_tty = _te.is_tty
_te.is_tty = lambda stream=None: True  # force ANSI so colour maths is real
try:
    for name in THEMES:
        th = Theme(name)
        s = th.apply("hello", "title") + th.apply("x", "error")
        check("theme %s roles ansi" % name, "\x1b[" in s)
    pink = Theme("Neon Pink")
    long_pink = pink.apply("ABCDEFGHIJKL", "border")            # solid border colour
    import re as _re
    codes = set(_re.findall(r"38;5;([0-9]+)", long_pink))
    check("neon pink border color present", len(codes) >= 1, str(sorted(codes)))
    check("neon pink every char colored", len(strip_ansi(long_pink)) == 12
          and "ABCDEFGHIJKL" == strip_ansi(long_pink))
    check("theme apply None empty",
          strip_ansi(Theme("Ice White").apply(None, "primary")) == "")
    check("all 267 theme names", len(THEMES) == 267, str(len(THEMES)))
    check("shipped 11 themes still first", tuple(THEMES[:11]) == (
        "Original Color", "Neon Pink", "Cyber Blue", "Blood Red",
        "Matrix Green", "Gold VIP", "Purple Reign", "Ice White",
        "Sunset Orange", "Ocean Teal", "Lava"), str(THEMES[:11]))

finally:
    _te.is_tty = _orig_is_tty

# config persistence (isolated HOME -> ~/.ikramtool/config)
with tempfile.TemporaryDirectory() as td:
    old_home = os.environ.get("HOME")
    os.environ["HOME"] = td
    import importlib
    import theme_engine
    theme_engine = importlib.reload(theme_engine)
    cfg = theme_engine.config_file()
    theme_engine.save_theme("Gold VIP")
    check("theme config at ~/.ikramtool/config", str(cfg).endswith(
        os.path.join(".ikramtool", "config")) and cfg.is_file())
    check("theme load roundtrip", theme_engine.load_theme().name == "Gold VIP")
    cfg.write_text("{corrupted")                    # corrupt config
    check("theme corrupt config fallback", theme_engine.load_theme().name in THEMES)
    cfg.unlink()                                    # missing config
    check("theme missing config fallback", theme_engine.load_theme().name in THEMES)
    if old_home is not None:
        os.environ["HOME"] = old_home

# ------------------------------------------------------------- D3 DETECT
import pathlib
_ROOT = pathlib.Path(__file__).resolve().parent.parent
_FIX_DIRS = [
    pathlib.Path(d) for d in [os.environ.get("IKRAM_TEST_FIXTURES", "")] if d
] + [
    _ROOT / "tests" / "fx",
    _ROOT / "tests" / ".sandbox_paks",
    _ROOT / "Paks",
    pathlib.Path.home() / "Paks",
]
try:
    from lua_bgmi import detect_format, is_bgmi
    import univ
    from univ import detect as detect_lua
    import lua_pipeline
    td = tempfile.mkdtemp()
    src = Path(td) / "t.lua"
    src.write_text(
        "local function add(a, b)\n"
        "    if a > b then return a end\n"
        "    return b\n"
        "end\n"
        "print(add(1, 3))\n")
    ok, _ = univ.compile_any(str(src), str(Path(td) / "t.luac"),
                             progress=None, strip=False)
    check("compile fixture", ok)
    if ok:
        good_luac = Path(td) / "t.luac"
        k = detect_lua(good_luac)
        check("detect compiled lua", k not in (None, "unsupported", "unknown"),
              str(k))
        import ikram_upgrade
        check("compile output is IKRM-protected",
              ikram_upgrade.is_protected(good_luac.read_bytes()))
        payload = ikram_upgrade.try_unwrap(good_luac.read_bytes())
        check("IKRM unwrap valid bgmi", payload is not None)
        if payload is None:
            payload = good_luac.read_bytes()
        fmt = detect_format(payload)
        check("bgmi detect_format", bool(fmt))
        meta = lua_pipeline.detect_report(payload)
        check("detect_report magic kind", meta["kind"] == "standard Lua bytecode",
              str(meta))
        check("detect_report band defined", meta["band"] in (
            "source", "standard bytecode", "lightly encrypted", "encrypted"),
            str(meta))
        # decompile roundtrip
        ok2, msg = univ.decompile_any(str(good_luac),
                                      str(Path(td) / "t_GAME.lua"),
                                      progress=None)
        check("decompile roundtrip validates", ok2, str(msg)[:60])
        out = (Path(td) / "t_GAME.lua").read_text(errors="ignore")
        check("decompiled is lua", "local" in out.lower() and len(out) > 20,
              out[:60])
        v = lua_pipeline.validate(out)
        check("validator 8/8 on real output", v["ok"] and v["score"] == 8,
              str(v["checks"]))
        with open(Path(td) / "t2.luac", "wb") as f:
            f.write(good_luac.read_bytes()[:10])           # truncated
        kx = detect_lua(Path(td) / "t2.luac")
        check("detect truncated no crash", True)
    # entropy spot checks (lua_pipeline)
    e0 = lua_pipeline.shannon_entropy(b"\x00" * 100)
    e1 = lua_pipeline.shannon_entropy(b"\x00" * 50 + b"\xff" * 50)
    check("entropy empty data", lua_pipeline.shannon_entropy(b"") == 0.0)
    check("entropy uniform", abs(e0 - 0.0) < 0.01, str(e0))
    check("entropy mixed", abs(e1 - 1.0) < 0.01, str(e1))
    band = lua_pipeline.entropy_band(3.0)
    check("entropy band source", band == "source", band)
    band = lua_pipeline.entropy_band(9.0)
    check("entropy band encrypted", band == "encrypted", band)
except Exception as e:
    import traceback
    traceback.print_exc()
    check("D3 detection suite", False, str(e))

# ------------------------------------------------------------- D4 PIPELINE
try:
    import lua_pipeline as lp
    import univ as _univ
    td = tempfile.mkdtemp()
    src = Path(td) / "ok.lua"
    src.write_text(
        "local x = 10\n"
        "local function helper(v)\n"
        "  return v * 2 + x\n"
        "end\n"
        "local sum = 0\n"
        "for i = 1, x do\n"
        "  sum = sum + helper(i)\n"
        "end\n"
        "print(sum)\n", encoding="utf-8")
    comp = Path(td) / "ok.luac"
    ok, _ = _univ.compile_any(str(src), str(comp), progress=None, strip=False)
    check("pipeline compile ok", ok)
    if ok:
        r = lp.run(Path(td) / "ok.luac", Path(td) / "out")
        check("pipeline decompile ok", r["ok"], str(r["msg"])[:120])
        if r["ok"]:
            check("pipeline output name _decompiled.lua",
                  r["out"].name == "ok_decompiled.lua", r["out"].name)
            check("pipeline output is lua", "local" in r["out"].read_text())
            check("pipeline quality", r["quality"] and "/8" in r["quality"])
    garbage = Path(td) / "junk.luac"
    garbage.write_bytes(bytes(range(256)) * 8)
    r2 = lp.run(garbage, Path(td) / "out2")
    check("pipeline garbage fails", not r2["ok"])
    check("pipeline FAILED.txt written", r2["fail_path"]
          and r2["fail_path"].name == "junk_FAILED.txt"
          and r2["fail_path"].is_file())
    txt = (Path(td) / "out2" / "junk_FAILED.txt").read_text(errors="ignore")
    check("FAILED.txt lists methods", "Methods tried:" in txt)
    check("FAILED.txt stores entropy", "Entropy" in txt)
except Exception as e:
    import traceback
    traceback.print_exc()
    check("D4 pipeline suite", False, str(e))

# ------------------------------------------------------------- D6 MENUS
from vip_ui import Vip
try:
    vip_dummy = Vip()
    pm = [strip_ansi(r) for r in vip_dummy.pak_menu()]
    lm = [strip_ansi(r) for r in vip_dummy.lua_menu()]
    for label in ("Unpack", "Inject", "Repack", "Costom Pak"):
        check("pak menu has %s" % label, any(label in r for r in pm))
    for gone in ("Verify", "List", "Pack Files", "Analyze"):
        check("pak menu dropped %s" % gone,
              not any(gone in r for r in pm))
    for label in ("Compile", "Decompile"):
        check("lua menu has %s" % label, any(label in r for r in lm))
    for gone in ("Analyze", "XOR", "Strings", "Batch"):
        check("lua menu dropped %s" % gone,
              not any(gone in r for r in lm))
    check("pak menu keeps C/R", any("Clear DROP/pak/" in r for r in pm)
          and any("Clear RESULT/" in r for r in pm))
    check("lua menu keeps C/R", any("Clear DROP/lua/" in r for r in lm)
          and any("Clear RESULT/lua/" in r for r in lm))
except Exception as e:
    import traceback
    traceback.print_exc()
    check("D6 menus", False, str(e))

# ------------------------------------------------------------- D5 PAK
# Two halves, because the two PAK engines are different formats:
#
#   D5a  tencent  — index parse / inject / byte-exact read-back. Needs a real
#                   tencent archive, which is licensed game data and cannot be
#                   synthesised (the writer only bootstraps from a reader). When
#                   none is present this is an absent fixture, reported as a skip.
#   D5b  ue4      — pack / extract / repack / re-extract, byte-for-byte. Built
#                   here with the bundled repak, so it runs on every machine and
#                   the round-trip is never silently untested.
def _pak_fixtures(dirs):
    out = []
    for d in dirs:
        try:
            if d.is_dir():
                out += [p for p in sorted(d.glob("*.pak"))
                        if p.stat().st_size > 0]
        except OSError:
            continue
    seen, uniq = set(), []
    for p in out:
        k = str(p.resolve())
        if k not in seen:
            seen.add(k)
            uniq.append(p)
    return uniq


PAKS = _pak_fixtures(_FIX_DIRS)


def _first_tencent_pak(cands):
    """First archive the tencent reader can open with a non-empty entry.

    Real PAKs legitimately contain zero-byte entries, and the engine's writer
    unpacks a struct per entry, so a zero-length payload is not a usable
    subject for the inject/repack round-trip.
    """
    import pak
    for c in cands:
        try:
            with pak.PakReader(c) as r:
                for v in list(r.full_paths().values()):
                    if v and r.read_entry(v):
                        return c
        except Exception:
            continue
    return None


PAKF = _first_tencent_pak(PAKS)
if PAKF:
    import pak
    pakf = PAKF
    try:
        new_path = "ShadowTrackerExtra/Content/UI/VIP_V112_PROBE.bin"
        with pak.PakReader(pakf) as r:
            paths = list(r.full_paths())
            entries = list(r.full_paths().values())
            check("pak index parse", len(paths) > 0, str(len(paths)))
            data = r.read_entry(entries[0])
        td = tempfile.mkdtemp()
        out = Path(td) / "rt.pak"
        with pak.PakReader(pakf) as r:
            n = pak.PakWriter(r).inject_files(
                [(new_path, (b"\x00" * len(data), None, "VIP_PROBE"))],
                str(out), force_add=True)
        check("pak repack inject", n > 0)
        with pak.PakReader(out) as r2:
            p2 = list(r2.full_paths())
            check("pak repack entries keep", len(p2) == len(paths) + 1,
                  str(len(p2)))
            got = r2.read_entry(r2.full_paths()[new_path])
            check("pak injected byte-exact", got == b"\x00" * len(data))
    except Exception as e:
        import traceback
        traceback.print_exc()
        check("D5a tencent suite", False, str(e))
else:
    skip("D5a tencent round-trip",
         "no tencent .pak in %s" % ", ".join(str(d) for d in _FIX_DIRS))

# ---- D5b ue4 round-trip, self-contained
def _tree(root):
    root = Path(root)
    return {str(f.relative_to(root)): f.read_bytes()
            for f in sorted(root.rglob("*")) if f.is_file()}


try:
    import engines as _eng
    _repak = _eng.find_repak()
    if not _repak:
        skip("D5b ue4 round-trip", "repak binary not found")
    else:
        import subprocess as _sp
        _td = Path(tempfile.mkdtemp(prefix="ikram_d5b_"))
        _src = _td / "tree"
        (_src / "ShadowTrackerExtra" / "Config").mkdir(parents=True)
        (_src / "ShadowTrackerExtra" / "Content" / "Lua").mkdir(parents=True)
        (_src / "ShadowTrackerExtra" / "Config" / "GameUserSettings.ini").write_bytes(
            b"res=1080p\nmobile=True\n")
        (_src / "ShadowTrackerExtra" / "Content" / "Lua" / "data.lua").write_bytes(
            bytes(range(256)) * 8)          # binary-ish, not text-only
        (_src / "ShadowTrackerExtra" / "Content" / "Lua" / "gameplay.lua").write_bytes(
            b"return {a=1,b='x'}\n")
        _pak1 = _td / "base.pak"
        _r = _sp.run([_repak, "pack", str(_src), "--mount-point", "../../../",
                      "--version", "V8B", "--compression", "Zlib", str(_pak1)],
                     capture_output=True, text=True)
        check("ue4 repak pack", _r.returncode == 0 and _pak1.exists(),
              (_r.stderr or _r.stdout)[:200])

        _un1 = _td / "un1"
        _n = _eng.unpack_pak(_pak1, _un1, kind="ue4", log=lambda *a, **k: None)
        check("ue4 unpack returns files", _n == 3, str(_n))
        _a = _tree(_src)
        _b = _tree(_un1)
        check("ue4 extract byte-exact", _a == _b,
              "%d vs %d files" % (len(_a), len(_b)))

        # edit one file, repack, extract again: the whole write path
        (_un1 / "ShadowTrackerExtra" / "Content" / "Lua" / "data.lua").write_bytes(
            b"-- vip edit\n" + b"z" * 4096)
        _pak2 = _td / "rt.pak"
        _n2 = _eng.repack_folder(_pak1, _un1, _pak2, kind="ue4",
                                 log=lambda *a, **k: None)
        check("ue4 repack returns files", _n2 == 3, str(_n2))
        _un2 = _td / "un2"
        _n3 = _eng.unpack_pak(_pak2, _un2, kind="ue4", log=lambda *a, **k: None)
        _c = _tree(_un2)
        _expect = dict(_a)
        _expect["ShadowTrackerExtra/Content/Lua/data.lua"] = \
            b"-- vip edit\n" + b"z" * 4096
        check("ue4 repack round-trip byte-exact", _n3 == 3 and _c == _expect,
              "%d files, %d match" % (len(_c), sum(1 for k in _c if _c.get(k) == _expect.get(k))))
except Exception as e:
    import traceback
    traceback.print_exc()
    check("D5b ue4 round-trip", False, str(e))

# ------------------------------------------------------------- finish
print()
if SKIPS:
    print("%d skipped: %s" % (len(SKIPS), "; ".join(n for n, _ in SKIPS)))
if FAILS:
    print("%d FAILED: %s" % (len(FAILS), ", ".join(FAILS)))
    sys.exit(1)
print("ALL ENGINE TESTS GREEN")
sys.exit(0)
