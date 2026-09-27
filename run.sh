#!/data/data/com.termux/files/usr/bin/bash
cd "$(dirname "$0")"
export PYTHONDONTWRITEBYTECODE=1
if [ -f ikram_patch.py ]; then
    exec python3 ikram_patch.py "$@"
elif [ -f ikram.pyc ]; then
    exec python3 ikram.pyc "$@"
else
    # Without this the script used to exit 0 having done nothing, so a broken
    # or half-extracted install looked like a clean run.
    echo "[x] Ikram Tool is incomplete: neither ikram_patch.py nor ikram.pyc is present." >&2
    echo "    Re-extract the release ZIP over this folder, or run:  bash update.sh" >&2
    exit 1
fi
