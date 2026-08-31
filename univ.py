# -*- coding: utf-8 -*-
"""Unified engine wrapper — my main entry used by ikram.pyc via `import univ`.

Loads the original `univ.pyc` for all non-Lua engines and overlays the
BGMI-aware Lua pipeline (mega_lua) so Decompile/Compile handle real game
bytecode with readable output and game-ready recompilation.

Keeps the exact API surface ikram.pyc calls:
    detect(src) -> str
    decompile_any(src, out, progress=None) -> (ok, msg)
    decompile_multi_engines(src, out_root, progress=None) -> [(label, ok, out, msg)]
    compile_any(src, out, progress=None) -> (ok, msg)
plus every other attribute of the original univ module.

Implementation detail: the legacy `univ.pyc` sits in the same directory.
Python resolves `univ.py` before `univ.pyc`, so this file wins. We load the
original code via importlib and re-export everything under _legacy, then
return our pipeline for the Lua calls.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import mega_lua as _mega

_TOOL_DIR = Path(__file__).resolve().parent
_PYC = _TOOL_DIR / "univ.pyc"


def _load_legacy():
    """Import the original univ.pyc as a private module `_univ_legacy`."""
    if "_univ_legacy" in sys.modules:
        return sys.modules["_univ_legacy"]
    spec = importlib.util.spec_from_file_location("_univ_legacy", str(_PYC))
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_univ_legacy"] = mod
    try:
        spec.loader.exec_module(mod)
    except Exception:
        sys.modules.pop("_univ_legacy", None)
        raise
    return mod


_legacy = None
try:
    _legacy = _load_legacy()
except Exception:
    _legacy = None

# ---- re-export every legacy attribute so nothing breaks -----------------
if _legacy is not None:
    for _n in dir(_legacy):
        if _n.startswith("__") and _n not in ("__builtins__",):
            continue
        globals()[_n] = getattr(_legacy, _n)

# ---- public callables ikram.pyc relies on -------------------------------


def detect(src):
    """Classify a file. Lua handled by mega_lua, else legacy detect."""
    kind = _mega.detect_lua(src)
    if kind != "unknown":
        return kind
    if _legacy is not None:
        try:
            return _legacy.detect(src)
        except Exception:
            pass
    return kind


def decompile_any(src, out, progress=None):
    """Decompile a Lua file to readable source; returns (ok, msg)."""
    src = Path(src)
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    kind = detect(src)
    if kind not in ("Lua source", "Lua 5.3", "LuaJIT", "Lua", "Lua 5.3 (encrypted)"):
        if _legacy is not None:
            return _legacy.decompile_any(src, out, progress)
        return False, "unsupported"
    results = decompile_multi_engines(src, out.parent, progress)
    for _l, ok, p, _m in results:
        if ok and p and str(p).endswith("_GAME.lua"):
            data = p.read_bytes()
            out.write_bytes(data)
            return True, str(p)
    return results[0][1], results[0][3] if results else (False, "decompile failed")


def decompile_multi_engines(src, out_root, progress=None):
    """Return [(label, ok, out_path, msg)] for all produced artifacts."""
    src = Path(src)
    out_root = Path(out_root)
    if str(src).lower().endswith((".py", ".pyc", ".java", ".class", ".dex")):
        if _legacy is not None:
            return _legacy.decompile_multi_engines(src, out_root, progress)
        return [("Legacy", False, out_root, "unsupported")]
    kind = detect(src)
    if kind in ("Lua source", "Lua 5.3", "LuaJIT", "Lua", "Lua 5.3 (encrypted)"):
        return _mega.decompile_bgmi(src, out_root, progress)
    if _legacy is not None:
        return _legacy.decompile_multi_engines(src, out_root, progress)
    return [("Legacy", False, out_root, "unsupported")]


def compile_any(src, out, progress=None):
    """Compile readable Lua -> BGMI bytecode; returns (ok, msg)."""
    src = Path(src)
    out = Path(out)
    kind = detect(src)
    if kind in ("Lua source", "Lua 5.3", "LuaJIT", "Lua"):
        return _mega.compile_bgmi(src, out, progress)
    if _legacy is not None:
        return _legacy.compile_any(src, out, progress)
    return False, "unsupported"


# Compat shim: legacy `compile_lua(src, out, version, strip)` compiles Lua
# source to STANDARD bytecode at `out` and returns '' on success / err string.
# lua_protect.protect_compile then converts std -> BGMI itself.
def compile_lua(src, out, version="5.3", strip=False) -> str:
    try:
        text = Path(src).read_text(encoding="utf-8", errors="replace")
        std = _mega._compile_std(text)
        out = Path(out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(std)
        return ""
    except Exception as e:
        return str(e)
