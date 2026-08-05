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

width=52
line() { printf "${1}%*s${C_RESET}\n" "$width" '' | tr ' ' '═'; }

step() { printf "\n${C_CYAN}${C_BOLD}▸ %s${C_RESET}\n" "$1"; }
ok()   { printf "${C_GREEN}${C_BOLD}  ✓ %s${C_RESET}\n" "$1"; }
fail() { printf "${C_RED}${C_BOLD}  ✗ %s${C_RESET}\n" "$1"; }

printf "\n"
line "${C_PINK}"
printf "${C_PINK}${C_BOLD}  ✦  I K R A M   T O O L  ✦${C_RESET}\n"
printf "${C_GOLD}${C_BOLD}      PAK • LUA  MODDING${C_RESET}\n"
printf "${C_DIM}   One-line VIP Installer for Termux${C_RESET}\n"
line "${C_PINK}"

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

cd "$TARGET" && unzip -q -o IkramTool.zip && rm -f IkramTool.zip
ok "Tool installed"

step "Adding 'ikram' command"
RC="$HOME/.bashrc"
if ! grep -q 'ikram()' "$RC" 2>/dev/null; then
    cat >> "$RC" <<'EOF'

# Ikram Tool launcher
ikram() { PYTHONDONTWRITEBYTECODE=1 python3 "$HOME/Ikram_Tool/ikram.pyc" "$@"; }
EOF
fi
ok "'ikram' command ready"

chmod +x "$TARGET/run.sh" "$TARGET/install.sh" 2>/dev/null || true

printf "\n"
line "${C_GREEN}"
printf "${C_GREEN}${C_BOLD}  ✅ IKRAM TOOL INSTALLED!${C_RESET}\n"
printf "${C_GOLD}${C_BOLD}  Run:  ${C_CYAN}ikram${C_RESET}\n"
printf "${C_DIM}  (pehli baar valid KEY maangi jayegi — owner se lo)${C_RESET}\n"
line "${C_GREEN}"
printf "\n"
