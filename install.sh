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

printf "\n${TOP}\n"
printf "${MID}${C_PINK}${C_BOLD}     ✦  I K R A M   T O O L  ✦${C_RESET}${MID}\n"
printf "${MID}${C_GOLD}${C_BOLD}        PAK • LUA  TOOL${C_RESET}${MID}\n"
printf "${MID}${C_DIM}        Termux me ek line me install${C_RESET}${MID}\n"
printf "${BOT}\n"

step "Storage permission"
termux-setup-storage >/dev/null 2>&1 && ok "Storage access granted" || ok "Storage already set / skipped"

step "Updating packages"
pkg update -y >/dev/null 2>&1 && ok "Repositories updated" || pkg update -y >/dev/null 2>&1

step "Installing core packages (python, git, java, lua...)"
if pkg install -y python git curl unzip openjdk-17 lua53 >/dev/null 2>&1; then
    ok "Core packages installed"
else
    pkg install -y python git curl unzip openjdk-17 lua53 >/dev/null 2>&1
    ok "Core packages installed"
fi

step "Installing Python libraries"
if pip install rich pycryptodome zstandard gmalg >/dev/null 2>&1; then
    ok "Libraries installed"
else
    pip install --break-system-packages rich pycryptodome zstandard gmalg >/dev/null 2>&1
    ok "Libraries installed"
fi

TARGET="$HOME/Ikram_Tool"
step "Downloading tool"
mkdir -p "$TARGET"
if curl -sL -o "$TARGET/IkramTool.zip" \
    "https://github.com/ikram571/ikram-tool/releases/latest/download/IkramTool.zip" \
    && [ -s "$TARGET/IkramTool.zip" ]; then
    ok "Tool downloaded (latest release)"
else
    fail "Download failed — internet check karo aur dobara try karo."
    exit 1
fi

step "Cleaning old files"
find "$TARGET" -mindepth 1 -maxdepth 1 \
    \( -name '*.pyc' -o -name '*.py' -o -name '*.jar' -o -name '*.json' \
       -o -name 'VERSION' -o -name 'INSTRUCTIONS.txt' -o -name 'run.sh' \) \
    -exec rm -rf {} + 2>/dev/null
ok "Old files removed"

cd "$TARGET" && unzip -q -o IkramTool.zip && rm -f IkramTool.zip
ok "Tool installed"

step "Fixing 'ikram' command"
RC="$HOME/.bashrc"
sed -i "/^# Ikram Tool launcher$/d" "$RC" 2>/dev/null
sed -i "/^ikram() { PYTHONDONTWRITEBYTECODE=1 python3 /d" "$RC" 2>/dev/null
sed -i "/^ikram() { python3 /d" "$RC" 2>/dev/null
if ! grep -q 'ikram()' "$RC" 2>/dev/null; then
    cat >> "$RC" <<'EOF'

# Ikram Tool launcher
ikram() { PYTHONDONTWRITEBYTECODE=1 python3 "$HOME/Ikram_Tool/ikram.pyc" "$@"; }
EOF
fi
ok "'ikram' command ready (new version)"

chmod +x "$TARGET/run.sh" "$TARGET/install.sh" 2>/dev/null || true

printf "\n${C_GREEN}╭$(printf '─%.0s' $(seq 1 $W))╮${C_RESET}\n"
printf "${C_GREEN}│${C_RESET}${C_GREEN}${C_BOLD}      ✅ IKRAM TOOL INSTALLED!${C_RESET}${C_GREEN}│${C_RESET}\n"
printf "${C_GREEN}│${C_RESET}${C_GOLD}${C_BOLD}      Run: ${C_CYAN}ikram${C_RESET}${C_GREEN}${C_BOLD}${C_RESET}${C_GREEN}│${C_RESET}\n"
printf "${C_GREEN}│${C_RESET}${C_DIM}      (KEY REQUIRED — owner se lo)${C_RESET}${C_GREEN}│${C_RESET}\n"
printf "${C_GREEN}╰$(printf '─%.0s' $(seq 1 $W))╯${C_RESET}\n"
printf "\n"
