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

C_RESET=$(printf '\033[0m')
C_PINK=$(printf '\033[1;38;5;201m')
C_CYAN=$(printf '\033[1;38;5;51m')
C_GOLD=$(printf '\033[1;38;5;220m')
C_GREEN=$(printf '\033[1;38;5;82m')
C_RED=$(printf '\033[1;38;5;196m')
C_DIM=$(printf '\033[2;38;5;244m')
C_BOLD=$(printf '\033[1m')

W=50
TOP="${C_PINK}╭$(printf '─%.0s' $(seq 1 $W))╮${C_RESET}"
MID="${C_PINK}│${C_RESET}"
BOT="${C_PINK}╰$(printf '─%.0s' $(seq 1 $W))╯${C_RESET}"

# -------- IKRAM TOOL style splash (matches the tool's startup) --------
tool_splash() {
    local STAR='✦'
    local LINE=""
    local i=0
    while [ "$i" -lt 66 ]; do LINE="${LINE}${STAR}"; i=$((i+1)); done
    printf "\n${C_GOLD}${LINE}${C_RESET}\n"
    printf "\n${C_BOLD}                                    IKRAM TOOL${C_RESET}\n"
    printf "${C_CYAN}                               📦 PAK   •   📜 LUA${C_RESET}\n"
    printf "\n${C_GOLD}${LINE}${C_RESET}\n"
    printf "\n"
}

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

# 1) tool splash (matches the tool)
tool_splash
# Press-Enter prompt ONLY if stdin is a real TTY. Under `curl ... | bash`
# stdin is the script pipe — an inner `read` there can swallow the next
# chunk of the script (bash hasn't buffered it yet) = "starts, stops mid-way".
if [ -t 0 ]; then
    step "Press Enter to start the installation..."
    read -r dummy 2>/dev/null || true
fi

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
DL_BASE=$((PW_UPDATE + PW_PKGS + PW_PIP))
_pbar "$DL_BASE" "Downloading tool"
TOTAL=$(curl -sIL "$TOOL_URL" 2>/dev/null | grep -i '^content-length' | tail -1 | tr -dc '0-9')
[ -z "$TOTAL" ] && TOTAL=0
DONE=0
ATT=0
while [ "$ATT" -lt 3 ] && [ "$DONE" -eq 0 ]; do
    ATT=$((ATT + 1))
    rm -f "$TARGET/IkramTool.zip"
    curl -fL -s -o "$TARGET/IkramTool.zip" "$TOOL_URL" &
    CPID=$!
    while kill -0 "$CPID" 2>/dev/null; do
        CUR=$(stat -c%s "$TARGET/IkramTool.zip" 2>/dev/null || echo 0)
        FRAC=$(( TOTAL > 0 ? CUR * 100 / TOTAL : 0 ))
        [ "$FRAC" -gt 100 ] && FRAC=100
        PCT=$(( DL_BASE + FRAC * PW_DL / 100 ))
        [ "$PCT" -gt $((DL_BASE + PW_DL)) ] && PCT=$((DL_BASE + PW_DL))
        if [ "$TTY_MODE" -eq 0 ]; then
            printf "  ▸ Downloading (try $ATT): $(human "$CUR") / $(human "$TOTAL") ... %3s%%\n" "$FRAC"
            sleep 1
            continue
        fi
        FILLED=$(( PCT * PB_W / 100 ))
        BAR=""
        i=0
        while [ "$i" -lt "$FILLED" ]; do BAR="${BAR}█"; i=$((i+1)); done
        while [ "$i" -lt "$PB_W" ]; do BAR="${BAR}░"; i=$((i+1)); done
        printf "\r${C_CYAN}  ⬇ Downloading (try $ATT): $(human "$CUR") / $(human "$TOTAL") [${C_GREEN}${BAR}${C_RESET}] %3s%%${C_RESET}   " "$FRAC"
        sleep 0.2
    done
    wait "$CPID"
    DONE=$(stat -c%s "$TARGET/IkramTool.zip" 2>/dev/null || echo 0)
    MAGIC=$(head -c2 "$TARGET/IkramTool.zip" 2>/dev/null | tr -d '\0')
    if [ "$MAGIC" != "PK" ] || { [ "$TOTAL" -gt 0 ] && [ "$DONE" -lt "$TOTAL" ]; }; then
        DONE=0
        if [ "$ATT" -lt 3 ]; then
            printf "\r${C_GOLD}  ⬇ Download incomplete — retry ${ATT}/3...${C_RESET}\n"
        fi
    fi
done
printf "\r${C_CYAN}  ⬇ Downloading: $(human "$DONE") / $(human "$TOTAL") ✓ done      ${C_RESET}\n"
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
rm -rf "$TARGET/.engine"
# drop/result hamesha real — kabhi delete NAHI (user files hain)
mkdir -p "$TARGET/drop" "$TARGET/result"
# temp se copy -> .engine/ (engine hidden; drop/result root pe real)
cp -r "$TMPX"/. "$TARGET/.engine"/ 2>/dev/null
rm -rf "$TMPX" "$TARGET/IkramTool.zip"
# DROP/RESULT skeleton — hamesha banayein (fresh install pe khali hota hai)
mkdir -p "$TARGET/.engine" "$TARGET/drop/inject" "$TARGET/drop/lua" "$TARGET/drop/pak" \
         "$TARGET/result/injected" "$TARGET/result/extracted" \
         "$TARGET/result/lua" "$TARGET/result/Repacked" "$TARGET/result/CostomPak"
# engine ab .engine/ me — DROP/RESULT symlink (engine __file__-relative me root drop/result)
ln -sfn "$TARGET/drop" "$TARGET/.engine/DROP"
ln -sfn "$TARGET/result" "$TARGET/.engine/RESULT"
if [ -f "$TARGET/.engine/ikram.pyc" ] || [ -f "$TARGET/ikram.pyc" ]; then
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
ikram() { PYTHONDONTWRITEBYTECODE=1 python3 "$HOME/Ikram_Tool/.engine/ikram_patch.py" "$@"; }
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
if [ ! -f "$HOME/Ikram_Tool/.engine/ikram_patch.py" ]; then
    echo ""
    echo "  ⚠ Tool files missing — khud repair kar raha hoon..."
    mkdir -p "$HOME/Ikram_Tool/.engine"
    cd "$HOME/Ikram_Tool"
    curl -sL -o repair.zip "https://github.com/ikram571/ikram-tool/releases/latest/download/IkramTool.zip"
    TMPX="$HOME/Ikram_Tool/.engine/.repair"
    rm -rf "$TMPX" && mkdir -p "$TMPX"
    if (cd "$TMPX" && unzip -q -o "$HOME/Ikram_Tool/.engine/repair.zip") && [ -f "$TMPX/ikram.pyc" ]; then
        cp -r "$TMPX"/. "$HOME/Ikram_Tool/.engine"/ 2>/dev/null
        chmod +x "$HOME/Ikram_Tool/.engine/run.sh" "$HOME/Ikram_Tool/run.sh" 2>/dev/null
        echo "  ✓ Repair done! Tool khul raha hai..."
        exec python3 "$HOME/Ikram_Tool/.engine/ikram_patch.py" "$@"
    fi
    rm -rf "$TMPX" "$HOME/Ikram_Tool/.engine/repair.zip"
    echo "  ✗ Repair fail. Dobara install karo:"
    echo "    curl -fL https://cdn.jsdelivr.net/gh/ikram571/ikram-tool@main/install.sh | bash"
    echo ""
    exit 1
fi
# pyc magic check — python purana ho to khud upgrade
MAGIC_NEEDED=$(python3 -c "import importlib.util;print(importlib.util.MAGIC_NUMBER.hex())" 2>/dev/null)
MAGIC_HAVE=$(python3 -c "
import struct
p = open('$HOME/Ikram_Tool/.engine/ikram.pyc','rb').read(4)
print(p.hex())
" 2>/dev/null)
if [ -n "$MAGIC_HAVE" ] && [ "$MAGIC_HAVE" != "$MAGIC_NEEDED" ]; then
    echo ""
    echo "  ⬆ Python purana hai — upgrade kar raha hoon..."
    pkg update -y >/dev/null 2>&1
    pkg upgrade -y python 2>&1 | tail -3
    if [ "$(python3 -c "import importlib.util;print(importlib.util.MAGIC_NUMBER.hex())" 2>/dev/null)" = "$MAGIC_NEEDED" ]; then
        echo "  ✓ Python upgrade ho gaya! Tool khul raha hai..."
        exec python3 "$HOME/Ikram_Tool/.engine/ikram_patch.py" "$@"
    fi
    echo "  ✗ Python upgrade nahi ho paya. Ye chalayen:"
    echo "    pkg update -y && pkg upgrade -y"
    echo "    ikram"
    echo ""
    exit 1
fi
    exec python3 "$HOME/Ikram_Tool/.engine/ikram_patch.py" "$@"
EOF
chmod +x "$PREFIX/bin/ikram"
printf "\n"
ok "'ikram' command ready (new version)"

chmod +x "$TARGET/.engine/run.sh" "$TARGET/.engine/install.sh" "$TARGET/run.sh" "$TARGET/install.sh" 2>/dev/null || true
chmod +x "$TARGET/.engine/luac_patched" "$TARGET/.engine/lua_patched" "$TARGET/luac_patched" "$TARGET/lua_patched" 2>/dev/null || true
chmod +x "$TARGET/.engine/repak" "$TARGET/.engine/unluac_rs" "$TARGET/repak" "$TARGET/unluac_rs" 2>/dev/null || true

# 7B) post-install boot test (shows key prompt + main menu once)
box "$C_GOLD" "🚀 Final boot test"
_pbar "$((DL_BASE + PW_DL + PW_EXTRACT))" "Booting tool once"
if [ -f "$TARGET/.engine/ikram_patch.py" ] || [ -f "$TARGET/ikram_patch.py" ]; then
    IKRAM_SRC="$TARGET/.engine/ikram_patch.py"
    [ -f "$IKRAM_SRC" ] || IKRAM_SRC="$TARGET/ikram_patch.py"
    BOOT_PLAN="$TARGET/.boot_plan.$$"
    BOOT_PY="$TARGET/.boot_drv.$$.py"
    printf 'FREETOOL\n0\n' > "$BOOT_PLAN"
    cat > "$BOOT_PY" <<'PY'
import os, builtins, traceback
path = os.environ["IKRAM_PATCH"]
src = open(path, encoding="utf-8").read()
g = {"__name__": "ikram_patch_boot", "__file__": path}
exec(compile(src, path, "exec"), g)
plan = [ln.rstrip("\n") for ln in open(os.environ["IKRAM_PLAN"])]
idx = {"i": 0}
def _inp(p=""):
    if idx["i"] < len(plan):
        a = plan[idx["i"]]; idx["i"] += 1
    else:
        a = ""
    return a
builtins.input = _inp
try:
    g["ikram"].main()
except SystemExit:
    pass
except Exception:
    tb = os.environ.get("IKRAM_TB")
    if tb:
        try:
            open(tb, "a").write(traceback.format_exc())
        except Exception:
            pass
else:
    try:
        open(os.environ.get("IKRAM_OK", ""), "a").close()
    except Exception:
        pass
PY
    IKRAM_PATCH="$IKRAM_SRC" \
    IKRAM_PLAN="$BOOT_PLAN" \
    IKRAM_TB="$TARGET/.boot_tb.log" \
    IKRAM_OK="$TARGET/.boot_ok.$$" \
    python3 "$BOOT_PY"
    if [ -f "$TARGET/.boot_ok.$$" ]; then
        printf "\n"
        ok "Boot test passed - Key prompt + Main menu OK"
    else
        printf "\n"
        fail "Boot test FAILED - $TARGET/.boot_tb.log me error dekho"
    fi
    rm -f "$BOOT_PLAN" "$BOOT_PY" "$TARGET/.boot_ok.$$" "$TARGET/.boot_tb.log" 2>/dev/null
else
    warn "Boot test skipped (ikram_patch.py nahi mili)"
fi
advance 100 "Boot test"

advance 100 "Setup complete"
V_VER=$(cat "$TARGET/.engine/VERSION" 2>/dev/null || cat "$TARGET/VERSION" 2>/dev/null || echo "latest")
BW=$((W - 2))
# right-pad each line so the box closes flush (tool-style VIP finish)
pad_line() { local txt="$1"; local L="${#txt}"; local P=$((BW - L)); [ $P -lt 1 ] && P=1; printf '%s%s%s' "$txt" "$(printf '%*s' $P '')" "${C_GREEN}│${C_RESET}"; }
printf "\n${C_GREEN}╭$(printf '─%.0s' $(seq 1 $BW))╮${C_RESET}\n"
printf "${C_GREEN}│${C_RESET}%s\n" "$(pad_line "  ${C_GREEN}${C_BOLD}✅ IKRAM TOOL INSTALLED!${C_RESET}")"
printf "${C_GREEN}│${C_RESET}%s\n" "$(pad_line "  ${C_GOLD}${C_BOLD}Now wait for key...${C_RESET}")"
printf "${C_GREEN}│${C_RESET}%s\n" "$(pad_line "  ${C_DIM}(KEY REQUIRED - owner se lo)${C_RESET}")"
printf "${C_GREEN}│${C_RESET}%s\n" "$(pad_line "  ${C_DIM}Version: ${C_GOLD}${C_BOLD}${V_VER}${C_RESET}")"
printf "${C_GREEN}│${C_RESET}%s\n" "$(pad_line "  ${C_GOLD}${C_BOLD}Run: ${C_CYAN}${C_BOLD}ikram${C_RESET}")"
printf "${C_GREEN}╰$(printf '─%.0s' $(seq 1 $BW))╯${C_RESET}\n"
printf "\n"
