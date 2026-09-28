#!/data/data/com.termux/files/usr/bin/bash
# =============================================
#  Ikram Tool - Manual Update (V116)
#  Manual fallback if auto-update fails.
#  Use: bash update.sh   (or:  python3 update.py)
# =============================================
set -e
# Resolve the tool dir from this script's own location. The previous default
# was a hardcoded $HOME/Ikram_Tool, which is wrong whenever the tool is
# installed anywhere else (and wrong for the canonical repo layout).
TOOL_DIR="${IKRAM_TOOL_DIR:-$(cd "$(dirname "$0")" && pwd)}"
PY="$TOOL_DIR/update.py"
if [ ! -f "$PY" ]; then
  # fallback: engine missing -> fresh install via canonical one-liner
  echo "[!] update.py not found — doing a fresh install..."
  curl -sL https://raw.githubusercontent.com/ikram571/ikram-tool/main/install.sh | bash
  exit 0
fi
echo "[*] Latest GitHub release check + clean install..."
"${TERMUX_PREFIX:-/data/data/com.termux/files/usr}/bin/python3" "$PY"
echo "[+] Update done."