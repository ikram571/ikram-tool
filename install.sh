#!/data/data/com.termux/files/usr/bin/bash
# ============================================================
#  IKRAM TOOL - ONE LINE INSTALLER
#  Ye file copy karo, Termux me paste karo, sab install ho
#  jayega (tool + dependencies + ikram command).
# ============================================================
set -e

BANNER="
✦✦✦✦✦✦✦✦✦✦✦✦✦✦✦✦✦✦✦✦✦✦✦✦✦✦✦✦✦✦✦✦✦✦✦✦✦✦✦✦✦✦✦✦✦

                            IKRAM TOOL
                       PAK  /  LUA  TOOL

✦✦✦✦✦✦✦✦✦✦✦✦✦✦✦✦✦✦✦✦✦✦✦✦✦✦✦✦✦✦✦✦✦✦✦✦✦✦✦✦✦✦✦✦
"
echo "$BANNER"

GITHUB_URL="https://github.com/ikram571/ikram-tool"
TARGET="$HOME/Ikram_Tool"
LATEST="$GITHUB_URL/releases/latest"
API="$GITHUB_URL/releases/latest/download"

echo "[*] Step 1: Downloads checking..."
command -v curl >/dev/null 2>&1 || pkg install -y curl
command -v zip >/dev/null 2>&1  || pkg install -y zip

echo "[*] Step 2: Downloading latest Ikram Tool..."
command -v unzip >/dev/null 2>&1 || pkg install -y unzip
rm -rf "$TARGET"
mkdir -p "$TARGET"
cd "$TARGET"
curl -fsSL -o tool.zip "$API/IkramTool.zip" || {
    echo ""
    echo "[X] Download FAIL! Internet check karo ya thodi der baad try karo."
    echo "    Agar problem bane to owner se rabta karo."
    exit 1
}
if ! unzip -tq tool.zip >/dev/null 2>&1; then
    echo "[X] Downloaded file corrupt hai. Dobara try karo."
    exit 1
fi
unzip -oq tool.zip -d .
rm -f tool.zip
chmod +x ikram.py run.sh ikram.sh install.sh 2>/dev/null || true

echo "[*] Step 3: Installing dependencies (1st baar mein thora time lagega)..."
pkg update -y >/dev/null 2>&1 || true
pkg install -y python openjdk-17 unzip lua53 gcc >/dev/null 2>&1 || \
pkg install -y python openjdk-17 unzip lua53
pip install rich pycryptodome zstandard gmalg >/dev/null 2>&1 || \
pip install --break-system-packages rich pycryptodome zstandard gmalg >/dev/null 2>&1

echo "[*] Step 4: Adding 'ikram' command..."
RC="$HOME/.bashrc"
touch "$RC"
# Purani (broken ya old) ikram() entry hatao
sed -i '/# Ikram Tool launcher/,+1d' "$RC"
cat >> "$RC" <<'EOF'

# Ikram Tool launcher
ikram() { ( cd "$HOME/Ikram_Tool" && [ -f ikram.pyc ] && exec python3 ikram.pyc "$@" || exec python3 ikram.py "$@" ); }
EOF

echo "[*] Step 5: Terminal scrollback optimize..."
PROP="$HOME/.termux/termux.properties"
mkdir -p "$HOME/.termux"
touch "$PROP"
if ! grep -q 'terminal-transcript-rows' "$PROP"; then
    echo "terminal-transcript-rows = 50000" >> "$PROP"
fi
command -v termux-reload-settings >/dev/null 2>&1 && termux-reload-settings >/dev/null 2>&1 || true

echo ""
echo "============================================"
echo "  [+] IKRAM TOOL INSTALLED!"
echo "  [*] Ab naya terminal kholo aur likho:  ikram"
echo "============================================"
