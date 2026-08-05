#!/data/data/com.termux/files/usr/bin/bash
# =============================================
#  Ikram Tool - One-line Installer
#  Fresh Termux me sab kuch khud install karta hai
#  (non-root, koi permission nahi chahiye)
# =============================================
set -u

BANNER="
===============================================
          ✦ IKRAM TOOL INSTALLER ✦
        PAK / LUA Modding Tool for Termux
===============================================
"
echo "$BANNER"

echo "[*] Storage permission de rahe hain (popup me ALLOW dabao)..."
termux-setup-storage >/dev/null 2>&1 || echo "    (skip, permission already hai ya skip kiya)"

echo "[*] Packages update ho rahe hain..."
pkg update -y >/dev/null 2>&1 || pkg update -y

echo "[*] Zaroori packages install ho rahe hain (python, git, java, lua...)"
pkg install -y python git curl unzip openjdk-17 lua53 >/dev/null 2>&1 \
    || pkg install -y python git curl unzip openjdk-17 lua53

echo "[*] Python libraries install ho rahi hain..."
pip install rich pycryptodome zstandard gmalg >/dev/null 2>&1 \
    || pip install --break-system-packages rich pycryptodome zstandard gmalg

TARGET="$HOME/Ikram_Tool"
echo "[*] Tool download + install ho raha hai -> $TARGET"
mkdir -p "$TARGET"
curl -sL -o "$TARGET/IkramTool.zip" \
    "https://github.com/ikram571/ikram-tool/releases/latest/download/IkramTool.zip"
if [ ! -s "$TARGET/IkramTool.zip" ]; then
    echo "[!] Download fail hua. Internet check karo aur dobara try karo."
    exit 1
fi
cd "$TARGET" && unzip -q -o IkramTool.zip && rm -f IkramTool.zip

echo "[*] 'ikram' command add ho raha hai..."
RC="$HOME/.bashrc"
if ! grep -q 'ikram()' "$RC" 2>/dev/null; then
    cat >> "$RC" <<'EOF'

# Ikram Tool launcher
ikram() { PYTHONDONTWRITEBYTECODE=1 python3 "$HOME/Ikram_Tool/ikram.pyc" "$@"; }
EOF
fi

chmod +x "$TARGET/run.sh" "$TARGET/install.sh" 2>/dev/null || true

echo ""
echo "==============================================="
echo "  [OK] Ikram Tool installed!"
echo "==============================================="
echo "  Ab is command se tool kholo:"
echo "        ikram"
echo ""
echo "  (pehli baar valid KEY maangi jayegi - owner se lo)"
echo "==============================================="
