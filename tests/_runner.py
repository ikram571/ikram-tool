"""Subprocess scenario runner for IkramTool V112 flow tests.

Each `python3 tests/_runner.py <name> '<json plan>'` is a FRESH process:
  - isolated temp tree (DROP/RESULT remapped via the ikram AND paths modules)
  - import-captured console redirected per-boot to a StringIO
  - key_lock / welcome_splash patched out
  - scripted inputs fed through Vip._ask AND builtins.input
The plan is JSON:
  {"script": [...], "fixtures": {"DROP/pak/core.pak": "/abs/source"},
   "inject": true, "steps": [{"script": [...], "expect": [substr...]}]}

Exit 0 = all checks ok; every check prints one line:
  OK   <name>
  FAIL <name> <extra>
"""
import io
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_IMPBUF = io.StringIO()
sys.stdout = _IMPBUF  # rich Console() binds file=sys.stdout at import time

import ikram_patch  # noqa: E402  (loads ikram.pyc + patched overlay + engines)

sys.stdout = sys.__stdout__

import paths as _paths  # noqa: E402
from rich.console import Console  # noqa: E402
from theme_engine import strip_ansi  # noqa: E402

FAILS = []


def check(name, cond, extra=""):
    if cond:
        print("OK   %s" % name)
    else:
        FAILS.append(name)
        print("FAIL %s  %s" % (name, extra))


class Feeder:
    def __init__(self, script):
        self.it = iter(str(s) for s in script)

    def next(self):
        try:
            return next(self.it)
        except StopIteration:
            return "0"


def build_env():
    home = Path(tempfile.mkdtemp(prefix="ikram_scn_"))
    base = home / "tool"
    base.mkdir(parents=True, exist_ok=True)
    remap_base = Path(_paths.BASE_DIR).resolve()
    paths_real = {n: getattr(_paths, n)
                  for n in dir(_paths)
                  if isinstance(getattr(_paths, n, None), Path)}
    for mod in (ikram_patch.ikram,):
        for name in dir(mod):
            try:
                v = getattr(mod, name)
            except Exception:
                continue
            if isinstance(v, Path):
                rp = v.resolve()
                if str(rp) == str(remap_base) or str(rp).startswith(
                        str(remap_base) + os.sep):
                    setattr(mod, name, base / rp.relative_to(remap_base))
    for name, v in paths_real.items():
        rp = v.resolve()
        if str(rp) == str(remap_base) or str(rp).startswith(
                str(remap_base) + os.sep):
            setattr(_paths, name, base / rp.relative_to(remap_base))
    global _DROP_ROOT, _RESULT_ROOT
    drop_root = _paths.DROP_DIR
    result_root = _paths.RESULT_DIR
    if (not str(drop_root).startswith(str(base)) or
            not str(result_root).startswith(str(base))):
        print("FATAL: DROP/RESULT not remapped under base: %s | %s" %
              (drop_root, result_root))
        sys.exit(2)
    _DROP_ROOT = drop_root
    _RESULT_ROOT = result_root
    mod = ikram_patch.ikram
    mod.DROP = drop_root
    mod.RESULT = result_root
    for sub in ("pak", "lua", "inject"):
        (drop_root / sub).mkdir(parents=True, exist_ok=True)
    for sub in ("extracted", "injected", "lua", "processed",
                "CostomPak", "Repacked"):
        (result_root / sub).mkdir(parents=True, exist_ok=True)
    return home, base, drop_root, result_root


_DROP_ROOT = None
_RESULT_ROOT = None


def _rel(base, rel):
    """Map a plan-relative key onto the remapped layout of the tree under
    test. install layout keys are lowercase drop/result; release layout keys
    are uppercase DROP/RESULT; the module constants carry the truth."""
    if rel.startswith("DROP/"):
        return _DROP_ROOT / rel[len("DROP/"):]
    if rel.startswith("RESULT/"):
        return _RESULT_ROOT / rel[len("RESULT/"):]
    return base / rel


def stage_fixtures(base, fixtures):
    import base64 as _b64
    for rel, src in (fixtures or {}).items():
        if isinstance(src, dict):
            data = _b64.b64decode(src["b64_text"])
        else:
            data = Path(src).read_bytes()
        p = _rel(base, rel)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)


def boot(base, script):
    import builtins
    from vip_ui import Vip
    ik = ikram_patch.ikram
    ik.key_lock = lambda: True
    ik.welcome_splash = lambda: None
    buf = io.StringIO()
    fed = Feeder(script)
    sys.stdout = buf
    ik.console = Console(file=buf, width=100, legacy_windows=False)
    v = Vip(ikram=ik, stream=buf)
    v._ask = lambda prompt: fed.next()
    old_input = builtins.input
    builtins.input = lambda prompt="": fed.next()
    try:
        v.run()
    finally:
        builtins.input = old_input
        sys.stdout = sys.__stdout__
    return strip_ansi(buf.getvalue())


def run_plan(plan):
    home, base, drop_root, result_root = build_env()
    stage_fixtures(base, plan.get("fixtures"))
    out_all = ""

    if plan.get("inject"):
        # pick a basename appearing exactly once inside the layout DROP/pak
        # so mode ALL resolves automatically without a folder-picker prompt
        import pak as _pak
        paks = sorted((drop_root / "pak").glob("*.pak"))
        if paks:
            with _pak.PakReader(paks[0]) as r:
                fmap = r.full_paths()
            by_name = {}
            for pth in fmap:
                by_name.setdefault(Path(pth).name, []).append(pth)
            target = None
            for name, plist in by_name.items():
                if len(plist) == 1 and not name.startswith("."):
                    target = name
                    break
            if target:
                (drop_root / "inject" / target).write_bytes(
                    b"V112-INJECT-PROBE\n")
            plan["_inject_target"] = target

    for step in plan["steps"]:
        out = boot(base, step["script"])
        out_all += out
        for name, substrs in step.get("expect", {}).items():
            check(name, all(s in out for s in substrs))

    for rel in plan.get("exists", []):
        check("exists %s" % rel, _rel(base, rel).exists())
    for rel in plan.get("gone", []):
        check("gone %s" % rel, not _rel(base, rel).exists())
    for rel, want in plan.get("content", {}).items():
        p = _rel(base, rel)
        got = p.read_bytes() if p.is_file() else None
        check("content %s" % rel, got == want)

    if plan.get("inject") and plan.get("_inject_target"):
        tgt = plan["_inject_target"]
        pak = result_root / "injected" / "core.pak"
        if pak.is_file():
            import pak as _pak
            with _pak.PakReader(pak) as r:
                got = r.read_entry(r.full_paths()[tgt])
            okc = got == b"V112-INJECT-PROBE\n"
            check("inject byte-exact", okc)

    # keep a trace for debugging (temp dirs are cleaned by parent on pass)
    (home / "trace.txt").write_text(out_all)

    if FAILS:
        print("FAILED_SCENARIO %s" % (FAILS,))
        sys.exit(1)
    print("SCENARIO_OK")


if __name__ == "__main__":
    name = sys.argv[1]
    plan = json.loads(sys.argv[2])
    print("# scenario: %s" % name)
    run_plan(plan)