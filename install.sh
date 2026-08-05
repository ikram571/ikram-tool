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
for try in 1 2 3; do
    pkg install -y python git curl unzip openjdk-17 lua53 2>&1 | tail -8
    if command -v python3 >/dev/null 2>&1; then
        break
    fi
    printf "${C_RED}${C_BOLD}    python3 nahi mila (try %s/3) — dobara try kar raha hoon...${C_RESET}\n" "$try"
    sleep 2
done
if ! command -v python3 >/dev/null 2>&1; then
    printf "\n${C_RED}${C_BOLD}  ✗ python3 install nahi hua!${C_RESET}\n"
    printf "${C_RED}  Internet check karo, phir ye chalayen:${C_RESET}\n"
    printf "${C_GOLD}    pkg update -y && pkg install -y python${C_RESET}\n"
    printf "${C_GOLD}    ikram${C_RESET}\n"
    exit 1
fi
ok "Core packages installed"

box "$C_CYAN" "⬇ Installing: rich, pycryptodome, zstandard, gmalg"
if pip install rich pycryptodome zstandard gmalg 2>&1 | tail -6; then
    :
else
    pip install --break-system-packages rich pycryptodome zstandard gmalg 2>&1 | tail -6
fi
ok "Libraries installed"

human() {
    local B="$1"
    if [ "$B" -ge 1048576 ] 2>/dev/null; then
        awk "BEGIN{printf \"%.1f MB\", $B/1048576}"
    elif [ "$B" -ge 1024 ] 2>/dev/null; then
        awk "BEGIN{printf \"%.0f KB\", $B/1024}"
    else
        printf "%s B" "$B"
    fi
}

TARGET="$HOME/Ikram_Tool"
box "$C_CYAN" "⬇ Downloading tool"
mkdir -p "$TARGET"
TOOL_URL="https://github.com/ikram571/ikram-tool/releases/latest/download/IkramTool.zip"
TOTAL=$(curl -sIL "$TOOL_URL" 2>/dev/null | grep -i '^content-length' | tail -1 | tr -dc '0-9')
[ -z "$TOTAL" ] && TOTAL=0
curl -sL -o "$TARGET/IkramTool.zip" "$TOOL_URL" &
CPID=$!
DONE=0
FIRST=1
draw_box() {
    printf "\r${C_CYAN}  ╭──────────────────────────────╮\n${C_RESET}"
    printf "${C_CYAN}  │${C_RESET}  ⬇  Downloading tool       ${C_CYAN}│\n${C_RESET}"
    printf "${C_CYAN}  │${C_RESET}  [${BAR}] %3s%%      ${C_CYAN}│\n${C_RESET}" "$PCT"
    printf "${C_CYAN}  │${C_RESET}  Downloading: $(human "$DONE")         ${C_CYAN}│\n${C_RESET}"
    printf "${C_CYAN}  │${C_RESET}  Size: $(human "$TOTAL")              ${C_CYAN}│\n${C_RESET}"
    printf "${C_CYAN}  ╰──────────────────────────────╯${C_RESET}"
}
while kill -0 "$CPID" 2>/dev/null; do
    DONE=$(stat -c%s "$TARGET/IkramTool.zip" 2>/dev/null || echo 0)
    PCT=$(( TOTAL > 0 ? DONE * 100 / TOTAL : 0 ))
    FILLED=$(( PCT * 18 / 100 ))
    BAR=""
    i=0
    while [ "$i" -lt "$FILLED" ]; do BAR="${BAR}█"; i=$((i+1)); done
    i=$FILLED
    while [ "$i" -lt 18 ]; do BAR="${BAR}░"; i=$((i+1)); done
    if [ "$FIRST" = "1" ]; then
        FIRST=0
        draw_box
    else
        printf "\033[6A"
        draw_box
    fi
    sleep 0.2
done
wait "$CPID"
DONE=$(stat -c%s "$TARGET/IkramTool.zip" 2>/dev/null || echo 0)
printf "\n"
if [ "$DONE" -gt 0 ] 2>/dev/null; then
    ok "Tool downloaded ($(human "$DONE"))"
else
    fail "Download failed — internet check karo aur dobara try karo."
    exit 1
fi

box "$C_GOLD" "🧹 Installing tool"
# pehle temp me extract + verify — taaki pyc delete hone ke baad kuch fail na ho
TMPX="$TARGET/.ikram_tmp"
rm -rf "$TMPX" && mkdir -p "$TMPX"
if ! (cd "$TMPX" && unzip -q -o "$TARGET/IkramTool.zip"); then
    fail "Extract fail hua — dobara try karo."
    rm -rf "$TMPX" "$TARGET/IkramTool.zip"
    exit 1
fi
if [ ! -f "$TMPX/ikram.pyc" ]; then
    fail "ikram.pyc zip me nahi mila — release theek nahi."
    rm -rf "$TMPX" "$TARGET/IkramTool.zip"
    exit 1
fi
# purani files clean (ab safe hai — naya unzip ho chuka)
find "$TARGET" -mindepth 1 -maxdepth 1 \
    \( -name '*.pyc' -o -name '*.py' -o -name '*.jar' -o -name '*.json' \
       -o -name 'VERSION' -o -name 'INSTRUCTIONS.txt' -o -name 'run.sh' \
       -o -name '.ikram_update*' \) \
    -exec rm -rf {} + 2>/dev/null
# temp se copy (DROP/RESULT already hai, overwrite karna zaroori nahi)
cp -r "$TMPX"/. "$TARGET"/ 2>/dev/null
rm -rf "$TMPX" "$TARGET/IkramTool.zip"
if [ -f "$TARGET/ikram.pyc" ]; then
    ok "Tool installed"
else
    fail "Install fail hua — dobara try karo."
    exit 1
fi

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
if ! command -v python3 >/dev/null 2>&1; then
    echo ""
    echo "  python3 not found! Install karo:"
    echo "    pkg update -y && pkg install -y python"
    echo ""
    exit 1
fi
# pyc missing ho to khud repair
if [ ! -f "$HOME/Ikram_Tool/ikram.pyc" ]; then
    echo ""
    echo "  ⚠ Tool files missing — khud repair kar raha hoon..."
    mkdir -p "$HOME/Ikram_Tool"
    cd "$HOME/Ikram_Tool"
    curl -sL -o repair.zip "https://github.com/ikram571/ikram-tool/releases/latest/download/IkramTool.zip"
    TMPX="$HOME/Ikram_Tool/.repair"
    rm -rf "$TMPX" && mkdir -p "$TMPX"
    if (cd "$TMPX" && unzip -q -o "$HOME/Ikram_Tool/repair.zip") && [ -f "$TMPX/ikram.pyc" ]; then
        cp -r "$TMPX"/. "$HOME/Ikram_Tool"/ 2>/dev/null
        echo "  ✓ Repair done! Tool khul raha hai..."
        exec python3 "$HOME/Ikram_Tool/ikram.pyc" "$@"
    fi
    rm -rf "$TMPX" "$HOME/Ikram_Tool/repair.zip"
    echo "  ✗ Repair fail. Dobara install karo:"
    echo "    curl -sL https://raw.githubusercontent.com/ikram571/ikram-tool/main/install.sh | bash"
    echo ""
    exit 1
fi
# pyc magic check — python purana ho to khud upgrade
MAGIC_NEEDED=$(python3 -c "import importlib.util;print(importlib.util.MAGIC_NUMBER.hex())" 2>/dev/null)
MAGIC_HAVE=$(python3 -c "
import struct
p = open('$HOME/Ikram_Tool/ikram.pyc','rb').read(4)
print(p.hex())
" 2>/dev/null)
if [ -n "$MAGIC_HAVE" ] && [ "$MAGIC_HAVE" != "$MAGIC_NEEDED" ]; then
    echo ""
    echo "  ⬆ Python purana hai — upgrade kar raha hoon..."
    pkg update -y >/dev/null 2>&1
    pkg upgrade -y python 2>&1 | tail -3
    if [ "$(python3 -c "import importlib.util;print(importlib.util.MAGIC_NUMBER.hex())" 2>/dev/null)" = "$MAGIC_NEEDED" ]; then
        echo "  ✓ Python upgrade ho gaya! Tool khul raha hai..."
        exec python3 "$HOME/Ikram_Tool/ikram.pyc" "$@"
    fi
    echo "  ✗ Python upgrade nahi ho paya. Ye chalayen:"
    echo "    pkg update -y && pkg upgrade -y"
    echo "    ikram"
    echo ""
    exit 1
fi
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
