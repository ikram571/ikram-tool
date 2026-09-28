#!/data/data/com.termux/files/usr/bin/bash
# =============================================
#  Ikram Tool - Manual Update
#  Manual fallback if auto-update fails.
#  Use: bash update.sh   (or:  python3 update.py)
# =============================================
  set -e
  # update.sh ships inside .engine/, so its own directory IS the tool dir.
  TOOL_DIR="$(cd "$(dirname "$0")" && pwd)"
  PY="$TOOL_DIR/update.py"
  if [ ! -f "$PY" ]; then
    echo "[!] update.py not found — doing a fresh install..."
    curl -sL https://raw.githubusercontent.com/ikram571/ikram-tool/main/install.sh | bash
    exit 0
  fi
echo "[*] Latest GitHub release check + clean install..."
"${TERMUX_PREFIX:-/data/data/com.termux/files/usr}/bin/python3" "$PY"
echo "[+] Update done."