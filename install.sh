#!/data/data/com.termux/files/usr/bin/bash
# ============================================================
#  IKRAM TOOL - ONE LINE INSTALLER
#  Ye file copy karo, Termux me paste karo, sab install ho
#  jayega (tool + dependencies + ikram command).
# ============================================================
set -e

BANNER="
  ██╗  ██╗██╗  ██╗██████╗  █████╗ ███╗   ███╗
  ██║ ██╔╝██║  ██║██╔══██╗██╔══██╗████╗ ████║
  █████╔╝ ███████║██████╔╝███████║██╔████╔██║
  ██╔═██╗ ██╔══██║██╔══██╗██╔══██║██║╚██╔╝██║
  ██║  ██╗██║  ██║██║  ██║██║  ██║██║ ╚═╝ ██║
  ╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝╚═╝     ╚═╝
       IKRAM TOOL - PAK / OBB / LUA MODDING TOOL
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
rm -rf "$TARGET"
mkdir -p "$TARGET"
cd "$TARGET"
ZIP_NAME=$(curl -sI "$LATEST" | grep -i 'location:' | sed 's/.*tag\///' | tr -d '\r')
if [ -z "$ZIP_NAME" ]; then ZIP_NAME="v1.0.1"; fi
curl -sL -o tool.zip "$API/ikram-tool-$ZIP_NAME.zip"
unzip -o tool.zip -d . >/dev/null
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
if ! grep -q 'ikram()' "$RC" 2>/dev/null; then
    cat >> "$RC" <<'EOF'

# Ikram Tool launcher
ikram() { python3 "$HOME/Ikram_Tool/ikram.py" "$@"; }
EOF
fi

echo ""
echo "============================================"
echo "  [+] IKRAM TOOL INSTALLED!"
echo "  [*] Ab naya terminal kholo aur likho:  ikram"
echo "============================================"
