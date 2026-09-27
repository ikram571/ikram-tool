"""V122 release gate — 13 end-to-end scenarios.

Every scenario is a gate: if any of these fail, the release does not ship.
They are deliberately not the same assertions the unit suites make. A unit
suite proves a function behaves; a gate proves a user journey works on a
fresh machine, which is the only thing the ZIP can be judged on.

  E01  fresh install into a path with spaces
  E02  launch, banner version, menu render, clean exit
  E03  key gate: three wrong keys then out, input restored
  E04  key gate: closed stdin exits, never hangs
  E05  version check is bounded and fails silent
  E06  env repair visible, .bashrc idempotent, launchers stable
  E07  every menu action lands in the local log, logging never raises
  E08  pak round trip: build, unpack, repack, honest counts
  E09  costom pak: all-paths, one-folder, typed-path byte copy
  E10  inject: file lands at the requested path, reads back byte-exact
  E11  lua: python -> pyc -> python round trip
  E12  theme: numbers follow the theme, default Color byte-identical
  E13  ship hygiene: no beacon, no network, no absolute home path, clean zip

Run:  python3 tests/test_release_e2e.py
Exit 0 = all 13 gates green.
"""
import ast
import base64
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

RUNNER = ROOT / "tests" / "_runner.py"
REPAK = ROOT / "repak"
KEY = "8A75AFDF1C74AB55B79DC1DD4ABE4B01360A059D77F243EF4EFADA41A59D71A0"
VERSION = (ROOT / "VERSION").read_text(encoding="utf-8").strip()

FAILS = []
N = [0]


def check(name, cond, extra=""):
    N[0] += 1
    if cond:
        print("  ok   %s" % name)
    else:
        FAILS.append(name)
        print("  FAIL %s   %s" % (name, extra))


def flow(name, plan, expect_rc=0):
    """One fresh-process menu journey, mirroring how a user launches."""
    r = subprocess.run([sys.executable, str(RUNNER), name,
                        json.dumps(plan)],
                       capture_output=True, text=True, timeout=300)
    if expect_rc is not None and r.returncode != expect_rc:
        print(r.stdout[-2500:])
        print(r.stderr[-1500:])
    check("flow %s" % name, r.returncode == expect_rc,
          "rc=%s" % r.returncode)
    return r.stdout


def build_pak(dest_dir, name="base.pak"):
    """A real UE4 pak with real payloads, built by the bundled repak."""
    tree = dest_dir / "tree" / "ShadowTrackerExtra"
    (tree / "Config").mkdir(parents=True, exist_ok=True)
    (tree / "Content" / "Lua").mkdir(parents=True, exist_ok=True)
    (tree / "Config" / "GameUserSettings.ini").write_bytes(b"res=1080p\n")
    (tree / "Content" / "Lua" / "data.lua").write_bytes(b"return {a=1}\n")
    (tree / "Content" / "Lua" / "gameplay.lua").write_bytes(
        b"local t = {} for i=1,10 do t[i]=i end return t\n")
    pak = dest_dir / name
    r = subprocess.run([str(REPAK), "pack", str(dest_dir / "tree"),
                        "--mount-point", "../../../", "--version", "V8B",
                        "--compression", "Zlib", str(pak)],
                       capture_output=True, text=True)
    if r.returncode != 0 or not pak.is_file():
        raise SystemExit("repak failed: %s %s" % (r.stdout, r.stderr))
    return pak


def build_zip():
    """release.sh --build-only: the exact archive users would download."""
    r = subprocess.run(["bash", str(ROOT / "release.sh"), VERSION,
                        "--build-only"], capture_output=True, text=True,
                       timeout=900)
    if r.returncode != 0:
        print(r.stdout[-2000:], r.stderr[-1000:])
        return None
    for line in r.stdout.splitlines():
        if line.startswith("[*] ZIP:"):
            return Path(line.split("ZIP:", 1)[1].strip())
    return None


def _res(path):
    """RESULT dir name as the tree under test actually spells it."""
    import paths as p
    return Path(p.RESULT_DIR).name


# ------------------------------------------------------------------ E01
def _fix_env_in(home):
    """Run update._fix_env() against a fake $HOME, in a clean subprocess.

    _fix_env() resolves everything from Path.home(), so the only honest way
    to test it is to actually change the environment it reads.
    """
    r = subprocess.run([sys.executable, str(ROOT / "tests" / "_fixenv_probe.py")],
                       env={**os.environ, "HOME": str(home)},
                       capture_output=True, text=True, timeout=300)
    return r


def e01_install():
    """Build the release ZIP, install it offline into a spaced $HOME.

    TOOL_URL is install.sh's own override, so this exercises the real
    download+unpack path against the archive this repo actually produces,
    without touching the network and without touching the real home.
    """
    zp = build_zip()
    check("e01 the release zip is built", zp is not None and zp.is_file(),
          str(zp))
    if zp is None:
        return
    check("e01 the zip is named exactly IkramTool.zip",
          zp.name == "IkramTool.zip", zp.name)
    check("e01 the zip passes its own integrity test",
          subprocess.run(["unzip", "-tq", str(zp)],
                         capture_output=True).returncode == 0)

    td = Path(tempfile.mkdtemp(prefix="ikram e01 "))
    home = td / "My Home"                       # a space, on purpose
    home.mkdir()
    target = home / "Ikram_Tool"
    r = subprocess.run(["bash", str(ROOT / "install.sh")],
                       env={**os.environ, "HOME": str(home),
                            "TOOL_URL": zp.resolve().as_uri()},
                       capture_output=True, text=True, timeout=900)
    out = r.stdout + r.stderr
    if r.returncode != 0:
        print(out[-2500:])
    check("e01 install.sh exits 0", r.returncode == 0, out[-300:])
    eng = target / ".engine"
    check("e01 .engine holds the compiled core", (eng / "ikram.pyc").is_file())
    check("e01 the overlay shipped", (eng / "ikram_patch.py").is_file()
          and (eng / "vip_ui.py").is_file())
    check("e01 drop/ and result/ are siblings of .engine",
          (target / "drop" / "pak").is_dir() and (target / "result").is_dir())
    check("e01 the internal DROP/RESULT symlinks are in place",
          (eng / "DROP").is_symlink() and (eng / "RESULT").is_symlink())
    check("e01 the installed VERSION is the release version",
          (eng / "VERSION").read_text().strip() == VERSION,
          (eng / "VERSION").read_text().strip() if (eng / "VERSION").is_file()
          else "missing")
    # no tests, no analysis, no caches, no log, no beacon
    names = subprocess.run(["unzip", "-Z1", str(zp)],
                           capture_output=True, text=True).stdout.split()
    for junk in ("analysis", "tests", "__pycache__", "telemetry.log",
                 "telemetry.pyc", ".git"):
        check("e01 zip excludes %s" % junk,
              not any(n.rstrip("/").split("/")[-1] == junk for n in names),
              str([n for n in names if junk in n][:3]))
    check("e01 zip keeps the compiled chain",
          all(any(n.endswith(f) for n in names)
              for f in ("ikram.pyc", "pak.pyc", "engines.py", "vip_ui.py",
                        "update.py", "install.sh")))
    # the installed launchers must be valid bash with no absolute home path
    for cand in sorted(home.rglob("*")):
        if not cand.is_file() or cand.name not in ("ikram", ".bashrc"):
            continue
        txt = cand.read_text(encoding="utf-8", errors="replace")
        check("e01 %s kept no placeholder" % cand.name, "@@" not in txt)
        if cand.name == ".bashrc":
            check("e01 .bashrc points at the new path", "Ikram_Tool" in txt,
                  txt[-200:])
            continue
        sr = subprocess.run(["bash", "-n", str(cand)],
                            capture_output=True, text=True)
        check("e01 %s is valid bash" % cand.name, sr.returncode == 0,
              sr.stderr[:200])
        check("e01 %s hardcodes no home path" % cand.name,
              "/data/data/" not in txt)


# ------------------------------------------------------------------ E02
def e02_launch():
    """Banner, folder status, clean exit — a fresh process, as a user runs it."""
    flow("gate_launch", {
        "steps": [{"script": ["0"],
                   "expect": {"brand": ["IkramTool", VERSION.lower()],
                              "status": ["DROP/pak/", "(empty)"],
                              "exit": ["Thanks for using IkramTool"]}}]})
    import json as _json
    meta = _json.loads((ROOT / "ikram_key.json").read_text())
    check("e02 ikram_key.json version agrees with VERSION",
          meta["version"] == VERSION, "%s vs %s" % (meta["version"], VERSION))
    check("e02 the activation hash is intact",
          len(meta["key_hash"]) == 64, meta["key_hash"][:16])


# ------------------------------------------------------------------ E03 / E04
PROBE = ROOT / "tests" / "_keygate_probe.py"


def _gate(*args):
    r = subprocess.run([sys.executable, str(PROBE)] + [str(a) for a in args],
                       capture_output=True, text=True, timeout=120)
    if "###VERDICT###" not in r.stdout:
        return {"ok": "NO-VERDICT", "hung": True, "raw": r.stdout + r.stderr}
    return json.loads(r.stdout.split("###VERDICT###")[-1])


def e03_three_strikes():
    v = _gate('["nope", "nope", "nope", "nope", "nope"]')
    check("e03 wrong keys do not hang", not v["hung"], json.dumps(v)[:300])
    check("e03 exactly 3 invalid-key messages", v["invalid"] == 3,
          str(v["invalid"]))
    check("e03 the prompt is redrawn exactly 3 times", v["prompts"] == 3,
          str(v["prompts"]))
    check("e03 a 4th attempt is never asked", v["prompts"] <= 3)
    check("e03 it leaves the tool", v["ok"] is False, repr(v["ok"]))
    check("e03 the exit message is shown", v["too_many"] is True)
    check("e03 builtins.input is restored", v["input_restored"] is True)
    check("e03 the console is restored", v["console_restored"] is True)

    q = _gate('["nope", "nope", "quit"]')
    check("e03 quit is not a strike", q["invalid"] == 2, str(q["invalid"]))
    check("e03 quit leaves quietly", q["ok"] is False and not q["too_many"])

    a = _gate("[]", "noeof", "accept")
    check("e03 the right key gets in", a["ok"] is True, repr(a["ok"]))
    check("e03 a good key asks nothing", a["invalid"] == 0)


def e04_eof():
    v = _gate("[]", "eof")
    check("e04 closed stdin does not hang", not v["hung"], json.dumps(v)[:300])
    check("e04 closed stdin leaves the tool", v["ok"] is False, repr(v["ok"]))
    check("e04 it does not count as a bad key", v["invalid"] == 0,
          str(v["invalid"]))
    check("e04 input restored on the EOF path", v["input_restored"] is True)
    w = _gate('["nope"]', "eof")
    check("e04 stdin dying mid-prompt still exits", not w["hung"])
    check("e04 stdin dying mid-prompt restores input",
          w["input_restored"] is True)


# ------------------------------------------------------------------ E05
def e05_version_check():
    upd = (ROOT / "update.py").read_text(encoding="utf-8")
    m = re.search(r"VERSION_CHECK_TIMEOUT\s*=\s*(\d+)", upd)
    check("e05 version timeout is 5s", bool(m) and int(m.group(1)) == 5,
          m.group(1) if m else "not set")
    check("e05 the download itself still has a real timeout", "timeout=120" in upd)
    spec = importlib.util.spec_from_file_location("upd_probe5", ROOT / "update.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.API = "https://127.0.0.1:9/nope.json"      # a host that never answers
    t0 = time.time()
    ver = mod.latest_remote()
    dt = time.time() - t0
    check("e05 unreachable API returns None, not an exception", ver is None,
          repr(ver))
    check("e05 unreachable API bounded (%.1fs <= 8s)" % dt, dt <= 8.0,
          "took %.1fs" % dt)
    check("e05 the release asset name is unchanged", mod.ZIP_NAME == "IkramTool.zip",
          mod.ZIP_NAME)


# ------------------------------------------------------------------ E06
def e06_env_repair():
    td = Path(tempfile.mkdtemp(prefix="ikram e06 "))
    home = td / "home"
    home.mkdir()
    r = _fix_env_in(home)
    out = r.stdout + r.stderr
    check("e06 _fix_env exits 0", r.returncode == 0, out[-400:])
    bashrc = home / ".bashrc"
    check("e06 .bashrc created when absent", bashrc.is_file())
    first = bashrc.read_text()
    check("e06 repair announces itself", "ENV_REPAIR" in out, out[-300:])
    r2 = _fix_env_in(home)
    check("e06 second run leaves .bashrc identical",
          bashrc.read_text() == first,
          "%d -> %d" % (len(first), len(bashrc.read_text())))
    check("e06 no duplicate launcher block", first.count("ikram()") <= 1,
          str(first.count("ikram()")))
    check("e06 update.py keeps no daemon machinery",
          "threading" not in (ROOT / "update.py").read_text(encoding="utf-8")
          or "Thread(" not in (ROOT / "update.py").read_text(encoding="utf-8"))


# ------------------------------------------------------------------ E07
def e07_telemetry():
    td = Path(tempfile.mkdtemp(prefix="ikram e07 "))
    spec = importlib.util.spec_from_file_location("tel_probe", ROOT / "telemetry.py")
    t = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(t)
    log = td / "telemetry.log"
    t._LOG = log
    t.send_login()
    t.send_event("pak.unpack", file="x.pak", status="OK", engine="ue4", files=3)
    t.send_event("lua.compile", file="a.lua")
    t.send_error(RuntimeError("boom"), extra="pak.repack")
    body = log.read_text()
    check("e07 login recorded", "login" in body, body[:200])
    check("e07 pak.unpack recorded", "pak.unpack" in body)
    check("e07 the engine column is filled", "ue4" in body, body[:300])
    check("e07 lua.compile recorded", "lua.compile" in body)
    check("e07 error carries type and message",
          "RuntimeError" in body and "boom" in body, body[-200:])
    check("e07 one write per action",
          len([l for l in body.splitlines() if l.strip()]) == 4,
          str(len(body.splitlines())))
    check("e07 every line is a single bracketed row",
          all(l.startswith("[") and l.endswith("]") and "\n" not in l
              for l in body.splitlines() if l.strip()), body[:200])

    # rotation is bounded once the file passes MAX_BYTES
    t._LOG = td / "rot.log"
    t.MAX_BYTES, t.KEEP_LINES = 4096, 20
    for i in range(3000):
        t.send_event("flood", file="f%d" % i)
    size = t._LOG.stat().st_size
    body = t._LOG.read_text()
    check("e07 rotation keeps the file bounded (%.1fkB)" % (size / 1024),
          size <= 4 * 4096, "%d bytes" % size)
    check("e07 the newest event is still the newest row",
          body.splitlines()[-1].endswith("]") and "f2999" in body.splitlines()[-1],
          body.splitlines()[-1][:120])
    check("e07 old rows are dropped", "f0]" not in body and
          "f10]" not in body, "oldest rows survived rotation")

    # a field can never break the one-row-per-action format
    t._LOG = td / "inject.log"
    t.send_event("pak.unpack", file="a\nb\r\nc")
    t.send_event("pak.unpack", file="x" * 5000)
    rows = t._LOG.read_text().splitlines()
    check("e07 newline injection cannot forge a row", len(rows) == 2, str(rows))
    check("e07 an overlong field is truncated", max(len(r) for r in rows) < 1000,
          str(max(len(r) for r in rows)))

    # logging must never raise, whatever the filesystem says
    t._LOG = td / "nope" / "deep" / "telemetry.log"
    try:
        t.send_event("x", file="y")
        t.send_error(ValueError("z"))
        check("e07 logging never raises", True)
    except Exception as e:
        check("e07 logging never raises", False, repr(e))
    check("e07 app_version reads the shipped VERSION",
          t.app_version() == VERSION, "%r != %r" % (t.app_version(), VERSION))
    check("e07 device_name is non-empty", bool(t.device_name()))


# ------------------------------------------------------------------ E08
def e08_roundtrip():
    td = Path(tempfile.mkdtemp(prefix="ikram e08 "))
    pak = build_pak(td)
    import engines
    out = td / "un"
    n = engines.unpack_pak(pak, out, kind="ue4", log=lambda *a, **k: None)
    check("e08 unpack counts the real entries", n == 3, str(n))
    got = {str(f.relative_to(out)): f.read_bytes()
           for f in out.rglob("*") if f.is_file()}
    check("e08 extract is byte-exact",
          got.get("ShadowTrackerExtra/Config/GameUserSettings.ini") == b"res=1080p\n",
          str(sorted(got)))
    edited = out / "ShadowTrackerExtra" / "Content" / "Lua" / "data.lua"
    edited.write_bytes(b"-- gate edit\nreturn {b=2}\n")
    rt = td / "rt.pak"
    n2 = engines.repack_folder(pak, out, rt, kind="ue4",
                               log=lambda *a, **k: None)
    check("e08 repack count matches the written pak", n2 == 3, str(n2))
    back = td / "back"
    n3 = engines.unpack_pak(rt, back, kind="ue4", log=lambda *a, **k: None)
    check("e08 repacked pak re-reads", n3 == 3, str(n3))
    check("e08 the edit survived the round trip",
          (back / "ShadowTrackerExtra" / "Content" / "Lua" / "data.lua")
          .read_bytes() == b"-- gate edit\nreturn {b=2}\n")
    check("e08 untouched files unchanged",
          (back / "ShadowTrackerExtra" / "Content" / "Lua" / "gameplay.lua")
          .read_bytes()
          == b"local t = {} for i=1,10 do t[i]=i end return t\n")


# ------------------------------------------------------------------ E09
def e09_costom():
    """The Costom PAK contract: declared names, zero bodies, or real bytes.

    engines.costom_pak() returns the number of declared paths, which is what
    menus.py reports to the user, so that is what is asserted here.
    """
    td = Path(tempfile.mkdtemp(prefix="ikram e09 "))
    pak = build_pak(td)
    import engines
    allp = engines.list_pak_paths(pak, log=lambda *a, **k: None)
    check("e09 the template declares 3 paths", len(allp) == 3, str(allp))

    out = td / "all.pak"
    n = engines.costom_pak(pak, out, allp, aes_key=KEY,
                           log=lambda *a, **k: None, copy=False)
    check("e09 all-paths reports 3", n == 3, str(n))
    got = engines.list_pak_paths(out, log=lambda *a, **k: None)
    check("e09 all-paths declares every name", sorted(got) == sorted(allp),
          str(got))
    un = td / "un_all"
    engines.unpack_pak(out, un, kind="ue4", aes_key=KEY,
                       log=lambda *a, **k: None)
    bodies = {str(f.relative_to(un)): f.stat().st_size
              for f in un.rglob("*") if f.is_file()}
    check("e09 all-paths writes zero-byte bodies",
          bodies and all(v == 0 for v in bodies.values()), str(bodies))

    target = "ShadowTrackerExtra/Content/Lua/data.lua"
    check("e09 the target path exists in the template", target in allp, str(allp))
    one = td / "one.pak"
    n2 = engines.costom_pak(pak, one, [target], aes_key=KEY,
                            log=lambda *a, **k: None, copy=False)
    check("e09 one-folder reports 1", n2 == 1, str(n2))
    check("e09 one-folder declares only that name",
          engines.list_pak_paths(one, log=lambda *a, **k: None) == [target])

    copied = td / "copy.pak"
    n3 = engines.costom_pak(pak, copied, [target], aes_key=KEY,
                            log=lambda *a, **k: None, copy=True)
    check("e09 typed-path reports 1", n3 == 1, str(n3))
    un2 = td / "un_copy"
    engines.unpack_pak(copied, un2, kind="ue4", aes_key=KEY,
                       log=lambda *a, **k: None)
    check("e09 typed-path copies the real bytes",
          (un2 / target).read_bytes() == b"return {a=1}\n",
          repr((un2 / target).read_bytes()[:40]))


# ------------------------------------------------------------------ E10
def e10_inject():
    td = Path(tempfile.mkdtemp(prefix="ikram e10 "))
    pak = build_pak(td)
    victim = td / "payload.bin"
    victim.write_bytes(bytes(range(256)) * 40)
    import engines
    out = td / "inj.pak"
    # UE4 inject goes through repak: stage the tree, add one file, repack
    tree = td / "tree2"
    engines.unpack_pak(pak, tree, kind="ue4", log=lambda *a, **k: None)
    target = tree / "ShadowTrackerExtra" / "Content" / "Lua" / "payload.bin"
    target.write_bytes(victim.read_bytes())
    r = subprocess.run([str(REPAK), "pack", str(tree), "--mount-point", "../../../",
                        "--version", "V8B", "--compression", "Zlib", str(out)],
                       capture_output=True, text=True)
    check("e10 repak accepted the injected tree", r.returncode == 0,
          r.stderr[:200])
    back = td / "back"
    n = engines.unpack_pak(out, back, kind="ue4", log=lambda *a, **k: None)
    check("e10 injected file is in the pak", n == 4, str(n))
    check("e10 injected file reads back byte-exact",
          (back / "ShadowTrackerExtra" / "Content" / "Lua" / "payload.bin")
          .read_bytes() == victim.read_bytes())
    check("e10 original entries still readable",
          (back / "ShadowTrackerExtra" / "Config" / "GameUserSettings.ini")
          .read_bytes() == b"res=1080p\n")


# ------------------------------------------------------------------ E11
def e11_lua():
    code = base64.b64encode(
        b"def add(a, b):\n"
        b"    if a > b:\n"
        b"        return a\n"
        b"    return b\n"
        b"print(add(1, 3))\n").decode()
    flow("gate_lua", {
        "fixtures": {"DROP/lua/helper.py": {"b64_text": code}},
        "exists": ["RESULT/lua/helper.pyc"],
        "steps": [
            {"script": ["2", "1", "", "0", "0"],
             "expect": {"compile": ["Compiled"]}},
            {"script": ["2", "2", "", "0", "0"],
             "expect": {"decompile": ["Decompiled"]}},
        ]})


# ------------------------------------------------------------------ E12
def e12_theme():
    from box_engine import _DEFAULT_NUM_CYCLE, vip_num_cycle
    from theme_engine import Theme, THEMES
    default = vip_num_cycle(Theme("Original Color")._pal, "Original Color")
    check("e12 the default cycle is byte-for-byte the historical one",
          default == {"0": 183, "1": 45, "2": 51, "3": 39, "4": 118, "5": 119},
          str(default))
    check("e12 the pinned default equals the default cycle",
          default == _DEFAULT_NUM_CYCLE)
    pink = vip_num_cycle(Theme("Neon Pink")._pal, "Neon Pink")
    check("e12 another theme numbers from its own palette", pink != default,
          str(pink))
    check("e12 every theme yields all six digits",
          all(set(vip_num_cycle(Theme(t)._pal, t)) == set("012345")
              for t in THEMES))
    broken = []
    for t in THEMES:
        try:
            box = Theme(t)
            if not box.apply("x", "menu"):
                broken.append(t)
        except Exception as e:                       # noqa: BLE001
            broken.append("%s:%s" % (t, e))
    check("e12 all %d themes render a menu role" % len(THEMES), not broken,
          str(broken[:3]))


# ------------------------------------------------------------------ E13
def e13_hygiene():
    """Nothing private, nothing networked, and the archive is clean."""
    check("e13 the beacon is gone", not (ROOT / "telemetry.pyc").exists())
    shipped = ["ikram_patch.py", "update.py", "engines.py", "menus.py",
               "vip_ui.py", "telemetry.py", "box_engine.py", "theme_engine.py",
               "paths.py", "univ.py", "install.sh", "run.sh", "release.sh"]
    # update.py is the updater: it must reach github. Nothing else may.
    may_network = {"update.py"}
    banned = {"socket", "urllib", "urllib.request", "requests", "http",
              "http.client", "smtplib", "telnetlib", "aiohttp", "ftplib"}
    for name in shipped:
        f = ROOT / name
        if not f.is_file():
            continue
        text = f.read_text(encoding="utf-8", errors="replace")
        if name.endswith(".py"):
            tree = ast.parse(text)
            mods = set()
            for n in ast.walk(tree):
                if isinstance(n, ast.Import):
                    mods |= {a.name for a in n.names}
                elif isinstance(n, ast.ImportFrom) and n.module:
                    mods.add(n.module)
            hits = {m for m in mods if m.split(".")[0] in banned or m in banned}
            if name in may_network:
                check("e13 %s is the only module that fetches" % name, True)
                continue
            check("e13 %s reaches no network" % name, not hits, str(hits))
            # the beacon must not be loaded from live code (docstrings are
            # allowed to explain that it is gone)
            docs = set()
            for n in ast.walk(tree):
                if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                  ast.AsyncFunctionDef)):
                    if (n.body and isinstance(n.body[0], ast.Expr)
                            and isinstance(n.body[0].value, ast.Constant)
                            and isinstance(n.body[0].value.value, str)):
                        docs.add(id(n.body[0].value))
            live = [n.value for n in ast.walk(tree)
                    if isinstance(n, ast.Constant) and isinstance(n.value, str)
                    and id(n) not in docs]
            check("e13 %s does not load the beacon" % name,
                  not any("telemetry.pyc" in lit for lit in live))
        else:
            check("e13 %s has no absolute home path" % name,
                  "/data/data/com.termux/files/home" not in text)
    # the updater must stay timeout-bounded wherever it fetches
    up = (ROOT / "update.py").read_text(encoding="utf-8")
    check("e13 every urlopen in the updater is bounded",
          all("timeout=" in ln for ln in up.splitlines()
              if "urlopen" in ln), "an unbounded fetch is in update.py")

    # runtime artifacts must never be committed, and never ship
    tracked = subprocess.run(["git", "ls-files"], cwd=str(ROOT),
                             capture_output=True, text=True).stdout.split()
    for junk in ("telemetry.log", "__pycache__", "ljd.zip"):
        check("e13 %s is not tracked by git" % junk,
              not any(junk in t for t in tracked))
    gi = (ROOT / ".gitignore").read_text(encoding="utf-8")
    for junk in ("telemetry.log", "__pycache__", "*.zip"):
        check("e13 .gitignore covers %s" % junk, junk in gi, gi[:200])

    zp = build_zip()          # always judge the archive that would be published
    check("e13 the release zip rebuilds for inspection", zp is not None)
    if zp is not None:
        names = [n for n in subprocess.run(["unzip", "-Z1", str(zp)],
                                           capture_output=True,
                                           text=True).stdout.split() if n]
        for junk in ("analysis", "tests", "__pycache__", "telemetry.log",
                     "telemetry.pyc", ".git", "release.sh", ".gitignore",
                     "README.md", "ljd.zip", "Memory.md"):
            check("e13 zip excludes %s" % junk,
                  not any(n.rstrip("/").split("/")[-1] == junk for n in names),
                  str([n for n in names if junk in n][:3]))
        check("e13 zip has no leftover .bak_ files",
              not any(".bak_" in n for n in names))
        check("e13 zip ships the compiled chain",
              all(any(n.endswith(f) for n in names)
                  for f in ("ikram.pyc", "pak.pyc", "ue4.pyc", "engines.py",
                            "vip_ui.py", "telemetry.py", "update.py")))
        check("e13 zip ships the native decompilers",
              all(any(n.endswith(f) for n in names)
                  for f in ("repak", "unluac.jar", "cfr.jar", "unluac_rs")))
        check("e13 zip has no dotfiles", not any(n.startswith(".") for n in names),
              str([n for n in names if n.startswith(".")][:5]))
        check("e13 zip ships no documentation",
              not any(n.endswith(".md") for n in names),
              str([n for n in names if n.endswith(".md")][:5]))


# ------------------------------------------------------------------ main
def main():
    if not REPAK.is_file():
        raise SystemExit("repak missing: the PAK gates cannot run")
    gates = [e01_install, e02_launch, e03_three_strikes, e04_eof,
             e05_version_check, e06_env_repair, e07_telemetry, e08_roundtrip,
             e09_costom, e10_inject, e11_lua, e12_theme, e13_hygiene]
    for i, g in enumerate(gates, 1):
        print("\n=== E%02d %s" % (i, g.__name__[1:]))
        try:
            g()
        except Exception as e:
            import traceback
            traceback.print_exc()
            check("E%02d %s completed" % (i, g.__name__[1:]), False, str(e))
    print("\n%d assertions, %d failed" % (N[0], len(FAILS)))
    if FAILS:
        for f in FAILS:
            print("  FAILED %s" % f)
        sys.exit(1)
    print("ALL 13 RELEASE GATES GREEN")
    sys.exit(0)


if __name__ == "__main__":
    main()
