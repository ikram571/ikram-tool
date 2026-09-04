#!/data/data/com.termux/files/usr/bin/bash
# =============================================
#  Ikram Tool - One-line Installer (VIP UI)
#  Fresh Termux me sab kuch khud install karta hai
#  (non-root, koi permission nahi chahiye)
#  - Har package ALAG install hota hai (ek fail to
#    baaki nahi rukte) + retry 3x
#  - Overall % progress bar (kitna hua, kitna baaki)
#    taaki lagta nahi ke tool stuck hai
# =============================================
set -u

# TTY check — agar terminal nahi hai (pipe se chala rahe hain) to spinner
# \r spam na kare, sirf plain line print kare (koi crash/stuck nahi)
if [ -t 1 ] && [ -t 0 ]; then
    TTY_MODE=1
else
    TTY_MODE=0
fi

LOG="${TMPDIR:-/data/data/com.termux/files/usr/tmp}/ikram_step.log"

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
warn() { printf "${C_GOLD}${C_BOLD}    ⚠ %s${C_RESET}\n" "$1"; }
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

# ---------------- overall progress bar ----------------
# Har step ek % deta hai. Pkg update/install jaise lambi cheezein
# spinner se chalti hain (stuck nahi lagta), bar us step par jata hai.
PB_W=22
CUR_PCT=0
LAST_PCT=-1
CUR_LABEL=""

_pbar() {  # _pbar PCT LABEL
    local PCT="$1" LABEL="$2"
    if [ "$TTY_MODE" -eq 0 ]; then
        printf "  ▸ %s ... %s%%\n" "$LABEL" "$PCT"
        return
    fi
    local FILLED=$(( PCT * PB_W / 100 ))
    local BAR=""
    local i=0
    while [ "$i" -lt "$FILLED" ]; do BAR="${BAR}█"; i=$((i+1)); done
    while [ "$i" -lt "$PB_W" ]; do BAR="${BAR}░"; i=$((i+1)); done
    printf "\r${C_CYAN}  ⬇ ${LABEL}${C_RESET} [${C_GREEN}${BAR}${C_RESET}] ${C_BOLD}%3s%%${C_RESET}   " "$PCT"
}

# spinner + bar — long command ke dauran animate karta hai
_spin() {  # _spin PCT LABEL PID
    local PCT="$1" LABEL="$2" SPID="$3"
    local FR=('|' '/' '-' '\\')
    local k=0
    while kill -0 "$SPID" 2>/dev/null; do
        if [ "$TTY_MODE" -eq 1 ]; then
            _pbar "$PCT" "${LABEL} ${FR[$((k % 4))]}"
        fi
        k=$((k + 1))
        sleep 0.2
    done
}

run_spin() {  # run_spin PCT LABEL cmd...
    local PCT="$1" LABEL="$2"; shift 2
    _pbar "$PCT" "$LABEL"
    "$@" >$LOG 2>&1 &
    local SPID=$!
    _spin "$PCT" "$LABEL" "$SPID"
    wait "$SPID"
    local RC=$?
    if [ "$RC" -ne 0 ]; then
        tail -6 $LOG 2>/dev/null | sed 's/^/    /'
    fi
    return "$RC"
}

advance() {  # advance PCT "LABEL" — ek step finish, bar update
    CUR_PCT=$1
    CUR_LABEL=$2
    _pbar "$CUR_PCT" "$CUR_LABEL ✓"
    printf "\n"
    CUR_LABEL=""
}

# ---------------- package install (individual + retry) ----------------
install_pkgs() {  # install_pkgs BASE_PCT PCT_STEP "LABEL_PREFIX" pkg...
    local BASE="$1" PCT_STEP="$2" LP="$3"; shift 3
    local total=$# i=1 p
    for p in "$@"; do
        local pct=$(( BASE + (i - 1) * PCT_STEP / total ))
        _pbar "$pct" "${LP} ${p} (${i}/${total})"
        local rc=1 try=1
        while [ "$try" -le 3 ] && [ "$rc" -ne 0 ]; do
            [ "$try" -gt 1 ] && _pbar "$pct" "${LP} ${p} retry ${try}/3"
            pkg install -y "$p" >$LOG 2>&1 &
            local SPID=$!
            _spin "$pct" "${LP} ${p} (${i}/${total})" "$SPID"
            wait "$SPID"
            rc=$?
            try=$((try + 1))
        done
        if [ "$rc" -eq 0 ]; then
            _pbar "$pct" "${LP} ${p} ✓ (${i}/${total})"
            printf "\n"
        else
            _pbar "$pct" "${LP} ${p} ✗"
            printf "\n"
            tail -6 $LOG 2>/dev/null | sed 's/^/    /'
            warn "$p install fail hua — dusre packages jaari rahe."
        fi
        i=$((i + 1))
    done
}

# ---------------- pip install (individual + retry) ----------------
pip_try() {  # pip_try "lib" — break-system-packages ke saath/na ke retry
    local lib="$1"
    pip install "$lib" >$LOG 2>&1 && return 0
    pip install --break-system-packages "$lib" >$LOG 2>&1 && return 0
    pip install --user "$lib" >$LOG 2>&1 && return 0
    return 1
}

install_pip() {  # install_pip BASE_PCT PCT_STEP "LABEL_PREFIX" lib...
    local BASE="$1" PCT_STEP="$2" LP="$3"; shift 3
    local total=$# i=1 p
    for p in "$@"; do
        local pct=$(( BASE + (i - 1) * PCT_STEP / total ))
        _pbar "$pct" "${LP} ${p} (${i}/${total})"
        local rc=1 try=1
        while [ "$try" -le 3 ] && [ "$rc" -ne 0 ]; do
            [ "$try" -gt 1 ] && _pbar "$pct" "${LP} ${p} retry ${try}/3"
            pip_try "$p" &
            local SPID=$!
            _spin "$pct" "${LP} ${p} (${i}/${total})" "$SPID"
            wait "$SPID"
            rc=$?
            try=$((try + 1))
        done
        if [ "$rc" -eq 0 ]; then
            _pbar "$pct" "${LP} ${p} ✓ (${i}/${total})"
            printf "\n"
        else
            _pbar "$pct" "${LP} ${p} ✗"
            printf "\n"
            tail -6 $LOG 2>/dev/null | sed 's/^/    /'
            warn "$p pip install fail hua — tool chalta rahega, kuch features limited."
        fi
        i=$((i + 1))
    done
}

printf "\n${TOP}\n"
printf "${MID}${C_PINK}${C_BOLD}     ✦  I K R A M   T O O L  ✦${C_RESET}${MID}\n"
printf "${MID}${C_GOLD}${C_BOLD}        PAK • LUA  TOOL${C_RESET}${MID}\n"
printf "${BOT}\n"

# phase weights (total 100)
PW_STORAGE=4
PW_UPDATE=8
PW_UPGRADE=10
PW_PKGS=34
PW_PIP=16
PW_DL=16
PW_EXTRACT=6
PW_SETUP=6

# 1) storage
box "$C_CYAN" "📁 Storage permission"
_pbar 0 "Storage permission"
termux-setup-storage >/dev/null 2>&1
printf "\n"
ok "Storage access granted"
advance "$PW_STORAGE" "Storage permission"

# 2) update
box "$C_CYAN" "🔄 Updating packages"
run_spin "$PW_UPDATE" "pkg update" pkg update -y
printf "\n"
ok "Repositories updated"
advance "$PW_UPDATE" "pkg update"

# 3) upgrade (python latest ke liye)
run_spin "$PW_UPGRADE" "pkg upgrade" pkg upgrade -y
printf "\n"
ok "Packages upgraded"
advance "$PW_UPGRADE" "pkg upgrade"

# 4) core packages — EK EK KARKE
box "$C_CYAN" "⬇ Installing core packages (python, git, java, lua...)"
install_pkgs "$PW_UPDATE" "$PW_PKGS" "Installing" \
    python git curl unzip openjdk-17 lua53
advance "$((PW_UPDATE + PW_PKGS))" "Core packages"

if ! command -v python3 >/dev/null 2>&1; then
    printf "\n${C_RED}${C_BOLD}  ✗ python3 install nahi hua!${C_RESET}\n"
    printf "${C_RED}  Internet check karo, phir ye chalayen:${C_RESET}\n"
    printf "${C_GOLD}    pkg update -y && pkg install -y python${C_RESET}\n"
    printf "${C_GOLD}    ikram${C_RESET}\n"
    exit 1
fi

# 5) pip libraries — EK EK KARKE
box "$C_CYAN" "⬇ Installing libraries (rich, crypto, zstd...)"
install_pip "$((PW_UPDATE + PW_PKGS))" "$PW_PIP" "Libraries" \
    rich pycryptodome zstandard gmalg
advance "$((PW_UPDATE + PW_PKGS + PW_PIP))" "Libraries"

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
_pbar "$((PW_UPDATE + PW_PKGS + PW_PIP))" "Downloading tool"
TOTAL=$(curl -sIL "$TOOL_URL" 2>/dev/null | grep -i '^content-length' | tail -1 | tr -dc '0-9')
[ -z "$TOTAL" ] && TOTAL=0
curl -sL -o "$TARGET/IkramTool.zip" "$TOOL_URL" &
CPID=$!
DONE=0
DL_BASE=$((PW_UPDATE + PW_PKGS + PW_PIP))
while kill -0 "$CPID" 2>/dev/null; do
    DONE=$(stat -c%s "$TARGET/IkramTool.zip" 2>/dev/null || echo 0)
    FRAC=$(( TOTAL > 0 ? DONE * 100 / TOTAL : 0 ))
    PCT=$(( DL_BASE + FRAC * PW_DL / 100 ))
    [ "$PCT" -gt $((DL_BASE + PW_DL)) ] && PCT=$((DL_BASE + PW_DL))
    if [ "$TTY_MODE" -eq 0 ]; then
        printf "  ▸ Downloading: $(human "$DONE") / $(human "$TOTAL") ... %3s%%\n" "$PCT"
        sleep 1
        continue
    fi
    FILLED=$(( PCT * PB_W / 100 ))
    BAR=""
    i=0
    while [ "$i" -lt "$FILLED" ]; do BAR="${BAR}█"; i=$((i+1)); done
    while [ "$i" -lt "$PB_W" ]; do BAR="${BAR}░"; i=$((i+1)); done
    printf "\r${C_CYAN}  ⬇ Downloading: $(human "$DONE") / $(human "$TOTAL") [${C_GREEN}${BAR}${C_RESET}] %3s%%${C_RESET}   " "$PCT"
    sleep 0.2
done
wait "$CPID"
DONE=$(stat -c%s "$TARGET/IkramTool.zip" 2>/dev/null || echo 0)
if [ "$TTY_MODE" -eq 0 ]; then
    printf "  ▸ Downloading: $(human "$DONE") / $(human "$TOTAL") ✓ done\n"
else
    printf "\r${C_CYAN}  ⬇ Downloading: $(human "$DONE") / $(human "$TOTAL") ✓ done      ${C_RESET}\n"
fi
if [ "$DONE" -gt 0 ] 2>/dev/null; then
    ok "Tool downloaded ($(human "$DONE"))"
    advance "$((DL_BASE + PW_DL))" "Tool downloaded"
else
    fail "Download failed — internet check karo aur dobara try karo."
    exit 1
fi

# 6) extract + install
box "$C_GOLD" "🧹 Installing tool"
TMPX="$TARGET/.ikram_tmp"
rm -rf "$TMPX" && mkdir -p "$TMPX"
_pbar "$((DL_BASE + PW_DL))" "Extracting tool"
if (cd "$TMPX" && unzip -q -o "$TARGET/IkramTool.zip"); then
    printf "\n"
else
    printf "\n"
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
    advance "$((DL_BASE + PW_DL + PW_EXTRACT))" "Tool installed"
else
    fail "Install fail hua — dobara try karo."
    exit 1
fi

# 7) command setup
box "$C_GOLD" "⚙ Setting up 'ikram' command"
_pbar "$((DL_BASE + PW_DL + PW_EXTRACT))" "Setting up ikram command"
RC="$HOME/.bashrc"
sed -i "/# Ikram Tool launcher/d" "$RC" 2>/dev/null
sed -i "/^ikram *()/d" "$RC" 2>/dev/null
sed -i "/Ikram_Tool\/ikram\.py/d" "$RC" 2>/dev/null
cat >> "$RC" <<'EOF'

# Ikram Tool launcher (ikram_patch.py = poori files A-to-Z load)
ikram() { PYTHONDONTWRITEBYTECODE=1 python3 "$HOME/Ikram_Tool/ikram_patch.py" "$@"; }
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
# patch missing ho to khud repair (poori zip fresh download)
if [ ! -f "$HOME/Ikram_Tool/ikram_patch.py" ]; then
    echo ""
    echo "  ⚠ Tool files missing — khud repair kar raha hoon..."
    mkdir -p "$HOME/Ikram_Tool"
    cd "$HOME/Ikram_Tool"
    curl -sL -o repair.zip "https://github.com/ikram571/ikram-tool/releases/latest/download/IkramTool.zip"
    TMPX="$HOME/Ikram_Tool/.repair"
    rm -rf "$TMPX" && mkdir -p "$TMPX"
    if (cd "$TMPX" && unzip -q -o "$HOME/Ikram_Tool/repair.zip") && [ -f "$TMPX/ikram.pyc" ]; then
        cp -r "$TMPX"/. "$HOME/Ikram_Tool"/ 2>/dev/null
        chmod +x "$HOME/Ikram_Tool/run.sh" 2>/dev/null
        echo "  ✓ Repair done! Tool khul raha hai..."
        exec python3 "$HOME/Ikram_Tool/ikram_patch.py" "$@"
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
        exec python3 "$HOME/Ikram_Tool/ikram_patch.py" "$@"
    fi
    echo "  ✗ Python upgrade nahi ho paya. Ye chalayen:"
    echo "    pkg update -y && pkg upgrade -y"
    echo "    ikram"
    echo ""
    exit 1
fi
    exec python3 "$HOME/Ikram_Tool/ikram_patch.py" "$@"
EOF
chmod +x "$PREFIX/bin/ikram"
printf "\n"
ok "'ikram' command ready (new version)"

chmod +x "$TARGET/run.sh" "$TARGET/install.sh" 2>/dev/null || true
chmod +x "$TARGET/luac_patched" "$TARGET/lua_patched" 2>/dev/null || true

advance 100 "Setup complete"
printf "\n${C_GREEN}╭$(printf '─%.0s' $(seq 1 $W))╮${C_RESET}\n"
printf "${C_GREEN}│${C_RESET}${C_GREEN}${C_BOLD}      ✅ IKRAM TOOL INSTALLED!${C_RESET}${C_GREEN}│${C_RESET}\n"
printf "${C_GREEN}│${C_RESET}${C_GOLD}${C_BOLD}      Run: ${C_CYAN}ikram${C_RESET}${C_GREEN}${C_BOLD}${C_RESET}${C_GREEN}│${C_RESET}\n"
printf "${C_GREEN}│${C_RESET}${C_DIM}      (KEY REQUIRED — owner se lo)${C_RESET}${C_GREEN}│${C_RESET}\n"
printf "${C_GREEN}╰$(printf '─%.0s' $(seq 1 $W))╯${C_RESET}\n"
printf "\n"
