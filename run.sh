#!/data/data/com.termux/files/usr/bin/bash
cd "$(dirname "$0")"
export PYTHONDONTWRITEBYTECODE=1
if [ -f ikram_patch.py ]; then
    python3 ikram_patch.py "$@"
elif [ -f ikram.pyc ]; then
    python3 ikram.pyc "$@"
elif [ -f ikram.py ]; then
    python3 ikram.py "$@"
fi
