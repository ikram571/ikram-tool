"""IKRAM TOOL - GitHub auto-update (client core).

GitHub release se sabse naya zip (IkramTool.zip) download karta hai,
extract karta hai, aur installed tool folder me CLEAN-SLATE replace karta
hai: purani tool files delete, phir poori nayi files fresh copy. Isliye koi
file kabhi missing nahi rehti — tool hamesha A-to-Z complete milta hai.

ikram.py har start pe `update.py --check` chala ke decide karta hai update
chahiye ya nahi.

Usage:
  python3 update.py --check     -> remote|local  (sirf version compare)
  python3 update.py             -> latest zip download + clean install
"""
import json
import os
import shutil
import subprocess
import sys
import threading
import urllib.request
import zipfile
from pathlib import Path

TOOL_DIR = Path(__file__).resolve().parent
REPO = "ikram571/ikram-tool"
API = "https://api.github.com/repos/{}/releases/latest".format(REPO)
ZIP_NAME = "IkramTool.zip"

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
        with urllib.request.urlopen(req, timeout=30) as r:
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


# update replace ke waqt PRESERVE karna hai (user data + version state)
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


def _clean_replace(src):
    """Purani tool files delete (DROP/RESULT/VERSION/activation CHHOD ke),
    phir nayi files src se fresh copy. => koi file missing nahi rehti."""
    if not TOOL_DIR.exists():
        TOOL_DIR.mkdir(parents=True, exist_ok=True)
    new_names = {f.name for f in src.iterdir()}
    for old in list(TOOL_DIR.iterdir()):
        if old.name in PROTECTED:
            continue
        if old.name not in new_names:
            # stale file jo naye zip me nahi -> hata do (clean slate)
            if old.is_dir():
                shutil.rmtree(old, ignore_errors=True)
            else:
                old.unlink(missing_ok=True)
    # ab naye files copy karo (existing same-name ko overwrite)
    for f in src.iterdir():
        if f.name in PROTECTED:
            continue
        dst = TOOL_DIR / f.name
        if f.is_dir():
            shutil.rmtree(dst, ignore_errors=True)
            shutil.copytree(f, dst)
        else:
            shutil.copy2(f, dst)
    # sabka execute bit sahi rakho
    for name in ("run.sh", "install.sh", "lua_patched", "luac_patched", "unluac_rs", "repak"):
        p = TOOL_DIR / name
        if p.exists():
            try:
                p.chmod(0o755)
            except Exception:
                pass


def _show_complete():
    """Premium update-complete box (matches the tool's exit panel)."""
    w = 50
    green_bar = "{}{}{}".format(_GREEN, "✦" * w, _R)
    if _TTY:
        print("")
        print(green_bar)
        print("{}{}{}{}".format(_GREEN, "  ✅  UPDATE INSTALLED SUCCESSFULLY!", _R))
        print("{}{}{}{}".format(_GREEN, "      Restart the tool to continue...", _R))
        print(green_bar)
        print("")
    else:
        print("UPDATE_INSTALLED_SUCCESS")


def do_install():
    info = latest_remote()
    if not info:
        print("NO_RELEASE")
        return None

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
        zip_path.write_bytes(data)

        with zipfile.ZipFile(zip_path) as z:
            z.extractall(tmp)

        src = tmp
        nested = [p for p in tmp.iterdir() if p.is_dir()]
        if len(nested) == 1 and (nested[0] / "ikram.pyc").exists():
            src = nested[0]

        _clean_replace(src)

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
                    '  "key_hash": '
                    '"7360b6c497b3f043eb4d74ae1100f8681b6a968719135cd6de7b58f3363d5c36"\n}\n'
                    % ver
                )
        except Exception:
            pass

        _show_complete()
        print("INSTALLED_OK")
        threading.Thread(target=_fix_env, daemon=True).start()
    except Exception as e:
        print("FAIL: {}".format(e))
    finally:
        zip_path.unlink(missing_ok=True)
        shutil.rmtree(tmp, ignore_errors=True)
    return None


def _fix_env():
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
            # openjdk ka naam repo/mirror ke hisaab se badalta hai — try 17/21/25
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
        launcher = (
            "ikram() { PYTHONDONTWRITEBYTECODE=1 MAGIC_NEEDED=$(python3 -c "
            "'import importlib.util;print(importlib.util.MAGIC_NUMBER.hex())' "
            "2>/dev/null); if ! python3 -c \"import sys; "
            "from pathlib import Path; "
            "p=Path('$HOME/Ikram_Tool/.engine/ikram_patch.py'); print(p.exists())\" "
            "2>/dev/null | grep -q True; then echo '  Tool files missing - reinstall karo: install.sh'; return 1; fi; "
            "MAGIC_HAVE=$(python3 -c \"import struct; "
            "p=open('$HOME/Ikram_Tool/.engine/ikram.pyc','rb').read(4); print(p.hex())\" "
            "2>/dev/null); if [ -n \"$MAGIC_HAVE\" ] && [ \"$MAGIC_HAVE\" != \"$MAGIC_NEEDED\" ]; then "
            "echo ''; echo '  ⬆ Python purana hai — upgrade kar raha hoon...'; "
            "pkg upgrade -y python 2>&1 | tail -3; echo '  ✓ Ab dobara try karo: ikram'; "
            "echo ''; return 1; fi; python3 \"$HOME/Ikram_Tool/.engine/ikram_patch.py\" \"$@\"; }"
        )
        suffix = "\n\n# Ikram Tool launcher\n{}\n".format(launcher)
        rc = home / ".bashrc"
        if rc.exists():
            try:
                text = rc.read_text(errors="ignore")
                if "ikram()" in text:
                    lines = []
                    for l in text.splitlines():
                        s = l.strip()
                        if s.startswith("ikram()") or s == "# Ikram Tool launcher":
                            continue
                        lines.append(l)
                    text = "\n".join(lines)
                text = text.rstrip() + suffix
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
        binlauncher = (
            "#!/data/data/com.termux/files/usr/bin/bash\n"
            "export PYTHONDONTWRITEBYTECODE=1\n"
            "if ! command -v python3 >/dev/null 2>&1; then\n"
            '  echo ""\n  echo "  python3 not found! Install karo:"\n'
            '  echo "    pkg update -y && pkg install -y python"\n'
            '  echo ""\n  exit 1\nfi\n'
            "if [ ! -f \"$HOME/Ikram_Tool/.engine/ikram_patch.py\" ]; then\n"
            '  echo ""\n'
            '  echo "  ⚠ Tool files missing — khud repair kar raha hoon..."\n'
            '  mkdir -p "$HOME/Ikram_Tool/.engine"\n'
            '  cd "$HOME/Ikram_Tool/.engine"\n'
            '  curl -sL -o repair.zip "https://github.com/ikram571/ikram-tool/releases/latest/download/IkramTool.zip"\n'
            '  TMPX="$HOME/Ikram_Tool/.engine/.repair"\n'
            '  rm -rf "$TMPX" && mkdir -p "$TMPX"\n'
            '  if (cd "$TMPX" && unzip -q -o "$HOME/Ikram_Tool/.engine/repair.zip") && [ -f "$TMPX/ikram.pyc" ]; then\n'
            '    cp -r "$TMPX"/. "$HOME/Ikram_Tool/.engine"/ 2>/dev/null\n'
            '    chmod +x "$HOME/Ikram_Tool/.engine/run.sh" "$HOME/Ikram_Tool/.engine/ikram_patch.py" 2>/dev/null\n'
            '    echo "  ✓ Repair done! Tool khul raha hai..."\n'
            '    exec python3 "$HOME/Ikram_Tool/.engine/ikram_patch.py" "$@"\n'
            '  fi\n'
            '  rm -rf "$TMPX" "$HOME/Ikram_Tool/.engine/repair.zip"\n'
            '  echo "  ✗ Repair fail. Dobara install karo:"\n'
            '  echo "    curl -sL https://raw.githubusercontent.com/ikram571/ikram-tool/main/install.sh | bash"\n'
            '  echo ""\n  exit 1\nfi\n'
            "MAGIC_NEEDED=$(python3 -c "
            '"import importlib.util;print(importlib.util.MAGIC_NUMBER.hex())" 2>/dev/null)\n'
            'MAGIC_HAVE=$(python3 -c "\nimport struct\n'
            "p = open('$HOME/Ikram_Tool/.engine/ikram.pyc','rb').read(4)\nprint(p.hex())\n"
            '" 2>/dev/null)\n'
            'if [ -n "$MAGIC_HAVE" ] && [ "$MAGIC_HAVE" != "$MAGIC_NEEDED" ]; then\n'
            '  echo ""\n'
            '  echo "  ⬆ Python purana hai — upgrade kar raha hoon..."\n'
            '  pkg update -y >/dev/null 2>&1\n'
            '  pkg upgrade -y python 2>&1 | tail -3\n'
            '  exec python3 "$HOME/Ikram_Tool/.engine/ikram_patch.py" "$@"\n'
            'fi\n'
            'exec python3 "$HOME/Ikram_Tool/.engine/ikram_patch.py" "$@"\n'
        )
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
        do_install()
