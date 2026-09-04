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
    """Download ke waqt chhota sa live box - kitna download hua + total size."""

    def __init__(self):
        self._drawn = False

    def _line(self, content):
        inner = 30
        return "│" + content.ljust(inner) + "│"

    def show(self, done, total):
        sz_done = _fmt_size(done)
        sz_total = _fmt_size(total) if total else "?"
        pct = int(done / total * 100) if total else 0
        bar_w = 18
        filled = pct * bar_w // 100
        bar = "█" * filled + "░" * (bar_w - filled)
        lines = [
            "╭──────────────────────────────╮",
            self._line("  ⬇  Downloading update"),
            self._line("  [{}] {:>3}%".format(bar, pct)),
            self._line("  Downloading: {}".format(sz_done)),
            self._line("  Size: {}".format(sz_total)),
            "╰──────────────────────────────╯",
        ]
        if self._drawn:
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
    for name in ("run.sh", "install.sh", "lua_patched", "luac_patched", "unluac_rs"):
        p = TOOL_DIR / name
        if p.exists():
            try:
                p.chmod(0o755)
            except Exception:
                pass


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
        print("  ✓ Downloaded. Installing...")

        with zipfile.ZipFile(zip_path) as z:
            z.extractall(tmp)

        src = tmp
        nested = [p for p in tmp.iterdir() if p.is_dir()]
        # agar zip me ek single nested folder ho (ikram.py ke saath) to usme jao
        if len(nested) == 1 and (nested[0] / "ikram.py").exists():
            src = nested[0]

        # CLEAN-SLATE: old tool files delete + fresh copy
        _clean_replace(src)

        # LOOP FIX: VERSION + ikram_key.json PROTECTED hain isliye _clean_replace
        # unhe preserve karta hai -> isi naye version se stamp karo, warna next
        # boot pe remote>local rahega aur update-loop chalta rahega.
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

        print("INSTALLED_OK")
        # fix env + launcher background me (tool restart par hi chahiye)
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
            ("javac", "openjdk-17"),
            ("lua5.3", "lua53"),
        ):
            if not shutil.which(tool):
                need.append(pkg)
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
    except Exception:
        pass
    try:
        # ---- 'ikram' launcher -> ikram_patch.py (poora tool A-to-Z load) ----
        launcher = (
            "ikram() { PYTHONDONTWRITEBYTECODE=1 MAGIC_NEEDED=$(python3 -c "
            "'import importlib.util;print(importlib.util.MAGIC_NUMBER.hex())' "
            "2>/dev/null); if ! python3 -c \"import sys; "
            "from pathlib import Path; "
            "p=Path('$HOME/Ikram_Tool/ikram_patch.py'); print(p.exists())\" "
            "2>/dev/null | grep -q True; then echo '  Tool files missing - reinstall karo: install.sh'; return 1; fi; "
            "MAGIC_HAVE=$(python3 -c \"import struct; "
            "p=open('$HOME/Ikram_Tool/ikram.pyc','rb').read(4); print(p.hex())\" "
            "2>/dev/null); if [ -n \"$MAGIC_HAVE\" ] && [ \"$MAGIC_HAVE\" != \"$MAGIC_NEEDED\" ]; then "
            "echo ''; echo '  ⬆ Python purana hai — upgrade kar raha hoon...'; "
            "pkg upgrade -y python 2>&1 | tail -3; echo '  ✓ Ab dobara try karo: ikram'; "
            "echo ''; return 1; fi; python3 \"$HOME/Ikram_Tool/ikram_patch.py\" \"$@\"; }"
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
            import os

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
            "if [ ! -f \"$HOME/Ikram_Tool/ikram_patch.py\" ]; then\n"
            '  echo ""\n'
            '  echo "  ⚠ Tool files missing — khud repair kar raha hoon..."\n'
            '  mkdir -p "$HOME/Ikram_Tool"\n'
            '  cd "$HOME/Ikram_Tool"\n'
            '  curl -sL -o repair.zip "https://github.com/ikram571/ikram-tool/releases/latest/download/IkramTool.zip"\n'
            '  TMPX="$HOME/Ikram_Tool/.repair"\n'
            '  rm -rf "$TMPX" && mkdir -p "$TMPX"\n'
            '  if (cd "$TMPX" && unzip -q -o "$HOME/Ikram_Tool/repair.zip") && [ -f "$TMPX/ikram.pyc" ]; then\n'
            '    cp -r "$TMPX"/. "$HOME/Ikram_Tool"/ 2>/dev/null\n'
            '    chmod +x "$HOME/Ikram_Tool/run.sh" "$HOME/Ikram_Tool/ikram_patch.py" 2>/dev/null\n'
            '    echo "  ✓ Repair done! Tool khul raha hai..."\n'
            '    exec python3 "$HOME/Ikram_Tool/ikram_patch.py" "$@"\n'
            '  fi\n'
            '  rm -rf "$TMPX" "$HOME/Ikram_Tool/repair.zip"\n'
            '  echo "  ✗ Repair fail. Dobara install karo:"\n'
            '  echo "    curl -sL https://raw.githubusercontent.com/ikram571/ikram-tool/main/install.sh | bash"\n'
            '  echo ""\n  exit 1\nfi\n'
            "MAGIC_NEEDED=$(python3 -c "
            '"import importlib.util;print(importlib.util.MAGIC_NUMBER.hex())" 2>/dev/null)\n'
            'MAGIC_HAVE=$(python3 -c "\nimport struct\n'
            "p = open('$HOME/Ikram_Tool/ikram.pyc','rb').read(4)\nprint(p.hex())\n"
            '" 2>/dev/null)\n'
            'if [ -n "$MAGIC_HAVE" ] && [ "$MAGIC_HAVE" != "$MAGIC_NEEDED" ]; then\n'
            '  echo ""\n'
            '  echo "  ⬆ Python purana hai — upgrade kar raha hoon..."\n'
            '  pkg update -y >/dev/null 2>&1\n'
            '  pkg upgrade -y python 2>&1 | tail -3\n'
            '  exec python3 "$HOME/Ikram_Tool/ikram_patch.py" "$@"\n'
            'fi\n'
            'exec python3 "$HOME/Ikram_Tool/ikram_patch.py" "$@"\n'
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
