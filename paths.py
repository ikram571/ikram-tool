"""IkramTool V112 — Path System (Section G frozen, matches V111 exactly).

The ONLY place in this package with path strings. Every folder in the
tool is a constant here. Inputs always DROP/, outputs always RESULT/,
paths are never asked, never typed, never change.

Original V111 paths (LOWERCASE DROP subfolders, MIXED-CASE RESULT names —
these exact spellings are frozen and must never be "fixed"):

  DROP/pak        <-  .pak files to process
  DROP/lua        <-  .lua / .luac files to process
  DROP/inject     <-  files to inject into a pak

  RESULT/extracted   unpacked pak trees
  RESULT/injected    paks after injection
  RESULT/lua         all lua results (compile/decompile/...)
  RESULT/processed   unpack secondary sidecars (option-1 auto-process)
  RESULT/CostomPak   custom paks        (NOTE the original spelling)
  RESULT/Repacked    repacked paks      (NOTE the original spelling)
"""
import shutil
import time
from pathlib import Path

_F = Path(__file__).resolve().parent

# Engine kaha se chal raha hai:
#   - .engine/  -> installed layout: DROP/RESULT parent me (drop/result lowercase)
#   - repo root -> dev layout: DROP/RESULT yahin (uppercase, release layout)
if _F.name == ".engine":
    BASE_DIR = _F.parent
    _DROP = BASE_DIR / "drop"
    _RESULT = BASE_DIR / "result"
else:
    BASE_DIR = _F
    _DROP = BASE_DIR / "DROP"
    _RESULT = BASE_DIR / "RESULT"

DROP_PAK = _DROP / "pak"
DROP_LUA = _DROP / "lua"
DROP_INJECT = _DROP / "inject"

RESULT_EXTRACTED = _RESULT / "extracted"
RESULT_INJECTED = _RESULT / "injected"
RESULT_LUA = _RESULT / "lua"
RESULT_PROCESSED = _RESULT / "processed"
RESULT_CUSTOMPAK = _RESULT / "CostomPak"
RESULT_REPACKED = _RESULT / "Repacked"

DROP_DIR = _DROP
RESULT_DIR = _RESULT

ALL_DIRS = (
    DROP_PAK, DROP_LUA, DROP_INJECT,
    RESULT_EXTRACTED, RESULT_INJECTED,
    RESULT_LUA, RESULT_PROCESSED,
    RESULT_CUSTOMPAK, RESULT_REPACKED,
)

_FOLDERS = {
    DROP_PAK: "DROP/pak",
    DROP_LUA: "DROP/lua",
    DROP_INJECT: "DROP/inject",
    RESULT_EXTRACTED: "RESULT/extracted",
    RESULT_INJECTED: "RESULT/injected",
    RESULT_LUA: "RESULT/lua",
    RESULT_PROCESSED: "RESULT/processed",
    RESULT_CUSTOMPAK: "RESULT/CostomPak",
    RESULT_REPACKED: "RESULT/Repacked",
}


def ensure_dirs():
    """Create all folders if missing. Raises OSError on permission."""
    for d in ALL_DIRS:
        d.mkdir(parents=True, exist_ok=True)


def folder_label(d):
    return _FOLDERS.get(Path(d), str(Path(d)))


def list_drop(folder, exts=()):
    """Files in a DROP folder. exts lowercase tuple or ().
    () = every file."""
    folder = Path(folder)
    if not folder.is_dir():
        return []
    out = []
    for p in sorted(folder.iterdir()):
        if p.is_file() and (p.name.startswith(".") is False):
            if not exts or p.suffix.lower() in exts:
                out.append(p)
    out.sort(key=lambda p: p.name.lower())
    return out


def count_dir(folder):
    """(file_count, total_bytes) for a folder tree."""
    folder = Path(folder)
    if not folder.is_dir():
        return 0, 0
    n = 0
    total = 0
    for p in folder.rglob("*"):
        if p.is_file():
            n += 1
            try:
                total += p.stat().st_size
            except OSError:
                pass
    return n, total


def unique_path(path, avoid=None):
    """Original never-overwrite rule (Section G): if the target exists,
    append ' (1)', ' (2)' ... to the *stem* (space + parentheses). This is
    the exact same rule the original tool uses for extracted/injected/
    CostomPak outputs — never overwrites."""
    path = Path(path)
    avoid = avoid or ()
    avoid = {Path(a) for a in avoid}
    if path.exists() or path in avoid:
        stem, suffix = path.stem, path.suffix
        i = 1
        while True:
            cand = path.with_name("{} ({}){}".format(stem, i, suffix))
            if not cand.exists() and cand not in avoid:
                return cand
            i += 1
    return path


def timestamp():
    return time.strftime("%Y%m%d_%H%M%S")


def human(n):
    n = float(n)
    for u in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return ("%.1f %s" % (n, u)) if n >= 10 else ("%.2f %s" % (n, u))
        n /= 1024
    return "%.2f TB" % n


def purge(folder):
    """Delete everything inside folder (used by Clear DROP/RESULT)."""
    folder = Path(folder)
    if not folder.exists():
        return
    for p in folder.iterdir():
        if p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
        else:
            try:
                p.unlink()
            except OSError:
                pass


def _display_path(p):
    """Collapse BASE_DIR prefix for pretty UI labels."""
    p = Path(p)
    try:
        return str(p.resolve().relative_to(BASE_DIR.resolve()))
    except ValueError:
        return str(p)