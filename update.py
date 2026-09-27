"""IKRAM TOOL - GitHub auto-update (client core).

Downloads the latest zip (IkramTool.zip) from the GitHub release,
extracts it, and CLEAN-SLATE replaces the installed tool folder:
old tool files are deleted, then the full fresh set is copied. So no
file is ever missing — the tool is always A-to-Z complete.

`ikram.py` runs `update.py --check` at every start to decide whether
an update is needed.

Usage:
  python3 update.py --check     -> remote|local  (version compare only)
  python3 update.py             -> download latest zip + clean install
"""
import json
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

TOOL_DIR = Path(__file__).resolve().parent

# A version check is a courtesy, not a gate. Five seconds is long enough for
# the GitHub API on a good connection and short enough that a dead network
# does not leave the user staring at a spinner before the tool opens.
VERSION_CHECK_TIMEOUT = 5
REPO = "ikram571/ikram-tool"
API = "https://api.github.com/repos/{}/releases/latest".format(REPO)
ZIP_NAME = "IkramTool.zip"

# The one true activation key hash. This must always equal the key_hash in
# ikram_key.json and in release.sh — a typo here silently invalidates the
# user's key. tests/test_updater_safety.py cross-checks all three.
CANONICAL_KEY_HASH = (
    "7360b6c497b3f043eb4d74ae1100f8681b6a968719135cd6de7b58f3363d5c36"
)

# ------------------- ANSI palette (matches Ikram Tool UI) --------------------
_TTY = 1 if (hasattr(sys.stdout, "isatty") and sys.stdout.isatty()) else 0
_R = "\033[0m"
_PINK = "\033[1;38;5;201m"
_CYAN = "\033[1;38;5;51m"
_GOLD = "\033[1;38;5;220m"
_GREEN = "\033[1;38;5;82m"
_RED = "\033[1;38;5;196m"
_DIM = "\033[2;38;5;244m"
_BOLD = "\033[1m"


def _pcol(content, width=30):
    """Pretty-print a line inside a colored box (pink border)."""
    text = content.ljust(width)
    return "{}{}{}{}{}".format(_PINK, "│", _R, text, _PINK)


def _box_top(width=30):
    return "{}{}{}".format(_PINK, "╭" + "─" * width + "╮", _R)


def _box_bot(width=30):
    return "{}{}{}".format(_PINK, "╰" + "─" * width + "╯", _R)


def _splash():
    """Premium update splash (matches the tool's startup panel)."""
    w = 50
    sep = "{}{}{}".format(_GOLD, "✦" * w, _R)
    title = "{}{}IKRAM TOOL UPDATE{}".format(_BOLD, _CYAN, _R)
    sub = "{}📦 PAK  •  📜 LUA{}".format(_CYAN, _R)
    pad_t = (w - 13) // 2
    pad_s = (w - 14) // 2
    lines = [
        "",
        sep,
        " " * pad_t + title,
        " " * pad_s + sub,
        sep,
        "",
    ]
    return "\n".join(lines)


def version_tuple(v):
    try:
        v = str(v).lstrip("vV").strip()
        parts = [p for p in v.split(".") if p != ""]
        return [int(p) for p in parts] if parts else [0]
    except Exception:
        return [0]


def latest_remote():
    """Latest release ka zip download URL + version. Return dict or None."""
    try:
        req = urllib.request.Request(API, headers={"User-Agent": "ikram-tool"})
        with urllib.request.urlopen(req, timeout=VERSION_CHECK_TIMEOUT) as r:
            d = json.load(r)
        tag = str(d.get("tag_name", "")).lstrip("vV")
        for a in d.get("assets", []):
            if a.get("name") == ZIP_NAME:
                return {"version": tag, "url": a["browser_download_url"]}
        for a in d.get("assets", []):
            if str(a.get("name", "")).endswith(".zip"):
                return {"version": tag, "url": a["browser_download_url"]}
    except Exception:
        pass
    return None


def _fmt_size(n):
    if n >= 1048576:
        return "{:.1f} MB".format(n / 1048576)
    if n >= 1024:
        return "{:.0f} KB".format(n / 1024)
    return "{} B".format(n)


class _Progress:
    """Premium colored live download box (matches the tool's progress UI)."""

    def __init__(self):
        self._drawn = False

    def show(self, done, total):
        sz_done = _fmt_size(done)
        sz_total = _fmt_size(total) if total else "?"
        pct = int(done / total * 100) if total else 0
        bar_w = 18
        filled = pct * bar_w // 100
        bar = "{}{}{}{}".format(
            _GREEN, "█" * filled, _DIM, "░" * (bar_w - filled)
        )
        pct_color = _GREEN if pct >= 100 else _CYAN
        lines = [
            _box_top(30),
            _pcol("  ⬇  Downloading update"),
            _pcol("  [{}] {}{:>3}{}%".format(bar, pct_color, pct, _R)),
            _pcol("  Downloaded: {}".format(sz_done)),
            _pcol("  Total: {}".format(sz_total)),
            _box_bot(30),
        ]
        if _TTY and self._drawn:
            print("\x1b[{}A".format(len(lines)), end="")
        for l in lines:
            print(l)
        self._drawn = True


# keep these during an update replace (user data + version state)
PROTECTED = {
    "DROP",
    "RESULT",
    "VERSION",
    "ikram_key.json",
    ".ikram_update.zip",
    ".ikram_update_tmp",
    ".repair",
    "repair.zip",
}

# A payload without the tool's own entry points is not an update, it is a
# broken or truncated download. The old installer deleted the whole runtime
# first and copied afterwards, so a partial payload left the tool uninstalled
# and unrecoverable without a manual reinstall. These must all be present
# before a single existing file is touched.
REQUIRED_ENTRIES = (
    "ikram.pyc",
    "ikram_patch.py",
    "lua_pipeline.py",
    "mega_lua.py",
    "univ.py",
    "update.py",
)

# A real release ships dozens of runtime files. Anything close to this count is
# a truncated archive, not a small update.
MIN_PAYLOAD_FILES = 40

BACKUP_DIR = ".ikram_update_backup"


class InstallError(Exception):
    """A payload cannot be installed safely. The live install is unchanged."""


def _safe_extract(zip_path, dest):
    """Extract an archive, refusing any member that would escape dest.

    A zip entry named ../../something writes outside the staging directory, so
    the paths are resolved and checked rather than trusted.
    """
    dest = Path(dest)
    root = dest.resolve()
    with zipfile.ZipFile(zip_path) as z:
        names = z.namelist()
        if not names:
            raise InstallError("archive is empty")
        for name in names:
            if name.startswith("/") or ".." in Path(name).parts:
                raise InstallError("unsafe path in archive: %s" % name)
            target = (root / name).resolve()
            if target != root and root not in target.parents:
                raise InstallError("unsafe path in archive: %s" % name)
        z.extractall(dest)


def _payload_root(tmp):
    """Release zips sometimes ship a single wrapper folder; step into it."""
    tmp = Path(tmp)
    nested = [p for p in tmp.iterdir() if p.is_dir()]
    if len(nested) == 1 and (nested[0] / "ikram.pyc").exists():
        return nested[0]
    return tmp


def _validate_payload(src):
    """(ok, reason). The gate that keeps a bad download away from the install."""
    src = Path(src)
    if not src.is_dir():
        return False, "payload directory missing"
    files = [p for p in src.rglob("*") if p.is_file()]
    if not files:
        return False, "payload contains no files"
    names = {p.name for p in src.iterdir()}
    missing = [n for n in REQUIRED_ENTRIES if n not in names]
    if missing:
        return False, "payload is missing %s" % ", ".join(sorted(missing))
    if len(files) < MIN_PAYLOAD_FILES:
        return False, ("payload has only %d file(s); a real release has %d+ "
                       "so this looks like a truncated download"
                       % (len(files), MIN_PAYLOAD_FILES))
    return True, "%d files validated" % len(files)


def _drop(path):
    """Remove a file, symlink or directory without ever raising."""
    try:
        p = Path(path)
        if p.is_symlink() or p.is_file():
            p.unlink()
        elif p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
    except OSError:
        pass


def _clean_replace(src):
    """Replace the runtime with src as a transaction, not a delete-then-copy.

    Every existing non-protected entry is MOVED aside first, the new set is
    copied in, and the result is verified. If any step fails, the partial copy
    is removed and the previous runtime is moved straight back, so a bad
    download can never leave the tool uninstalled.

    DROP/RESULT/VERSION/ikram_key.json are never touched.
    """
    src = Path(src)
    ok, reason = _validate_payload(src)
    if not ok:
        raise InstallError(reason)

    if not TOOL_DIR.exists():
        TOOL_DIR.mkdir(parents=True, exist_ok=True)
    backup = TOOL_DIR / BACKUP_DIR
    shutil.rmtree(backup, ignore_errors=True)
    backup.mkdir(parents=True, exist_ok=True)

    moved, installed = [], []
    try:
        for old in list(TOOL_DIR.iterdir()):
            if old.name in PROTECTED or old.name == BACKUP_DIR:
                continue
            shutil.move(str(old), str(backup / old.name))
            moved.append(old.name)

        for f in src.iterdir():
            if f.name in PROTECTED:
                continue
            dst = TOOL_DIR / f.name
            if f.is_dir():
                shutil.copytree(f, dst)
            else:
                shutil.copy2(f, dst)
            installed.append(f.name)

        gone = [n for n in REQUIRED_ENTRIES if not (TOOL_DIR / n).exists()]
        if gone:
            raise InstallError("install came out incomplete, missing %s"
                               % ", ".join(sorted(gone)))
    except Exception as exc:
        for name in installed:
            _drop(TOOL_DIR / name)
        for name in moved:
            kept = backup / name
            if kept.exists() or kept.is_symlink():
                shutil.move(str(kept), str(TOOL_DIR / name))
        shutil.rmtree(backup, ignore_errors=True)
        if isinstance(exc, InstallError):
            raise
        raise InstallError("copy failed (%s); previous install restored"
                           % exc)

    for name in ("run.sh", "install.sh", "lua_patched", "luac_patched",
                 "unluac_rs", "repak"):
        p = TOOL_DIR / name
        if p.exists():
            try:
                p.chmod(0o755)
            except Exception:
                pass
    shutil.rmtree(backup, ignore_errors=True)
    return True


def _show_complete():
    """Premium update-complete box (matches the tool's exit panel)."""
    w = 50
    green_bar = "{}{}{}".format(_GREEN, "✦" * w, _R)
    if _TTY:
        print("")
        print(green_bar)
        print("{}{}{}".format(_GREEN, "  ✅  UPDATE INSTALLED SUCCESSFULLY!", _R))
        print("{}{}{}".format(_GREEN, "      Restart the tool to continue...", _R))
        print(green_bar)
        print("")
    else:
        print("UPDATE_INSTALLED_SUCCESS")


def do_install():
    """Download + install the latest release. Returns True only on a real
    complete install; every failure path leaves the current install intact."""
    info = latest_remote()
    if not info:
        print("NO_RELEASE")
        return False

    zip_path = TOOL_DIR / ".ikram_update.zip"
    tmp = TOOL_DIR / ".ikram_update_tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True, exist_ok=True)

    try:
        req = urllib.request.Request(
            info["url"], headers={"User-Agent": "ikram-tool"}
        )
        print(_splash())
        prog = _Progress()
        with urllib.request.urlopen(req, timeout=120) as r:
            total = int(r.headers.get("Content-Length") or 0)
            data = bytearray()
            while True:
                chunk = r.read(65536)
                if not chunk:
                    break
                data += chunk
                prog.show(len(data), total)
        if not data:
            raise InstallError("download produced an empty file")
        zip_path.write_bytes(data)

        _safe_extract(zip_path, tmp)
        _clean_replace(_payload_root(tmp))

        try:
            ver = "V" + str(info["version"]).lstrip("vV")
            (TOOL_DIR / "VERSION").write_text(ver)
            kf = TOOL_DIR / "ikram_key.json"
            try:
                d = json.loads(kf.read_text())
                d["version"] = ver
                kf.write_text(json.dumps(d, indent=2))
            except Exception:
                kf.write_text(
                    '{\n  "version": "%s",\n'
                    '  "key_hash": "%s"\n}\n' % (ver, CANONICAL_KEY_HASH)
                )
        except Exception:
            pass

        _show_complete()
        print("INSTALLED_OK")
        # Synchronous on purpose. This runs pkg/pip, and a dpkg that is
        # killed halfway leaves the package database locked and the next
        # install failing; a daemon thread dies with this process, which is
        # exactly the moment the tool exits. The files are already in place,
        # so all that blocking costs is the wait on the repair itself.
        _fix_env()
        return True
    except InstallError as e:
        print("UPDATE_ABORTED: {}".format(e))
        print("Your current install was left untouched.")
        return False
    except Exception as e:
        print("FAIL: {}".format(e))
        print("Your current install was left untouched.")
        return False
    finally:
        _drop(zip_path)
        shutil.rmtree(tmp, ignore_errors=True)


def _has_lib(name):
    """True when the module is importable, without importing it twice."""
    import importlib.util
    try:
        return importlib.util.find_spec(name) is not None
    except Exception:
        return False


def _fix_env():
    """Install what the tool needs and put the `ikram` command back.

    Blocking by design — see the call site. Every step announces itself, so
    a ten minute wait reads as progress instead of a frozen screen.
    """
    try:
        home = Path.home()
    except Exception:
        return
    try:
        need = []
        for tool, pkg in (
            ("python", "python"),
            ("git", "git"),
            ("curl", "curl"),
            ("unzip", "unzip"),
            ("lua5.3", "lua53"),
        ):
            if not shutil.which(tool):
                need.append(pkg)
        if not shutil.which("javac"):
            print("ENV_REPAIR: installing a Java compiler (needed for "
                  "some PAK work)...")
            # openjdk package name varies by repo/mirror — try 17/21/25
            for jp in ("openjdk-17", "openjdk-21", "openjdk-25"):
                for _ in range(3):
                    try:
                        subprocess.run(
                            ["pkg", "install", "-y", jp],
                            capture_output=True,
                            timeout=600,
                        )
                        if shutil.which("javac"):
                            break
                    except Exception:
                        pass
                if shutil.which("javac"):
                    break
        if need:
            print("ENV_REPAIR: installing %s..." % ", ".join(need))
            for pkg in need:
                for _ in range(3):
                    try:
                        subprocess.run(
                            ["pkg", "install", "-y", pkg],
                            capture_output=True,
                            timeout=600,
                        )
                        break
                    except Exception:
                        pass
        try:
            subprocess.run(
                ["pkg", "upgrade", "-y", "python"],
                capture_output=True,
                timeout=600,
            )
        except Exception:
            pass
        missing_lib = [lib for lib in ("rich", "pycryptodome", "zstandard",
                                       "gmalg")
                       if not _has_lib(lib)]
        if missing_lib:
            print("ENV_REPAIR: installing %s..." % ", ".join(missing_lib))
        for lib in ("rich", "pycryptodome", "zstandard", "gmalg"):
            for _ in range(3):
                try:
                    subprocess.run(
                        ["pip", "install", lib],
                        capture_output=True,
                        timeout=600,
                    )
                    break
                except Exception:
                    pass
        # ---- 'ikram' launcher -> ikram_patch.py (poora tool A-to-Z load) ----
        # Built from TOOL_DIR, not typed in: the tool has been installed
        # both as ~/Ikram_Tool and as a plain .engine tree, and a launcher
        # pointing at the wrong one fails with a bare "command not found".
        tdir = str(TOOL_DIR)
        launcher = (
            "ikram() { PYTHONDONTWRITEBYTECODE=1 MAGIC_NEEDED=$(python3 -c "
            "'import importlib.util;print(importlib.util.MAGIC_NUMBER.hex())' "
            "2>/dev/null); if ! python3 -c \"import sys; "
            "from pathlib import Path; "
            "p=Path('@@PATCH@@'); print(p.exists())\" "
            "2>/dev/null | grep -q True; then echo '  Tool files missing - reinstall with: install.sh'; return 1; fi; "
            "MAGIC_HAVE=$(python3 -c \"import struct; "
            "p=open('@@CORE@@','rb').read(4); print(p.hex())\" "
            "2>/dev/null); if [ -n \"$MAGIC_HAVE\" ] && [ \"$MAGIC_HAVE\" != \"$MAGIC_NEEDED\" ]; then "
            "echo ''; echo '  \u2b06 Python is outdated \u2014 upgrading...'; "
            "pkg upgrade -y python 2>&1 | tail -3; echo '  \u2713 Now try again: ikram'; "
            "echo ''; return 1; fi; python3 \"@@PATCH@@\" \"$@\"; }"
        ).replace("@@PATCH@@", str(Path(tdir) / "ikram_patch.py")) \
         .replace("@@CORE@@", str(Path(tdir) / "ikram.pyc"))
        suffix = "\n\n# Ikram Tool launcher\n{}\n".format(launcher)
        rc = home / ".bashrc"
        try:
            # A missing .bashrc must not skip the launcher: read "" when it
            # is not there, and write the file either way.
            text = rc.read_text(errors="ignore") if rc.exists() else ""
            lines = []
            for l in text.splitlines():
                t = l.strip()
                # the whole launcher is one line; strip it and its header so
                # repeated installs cannot stack up copies of it
                if t.startswith("ikram()") or t == "# Ikram Tool launcher":
                    continue
                lines.append(l)
            text = "\n".join(lines).rstrip() + suffix
            rc.write_text(text)
        except Exception:
            pass
        # ---- real executable: $PREFIX/bin/ikram -> ikram_patch.py ----
        try:
            prefix = os.environ.get(
                "PREFIX", "/data/data/com.termux/files/usr"
            )
        except Exception:
            prefix = "/data/data/com.termux/files/usr"
        bindir = Path(prefix) / "bin"
        bindir.mkdir(parents=True, exist_ok=True)
        binpath = bindir / "ikram"
        # Same rule as the .bashrc launcher: the install directory is
        # substituted in, never assumed, so the self-repair path repairs the
        # copy the user actually has.
        bdir = str(TOOL_DIR)
        bpatch = str(Path(bdir) / "ikram_patch.py")
        bcore = str(Path(bdir) / "ikram.pyc")
        binlauncher = (
            "#!/data/data/com.termux/files/usr/bin/bash\n"
            "export PYTHONDONTWRITEBYTECODE=1\n"
            "TOOL_DIR=@@DIR@@\n"
            "if ! command -v python3 >/dev/null 2>&1; then\n"
            '  echo ""\n  echo "  python3 not found! Install it:"\n'
            '  echo "    pkg update -y && pkg install -y python"\n'
            '  echo ""\n  exit 1\nfi\n'
            "if [ ! -f \"$TOOL_DIR/ikram_patch.py\" ]; then\n"
            '  echo ""\n'
            '  echo "  \u26a0 Tool files missing \u2014 self-repairing..."\n'
            '  mkdir -p "$TOOL_DIR"\n'
            '  cd "$TOOL_DIR"\n'
            '  curl -sL -o repair.zip "https://github.com/ikram571/ikram-tool/releases/latest/download/IkramTool.zip"\n'
            '  TMPX="$TOOL_DIR/.repair"\n'
            '  rm -rf "$TMPX" && mkdir -p "$TMPX"\n'
            '  if (cd "$TMPX" && unzip -q -o "$TOOL_DIR/repair.zip") && [ -f "$TMPX/ikram.pyc" ]; then\n'
            '    cp -r "$TMPX"/. "$TOOL_DIR"/ 2>/dev/null\n'
            '    chmod +x "$TOOL_DIR/run.sh" "$TOOL_DIR/ikram_patch.py" 2>/dev/null\n'
            '    echo "  \u2713 Repair done! Tool is starting..."\n'
            '    exec python3 "$TOOL_DIR/ikram_patch.py" "$@"\n'
            "  fi\n"
            '  rm -rf "$TMPX" "$TOOL_DIR/repair.zip"\n'
            '  echo "  \u2717 Repair failed. Reinstall with:"\n'
            '  echo "    curl -sL https://raw.githubusercontent.com/ikram571/ikram-tool/main/install.sh | bash"\n'
            '  echo ""\n  exit 1\nfi\n'
            "MAGIC_NEEDED=$(python3 -c "
            '"import importlib.util;print(importlib.util.MAGIC_NUMBER.hex())" 2>/dev/null)\n'
            'MAGIC_HAVE=$(python3 -c "\nimport struct\n'
            "p = open('@@CORE@@','rb').read(4)\nprint(p.hex())\n"
            '" 2>/dev/null)\n'
            'if [ -n "$MAGIC_HAVE" ] && [ "$MAGIC_HAVE" != "$MAGIC_NEEDED" ]; then\n'
            '  echo ""\n'
            '  echo "  \u2b06 Python is outdated \u2014 upgrading..."\n'
            '  pkg update -y >/dev/null 2>&1\n'
            '  pkg upgrade -y python 2>&1 | tail -3\n'
            '  exec python3 "$TOOL_DIR/ikram_patch.py" "$@"\n'
            "fi\n"
            'exec python3 "$TOOL_DIR/ikram_patch.py" "$@"\n'
        ).replace("@@DIR@@", bdir).replace("@@CORE@@", bcore)
        binpath.write_text(binlauncher)
        binpath.chmod(0o755)
    except Exception:
        pass
    return None


def check_only():
    info = latest_remote()
    if not info:
        print("NO_RELEASE")
        return None
    v = TOOL_DIR / "VERSION"
    local = v.read_text().strip() if v.exists() else "0.0.0"
    print("{}|{}".format(info["version"], local))
    return None


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--check":
        check_only()
    else:
        # update.sh runs under `set -e`, so a failed install must not look done.
        sys.exit(0 if do_install() else 1)
