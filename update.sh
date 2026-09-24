#!/data/data/com.termux/files/usr/bin/bash
# =============================================
#  Ikram Tool - Manual Update (V112)
#  Auto-update fail ho jaye to ye manual fallback.
#  Use: bash update.sh   (or:  python3 update.py)
# =============================================
set -e
TOOL_DIR="${IKRAM_TOOL_DIR:-$HOME/Ikram_Tool}"
PY="$TOOL_DIR/.engine/update.py"
if [ ! -f "$PY" ]; then
  # fallback: engine missing -> fresh install via canonical one-liner
  echo "[!] update.py nahi mila — fresh install ho raha hai..."
  curl -sL https://raw.githubusercontent.com/ikram571/ikram-tool/main/install.sh | bash
  exit 0
fi
echo "[*] Latest GitHub release check + clean install..."
"${TERMUX_PREFIX:-/data/data/com.termux/files/usr}/bin/python3" "$PY"
echo "[+] Update done."