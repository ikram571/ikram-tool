#!/data/data/com.termux/files/usr/bin/bash
# =============================================
#  Ikram Tool - One-line Installer (VIP UI)
#  Fresh Termux me sab kuch khud install karta hai
#  (non-root, koi permission nahi chahiye)
# =============================================
set -u

C_RESET='\033[0m'
C_PINK='\033[1;38;5;201m'
C_CYAN='\033[1;38;5;51m'
C_GOLD='\033[1;38;5;220m'
C_GREEN='\033[1;38;5;82m'
C_RED='\033[1;38;5;196m'
C_DIM='\033[2;38;5;244m'
C_BOLD='\033[1m'

W=50
TOP="${C_PINK}╭$(printf '─%.0s' $(seq 1 $W))╮${C_RESET}"
MID="${C_PINK}│${C_RESET}"
BOT="${C_PINK}╰$(printf '─%.0s' $(seq 1 $W))╯${C_RESET}"

step() { printf "\n${C_CYAN}${C_BOLD}  ▸ %s${C_RESET}\n" "$1"; }
ok()   { printf "${C_GREEN}${C_BOLD}    ✓ %s${C_RESET}\n" "$1"; }
fail() { printf "${C_RED}${C_BOLD}    ✗ %s${C_RESET}\n" "$1"; }

box() {
    local COLOR="$1"
    local TITLE="$2"
    local BW=$((W - 4))
    local TITLE_LEN=${#TITLE}
    local PAD=$((BW - TITLE_LEN - 4))
    [ $PAD -lt 1 ] && PAD=1
    local PADDING=$(printf '%*s' $PAD '')
    printf "\n${COLOR}╭$(printf '─%.0s' $(seq 1 $BW))╮${C_RESET}\n"
    printf "${COLOR}│${C_RESET}  ${COLOR}${C_BOLD}${TITLE}${C_RESET}${PADDING}${COLOR}│${C_RESET}\n"
    printf "${COLOR}╰$(printf '─%.0s' $(seq 1 $BW))╯${C_RESET}\n"
}

printf "\n${TOP}\n"
printf "${MID}${C_PINK}${C_BOLD}     ✦  I K R A M   T O O L  ✦${C_RESET}${MID}\n"
printf "${MID}${C_GOLD}${C_BOLD}        PAK • LUA  TOOL${C_RESET}${MID}\n"
printf "${BOT}\n"

box "$C_CYAN" "📁 Storage permission"
termux-setup-storage >/dev/null 2>&1 && ok "Storage access granted" || ok "Storage already set / skipped"

box "$C_CYAN" "🔄 Updating packages"
pkg update -y 2>&1 | tail -5
pkg upgrade -y 2>&1 | tail -5
ok "Repositories + packages updated (python latest)"

box "$C_CYAN" "⬇ Installing: python, git, curl, unzip, java, lua..."
pkg install -y python git curl unzip openjdk-17 lua53 2>&1 | tail -8 || \
    pkg install -y python git curl unzip openjdk-17 lua53 2>&1 | tail -8
ok "Core packages installed"

box "$C_CYAN" "⬇ Installing: rich, pycryptodome, zstandard, gmalg"
if pip install rich pycryptodome zstandard gmalg 2>&1 | tail -6; then
    :
else
    pip install --break-system-packages rich pycryptodome zstandard gmalg 2>&1 | tail -6
fi
ok "Libraries installed"

TARGET="$HOME/Ikram_Tool"
box "$C_CYAN" "⬇ Downloading tool"
mkdir -p "$TARGET"
if curl -sL -o "$TARGET/IkramTool.zip" \
    "https://github.com/ikram571/ikram-tool/releases/latest/download/IkramTool.zip" \
    && [ -s "$TARGET/IkramTool.zip" ]; then
    ok "Tool downloaded (latest release)"
else
    fail "Download failed — internet check karo aur dobara try karo."
    exit 1
fi

box "$C_GOLD" "🧹 Cleaning old files"
find "$TARGET" -mindepth 1 -maxdepth 1 \
    \( -name '*.pyc' -o -name '*.py' -o -name '*.jar' -o -name '*.json' \
       -o -name 'VERSION' -o -name 'INSTRUCTIONS.txt' -o -name 'run.sh' \) \
    -exec rm -rf {} + 2>/dev/null
ok "Old files removed"

cd "$TARGET" && unzip -q -o IkramTool.zip && rm -f IkramTool.zip
ok "Tool installed"

box "$C_GOLD" "⚙ Setting up 'ikram' command"
RC="$HOME/.bashrc"
sed -i "/# Ikram Tool launcher/d" "$RC" 2>/dev/null
sed -i "/^ikram *()/d" "$RC" 2>/dev/null
sed -i "/Ikram_Tool\/ikram\.py/d" "$RC" 2>/dev/null
cat >> "$RC" <<'EOF'

# Ikram Tool launcher
ikram() { PYTHONDONTWRITEBYTECODE=1 python3 "$HOME/Ikram_Tool/ikram.pyc" "$@"; }
EOF
# real executable - bashrc function reload na lage, PATH me hamesha ready
cat > "$PREFIX/bin/ikram" <<'EOF'
#!/data/data/com.termux/files/usr/bin/bash
export PYTHONDONTWRITEBYTECODE=1
exec python3 "$HOME/Ikram_Tool/ikram.pyc" "$@"
EOF
chmod +x "$PREFIX/bin/ikram"
ok "'ikram' command ready (new version)"

chmod +x "$TARGET/run.sh" "$TARGET/install.sh" 2>/dev/null || true

printf "\n${C_GREEN}╭$(printf '─%.0s' $(seq 1 $W))╮${C_RESET}\n"
printf "${C_GREEN}│${C_RESET}${C_GREEN}${C_BOLD}      ✅ IKRAM TOOL INSTALLED!${C_RESET}${C_GREEN}│${C_RESET}\n"
printf "${C_GREEN}│${C_RESET}${C_GOLD}${C_BOLD}      Run: ${C_CYAN}ikram${C_RESET}${C_GREEN}${C_BOLD}${C_RESET}${C_GREEN}│${C_RESET}\n"
printf "${C_GREEN}│${C_RESET}${C_DIM}      (KEY REQUIRED — owner se lo)${C_RESET}${C_GREEN}│${C_RESET}\n"
printf "${C_GREEN}╰$(printf '─%.0s' $(seq 1 $W))╯${C_RESET}\n"
printf "\n"
