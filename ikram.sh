#!/data/data/com.termux/files/usr/bin/bash
# =============================================
#  Ikram Tool - Installer
#  Owner: ikram
#  Termux me ikram tool install karta hai
# =============================================
# NOTE: install target = $HOME/Ikram_Tool (clean path, no opencode)
set -e
BANNER="

██╗  ██╗██╗  ██╗██████╗  █████╗ ███╗   ███╗
██║ ██╔╝██║  ██║██╔══██╗██╔══██╗████╗ ████║
█████╔╝ ███████║██████╔╝███████║██╔████╔██║
██╔═██╗ ██╔══██║██╔══██╗██╔══██║██║╚██╔╝██║
██║  ██╗██║  ██║██║  ██║██║  ██║██║ ╚═╝ ██║
╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝╚═╝     ╚═╝
  PAK / OBB / LUA Tool - by ikram
"
echo "$BANNER"

TARGET="$HOME/Ikram_Tool"

echo "[*] Ikram Tool installing in: $TARGET"

if [ ! -d "$TARGET" ]; then
    SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
    echo "[*] Copying files..."
    mkdir -p "$TARGET"
    cp -r "$SCRIPT_DIR"/modules "$TARGET"/
    cp "$SCRIPT_DIR"/ikram.py "$SCRIPT_DIR"/run.sh "$SCRIPT_DIR"/ikram_key.json "$SCRIPT_DIR"/Memory.md "$TARGET"/
    mkdir -p "$TARGET"/workspace/{PAK_WORKSPACE,LUA_WORKSPACE,OBB_WORKSPACE,RESULT}
fi

echo "[*] Updating packages..."
pkg update -y 2>/dev/null || true

echo "[*] Installing dependencies..."
pkg install -y python openjdk-17 unzip lua53 gcc 2>/dev/null || pkg install -y python openjdk-17 unzip lua53
pip install rich pycryptodome zstandard gmalg 2>/dev/null || pip install --break-system-packages rich pycryptodome zstandard gmalg

echo "[*] Checking luac..."
if ! command -v luac >/dev/null 2>&1 && ! command -v luac5.3 >/dev/null 2>&1; then
    echo "[!] luac nahi mila. Lua compile ke liye chahiye."
fi

echo "[*] Adding 'ikram' command..."
RC="$HOME/.bashrc"
if ! grep -q 'ikram()' "$RC" 2>/dev/null; then
    cat >> "$RC" <<'EOF'

# Ikram Tool launcher
ikram() { python3 "$HOME/Ikram_Tool/ikram.py" "$@"; }
EOF
fi

echo "[*] Setting permissions..."
chmod +x "$TARGET/ikram.py" "$TARGET/run.sh" 2>/dev/null || true

echo ""
echo "[+] Ikram Tool installed!"
echo "[+] Run karo:  ikram"
echo "[+] ya:        bash $TARGET/run.sh"
