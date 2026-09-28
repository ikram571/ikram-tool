#!/data/data/com.termux/files/usr/bin/bash
# =============================================
#  Ikram Tool - One-line Installer (VIP UI)
#  Installs everything by itself on a fresh Termux
#  (non-root, no permissions needed)
#  - Every package installs SEPARATELY (one fails, the
#    others continue) + retry 3x
#  - Overall % progress bar (how much done, how much left)
#    so the tool never looks stuck
# =============================================
set -u

# `curl ... | bash` phone-fail fixes (V114):
#  1) PREFIX guard (for set -u) + apt NONINTERACTIVE — conffile/dpkg
#     prompts must never eat the piped script bytes (that was the
#     "stops halfway" phone-fail).
#  2) every pkg/pip/unzip call gets `</dev/null` — no prompt can take an
#     answer from the (piped) stdin.
PREFIX="${PREFIX:-/data/data/com.termux/files/usr}"
export DEBIAN_FRONTEND=noninteractive

# TTY check — only STDOUT is looked at (decides bar/print format).
# There used to be `[ -t 0 ]` too → with `curl|bash` stdin is always a pipe,
# so TTY_MODE=0 → silent multi-minute gap on slow phones = "install stuck".
# The `read` call has its own separate `[ -t 0 ]` guard below.
if [ -t 1 ]; then
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

# ---------------- system info / checks (V114) ----------------
sys_info() {
    local arch cpu android storage_ok
    arch=$(uname -m 2>/dev/null || echo "unknown")
    cpu=$(getprop ro.product.cpu.abi 2>/dev/null)
    [ -z "$cpu" ] && cpu=$(getprop ro.product.cpu.abilist0 2>/dev/null)
    [ -z "$cpu" ] && cpu="termux-native"
    android=$(getprop ro.build.version.release 2>/dev/null)
    [ -z "$android" ] && android=$(getprop ro.build.version.sdk 2>/dev/null)
    [ -z "$android" ] && android="n/a"
    box "$C_GOLD" "⚙ SYSTEM (V114)"
    printf "${C_BOLD}  • Arch    : ${C_CYAN}%s${C_RESET}\n" "$arch"
    printf "${C_BOLD}  • CPU ABI : ${C_CYAN}%s${C_RESET}\n" "$cpu"
    printf "${C_BOLD}  • Android : ${C_CYAN}%s${C_RESET}\n" "$android"
    case "$arch" in
        armv7l|armv8l|armv6l|arm)
            printf "${C_DIM}  • Note    : 32-bit phone — Termux now officially supports\n"
            printf "${C_DIM}              only 64-bit (aarch64). If Python is not on the\n"
            printf "${C_DIM}              mirror, the tool will not run.\n"
            printf "${C_CYAN}              Best-effort install continuing...${C_RESET}\n"
            ;;
    esac
    local space_kb
    space_kb=$(df -P "$PREFIX" 2>/dev/null | awk 'NR==2{print $4}')
    if [ -n "$space_kb" ] && [ "${space_kb:-0}" -lt 204800 ]; then
        printf "${C_GOLD}  • Storage : LOW SPACE (<200MB free) — python/java\n"
        printf "${C_GOLD}             install may fail. Free up space first.${C_RESET}\n"
    else
        printf "${C_DIM}  • Space   : ~%s GB free ($PREFIX)${C_RESET}\n" \
            "$(awk -v k="${space_kb:-0}" 'BEGIN{printf "%.1f", k/1048576}')"
    fi
    storage_ok=0
    if [ -d "$HOME/storage/shared" ] && [ -w "$HOME/storage/shared" ]; then
        storage_ok=1
    fi
    if [ "$storage_ok" -eq 1 ]; then
        printf "${C_BOLD}  • Storage : ${C_GREEN}ok — shared writable${C_RESET}\n"
    else
        printf "${C_BOLD}  • Storage : ${C_GOLD}termux-setup-storage dena padega (step 1)${C_RESET}\n"
    fi
    printf "\n"
}

_boot_pct() {
    if [ -n "${DL_BASE:-}" ] && [ -n "${PW_DL:-}" ] && [ -n "${PW_EXTRACT:-}" ]; then
        echo $((DL_BASE + PW_DL + PW_EXTRACT))
    else
        echo 100
    fi
}

# ---------------- overall progress bar ----------------
# Each step reports a %. Long things like pkg update/install run under a
# spinner (never looks stuck), and the bar moves while that step runs.
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

# spinner + bar — animates during long commands
_spin() {  # _spin PCT LABEL PID
    local PCT="$1" LABEL="$2" SPID="$3"
    local FR=('|' '/' '-' '\\')
    local k=0
    while kill -0 "$SPID" 2>/dev/null; do
        if [ "$TTY_MODE" -eq 1 ]; then
            _pbar "$PCT" "${LABEL} ${FR[$((k % 4))]}"
        elif [ $((k % 20)) -eq 0 ]; then
            # non-tty (log capture) — 4s heartbeat, otherwise minutes of SILENCE
            printf "  ▸ %s ... (%ss)\n" "$LABEL" "$((k / 5))"
        fi
        k=$((k + 1))
        sleep 0.2
    done
}

run_spin() {  # run_spin PCT LABEL cmd...
    local PCT="$1" LABEL="$2"; shift 2
    _pbar "$PCT" "$LABEL"
    # </dev/null — apt/dpkg prompts must never eat the piped script (stdin)
    "$@" >$LOG 2>&1 </dev/null &
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

# ---------------- pip install (individual + retry) ----------------
pip_try() {  # pip_try "lib" — break-system-packages ke saath/na ke retry
    local lib="$1"
    pip install "$lib" >$LOG 2>&1 </dev/null && return 0
    pip install --break-system-packages "$lib" >$LOG 2>&1 </dev/null && return 0
    pip install --user "$lib" >$LOG 2>&1 </dev/null && return 0
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

# ------------ dpkg/apt heal — fix broken package state ------------
_heal_dpkg() {  # half-configured dpkg or broken dependencies = the #1
    # cause of "pkg fail". Non-fatal, runs before every retry.
    dpkg --configure -a >$LOG 2>&1 </dev/null || true
    apt-get -f install -y >$LOG 2>&1 </dev/null || true
}

# package install (individual + retry) — works on every phone now:
#   pkg fail 3x  ->  heal + apt-get direct fallback  ->  post-check
install_pkgs() {  # install_pkgs BASE_PCT PCT_STEP "LABEL_PREFIX" pkg...
    local BASE="$1" PCT_STEP="$2" LP="$3"; shift 3
    local total=$# i=1 p
    for p in "$@"; do
        local pct=$(( BASE + (i - 1) * PCT_STEP / total ))
        _pbar "$pct" "${LP} ${p} (${i}/${total})"
        if command -v "$p" >/dev/null 2>&1; then
            _pbar "$pct" "${LP} ${p} ✓ (${i}/${total})"
            printf "\n"
            i=$((i + 1))
            continue
        fi
        local rc=1 try=1
        while [ "$try" -le 3 ] && [ "$rc" -ne 0 ]; do
            [ "$try" -gt 1 ] && _pbar "$pct" "${LP} ${p} retry ${try}/3"
            _heal_dpkg
            pkg install -y "$p" >$LOG 2>&1 </dev/null &
            local SPID=$!
            _spin "$pct" "${LP} ${p} (${i}/${total})" "$SPID"
            wait "$SPID"
            rc=$?
            if [ "$rc" -ne 0 ]; then
                pkg update -y >$LOG 2>&1 </dev/null || true
            fi
            try=$((try + 1))
        done
        if [ "$rc" -ne 0 ]; then
            # pkg wrapper fail -> apt-get direct (both are the same in Termux,
            # but apt has --fix-broken + more conf options)
            _pbar "$pct" "${LP} ${p} (apt-get fallback)"
            _heal_dpkg
            apt-get install -y -o Dpkg::Options::=--force-confdef \
                -o Dpkg::Options::=--force-confold "$p" >$LOG 2>&1 </dev/null
            rc=$?
        fi
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

# python is obviously essential (the tool runs on python). If 3 retries + apt-get
# fallback still fail -> one FINAL repair round (update + heal + space check).
python_repair() {
    printf "\n${C_GOLD}${C_BOLD}  ⚠ python did not install — final repair round...${C_RESET}\n"
    pkg update -y >$LOG 2>&1 </dev/null || true
    _heal_dpkg
    pkg install -y python >$LOG 2>&1 </dev/null || true
    if ! command -v python3 >/dev/null 2>&1; then
        apt-get install -y -o Dpkg::Options::=--force-confdef \
            -o Dpkg::Options::=--force-confold python \
            >$LOG 2>&1 </dev/null || true
    fi
    if command -v python3 >/dev/null 2>&1; then
        printf "\n"
        ok "python3 installed"
        return 0
    fi
    printf "\n${C_RED}${C_BOLD}  ✗ python3 failed to install!${C_RESET}\n"
    printf "${C_GOLD}  First check free space:${C_RESET}\n"
    df -h "$PREFIX" 2>/dev/null | sed 's/^/    /'
    printf "${C_GOLD}  Then run these manually:${C_RESET}\n"
    printf "${C_GOLD}    pkg update -y && pkg upgrade -y${C_RESET}\n"
    printf "${C_GOLD}    pkg install -y python${C_RESET}\n"
    printf "${C_GOLD}    ikram${C_RESET}\n"
    return 1
}

# boot test — key prompt + main menu once (shared by install finish + --test)
boot_test() {  # boot_test IKRAM_SRC
    local IKRAM_SRC="$1"
    local BOOT_TB="$TARGET/.boot_tb.log"
    local BOOT_OK="$TARGET/.boot_ok.$$"
    local BOOT_PY="$TARGET/.boot_drv.$$.py"
    box "$C_GOLD" "\U0001F680 Final boot test"
    _pbar "$(_boot_pct)" "Booting tool once"
    rm -f "$BOOT_TB" "$BOOT_OK"
    printf 'FREETOOL\n0\n' > "$TARGET/.boot_plan.$$"
    cat > "$BOOT_PY" <<'PY'
import os, sys, builtins, traceback

TB = os.environ.get("IKRAM_TB")
OK = os.environ.get("IKRAM_OK")

def _boom(tag, exc):
    try:
        with open(TB, "a") as fh:
            fh.write("[%s] %s\n" % (tag, traceback.format_exc()))
    except Exception:
        pass

# The whole driver is guarded. A driver that cannot even read its own env must
# never look like a healthy boot: the installer reads this log to decide, and an
# unguarded crash here used to be reported as "reached the key prompt".
try:
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
        # Unactivated tool stops at its activation-key gate. Expected, healthy.
        pass
    except BaseException:
        _boom("main", sys.exc_info()[1])
    else:
        try:
            open(OK, "a").close()
        except Exception:
            pass
except BaseException:
    _boom("driver", sys.exc_info()[1])
    sys.exit(3)
PY
    # Bounded: the tool parks at the activation-key prompt and keeps reading
    # stdin, so without a timeout this waits forever when the installer's own
    # stdin is not a terminal (curl | bash, CI, </dev/null). The env prefix must
    # be immediately followed by the command - a comment between them ends the
    # assignment and the driver then runs with IKRAM_PATCH unset.
    PYTHONDONTWRITEBYTECODE=1 IKRAM_PATCH="$IKRAM_SRC" \
    IKRAM_PLAN="$TARGET/.boot_plan.$$" \
    IKRAM_TB="$BOOT_TB" \
    IKRAM_OK="$BOOT_OK" \
    timeout 30 python3 "$BOOT_PY"
    _boot_rc=$?
    if [ -f "$BOOT_OK" ]; then
        printf "\n"
        ok "Boot test passed - Key prompt + Main menu OK"
    elif [ -s "$BOOT_TB" ]; then
        printf "\n"
        fail "Boot test FAILED:"
        sed 's/^/      /' "$BOOT_TB"
        _restore
        return 1
    else
        printf "\n"
        ok "Boot test passed - tool reached the key prompt (rc=$_boot_rc)"
    fi
    rm -f "$TARGET/.boot_plan.$$" "$BOOT_PY" "$BOOT_OK" "$BOOT_TB" 2>/dev/null
    advance 100 "Boot test"
}

# ---------------- --test self-test mode (V114) ----------------
# install.sh --test  ->  system checks + boot test only (no reinstall).
# Exit code 0 = PASS, 1 = FAIL. Clean output even when not on a TTY.
SELF_TEST="${1:-}"
if [ "$SELF_TEST" = "--test" ] || [ "$SELF_TEST" = "-t" ]; then
    tool_splash
    sys_info
      TARGET="$HOME/Ikram_Tool"
      ENG="$TARGET/.engine"
      if [ -f "$ENG/ikram_patch.py" ]; then
          IKRAM_SRC="$ENG/ikram_patch.py"
      elif [ -f "$TARGET/ikram_patch.py" ]; then
          IKRAM_SRC="$TARGET/ikram_patch.py"
      fi
    if [ -n "$IKRAM_SRC" ]; then
        boot_test "$IKRAM_SRC"
        ok "SELF-TEST DONE"
        exit 0
    fi
    fail "Tool is not installed — install it first, then run --test:"
    printf "${C_GOLD}    curl -fL https://raw.githubusercontent.com/ikram571/ikram-tool/main/install.sh | bash${C_RESET}\n"
    exit 1
fi

# 1) tool splash (matches the tool)
tool_splash
# Press-Enter prompt ONLY if stdin is a real TTY. Under `curl ... | bash`
# stdin is the script pipe — an inner `read` there can swallow the next
# chunk of the script (bash hasn't buffered it yet) = "starts, stops mid-way".
if [ -t 0 ]; then
    step "Press Enter to start the installation..."
    read -r dummy 2>/dev/null || true
fi

# system info — arch / android / storage (V114)
sys_info

# phase weights (total 100)
PW_STORAGE=4
PW_UPDATE=8
PW_UPGRADE=10
PW_PKGS=34
PW_PIP=16
PW_DL=16
PW_EXTRACT=6
PW_SETUP=6

# 1) storage — run it in BACKGROUND (on some phones the dialog blocks ahead =
# "install stuck"); the user can grant it during the pkg steps, checked at
# the end. The pipe will never block.
box "$C_CYAN" "📁 Storage permission"
_pbar 0 "Storage permission"
printf "${C_DIM}    (If a popup appears, press ALLOW)${C_RESET}\n"
termux-setup-storage >/dev/null 2>&1 </dev/null &
printf "\n"
ok "Storage request sent (press ALLOW on popup)"
advance "$PW_STORAGE" "Storage permission"

# 0.5) broken dpkg heal — this was the case on already half-updated phones
# that failed "again and again". best-effort, non-fatal.
dpkg --configure -a >$LOG 2>&1 </dev/null || true

# 2) update
box "$C_CYAN" "🔄 Updating packages"
run_spin "$PW_UPDATE" "pkg update" pkg update -y
printf "\n"
ok "Repositories updated"
advance "$PW_UPDATE" "pkg update"

# 3) upgrade (for latest python) — 2-5 min on slow phones, bar keeps moving
box "$C_CYAN" "⬆ Upgrading packages (may take 2-5 min on slow phones)"
run_spin "$PW_UPGRADE" "pkg upgrade" pkg upgrade -y
printf "\n"
ok "Packages upgraded"
# if the upgrade broke halfway, dpkg is left half-configured = every
# python/java install after it FAILS. Heal here, then start the installs.
_heal_dpkg
advance "$PW_UPGRADE" "pkg upgrade"

# 4) core packages — ONE BY ONE
box "$C_CYAN" "⬇ Installing core packages (python, git, curl, unzip, java, lua...)"
# openjdk package name differs across Termux repo states: try a candidate-chain
# (17 -> 21 -> 25), use whichever exists on that mirror. Needed for java cfr.jar
# / unluac.jar; Lua native (luac_patched) runs without java. clang = the
#         runtime C self-repair fallback of sm4_custom (if the shipped
#         ikram_sm4_fast.so is ever corrupt/missing, recompile on device).
install_pkgs "$PW_UPDATE" "$PW_PKGS" "Installing" \
    python git curl unzip lua53 clang

JAVA_PKG=""
if ! command -v javac >/dev/null 2>&1; then
    for jp in openjdk-17 openjdk-21 openjdk-25; do
        _pbar "$((PW_UPDATE + PW_PKGS))" "Installing ${jp}"
        if     pkg install -y "$jp" >$LOG 2>&1 </dev/null; then
            if command -v javac >/dev/null 2>&1; then
                JAVA_PKG="$jp"
                printf "\n"
                ok "Java ready (${jp})"
                break
            fi
        fi
        printf "\n"
        warn "${jp} not found in this repo — trying next."
    done
    if [ -z "$JAVA_PKG" ]; then
        warn "Java install failed — jar-based decompile somewhat limited (Lua native still works)."
    fi
else
    JAVA_PKG=$(javac --version 2>/dev/null | head -1)
    ok "Java already present (${JAVA_PKG})"
fi
advance "$((PW_UPDATE + PW_PKGS))" "Core packages"

if ! command -v python3 >/dev/null 2>&1; then
    python_repair
    if ! command -v python3 >/dev/null 2>&1; then
        exit 1
    fi
fi
PY_VER=$(python3 -c 'import sys;print(".".join(map(str,sys.version_info[:3])))' 2>/dev/null)
ok "python3 ready (${PY_VER:-unknown})"

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
  # Installed layout is exactly three folders:
  #   Ikram_Tool/.engine/  the runtime, and nothing else
  #   Ikram_Tool/DROP/     the user's input files
  #   Ikram_Tool/RESULT/   the tool's output files
  # The engine stays in a hidden folder so the tool's own files never sit
  # among the user's data, but DROP/RESULT are siblings of it, not children.
    ENG="$TARGET/.engine"
    # Staging lives OUTSIDE Ikram_Tool so a half-finished download can never be
    # mistaken for part of the install, and so a successful install leaves
    # exactly three folders behind: .engine, DROP and RESULT.
    STAGE="$HOME/.ikram_stage"
    DLZIP="$STAGE/IkramTool.zip"
    rm -rf "$STAGE"; mkdir -p "$STAGE"
    # Every exit path - success, download failure, corrupt zip, Ctrl-C - must
    # take the staging dir with it, and must not leave a hollow Ikram_Tool
    # behind. rmdir only succeeds on an empty dir, so an existing install is
    # never touched here.
    _cleanup_stage() {
        [ -n "${STAGE:-}" ] && rm -rf "$STAGE"
        [ -n "${TARGET:-}" ] && [ -d "$TARGET" ] && rmdir "$TARGET" 2>/dev/null
        return 0
    }
    trap _cleanup_stage EXIT INT TERM
    box "$C_CYAN" "⬇ Downloading tool"
    mkdir -p "$TARGET"
# TOOL_URL env override = local/testing builds. Default = GitHub latest.
: "${TOOL_URL:=https://github.com/ikram571/ikram-tool/releases/latest/download/IkramTool.zip}"
TOOL_URL="$TOOL_URL"
DL_BASE=$((PW_UPDATE + PW_PKGS + PW_PIP))
_pbar "$DL_BASE" "Downloading tool"
TOTAL=$(curl -sIL "$TOOL_URL" 2>/dev/null | grep -i '^content-length' | tail -1 | tr -dc '0-9')
[ -z "$TOTAL" ] && TOTAL=0
DONE=0
ATT=0
while [ "$ATT" -lt 3 ] && [ "$DONE" -eq 0 ]; do
    ATT=$((ATT + 1))
    rm -f "$DLZIP"
    curl -fL -s -o "$DLZIP" "$TOOL_URL" &
    CPID=$!
    while kill -0 "$CPID" 2>/dev/null; do
        CUR=$(stat -c%s "$DLZIP" 2>/dev/null || echo 0)
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
    DONE=$(stat -c%s "$DLZIP" 2>/dev/null || echo 0)
    MAGIC=$(head -c2 "$DLZIP" 2>/dev/null | tr -d '\0')
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
    fail "Download failed — check your internet and try again."
    exit 1
fi

# 6) extract + install
box "$C_GOLD" "🧹 Installing tool"
# extract into a subdir: TMPX is wiped before extraction, and the downloaded
# zip lives in $STAGE itself
TMPX="$STAGE/payload"
rm -rf "$TMPX" && mkdir -p "$TMPX"
_pbar "$((DL_BASE + PW_DL))" "Extracting tool"
if (cd "$TMPX" && unzip -q -o "$DLZIP"); then
    printf "\n"
else
    printf "\n"
    fail "Extract failed — try again."
    rm -rf "$TMPX" "$DLZIP"
    exit 1
fi
# Release zips may ship either FLAT (payload at the zip root, V119 and older)
# or WRAPPED in a single top-level directory (Ikram_Tool/, V120+). Descend into
# the wrapper before anything else looks at the tree, so the ikram.pyc probe
# and the whole-payload validation below both see the real payload root.
# update.py already unwraps the same way before it swaps the runtime.
if [ ! -f "$TMPX/ikram.pyc" ]; then
    for _cand in "$TMPX"/*/; do
        [ -f "${_cand}ikram.pyc" ] && { TMPX="${_cand%/}"; break; }
    done
fi
if [ ! -f "$TMPX/ikram.pyc" ]; then
    fail "ikram.pyc not found in zip — release is broken."
    rm -rf "$TMPX" "$DLZIP"
    exit 1
fi
# Validate the WHOLE payload before a single existing file is touched. A
# payload missing the tool's own entry points is not an update, it is a broken
# or truncated download.
_missing=""
for _need in ikram.pyc ikram_patch.py menus.py engines.py paths.py vip_ui.py \
             run.sh update.py; do
    [ -f "$TMPX/$_need" ] || _missing="$_missing $_need"
done
if [ -n "$_missing" ]; then
    fail "Downloaded package is incomplete — missing:$_missing"
    printf "${C_RED}${C_BOLD}    Nothing was changed. Try again with a better connection.${C_RESET}\n"
    rm -rf "$TMPX" "$DLZIP"
    exit 1
fi

# ---- stale-installer hand-off --------------------------------------------
# A cached copy of this script (CDN, proxy, an old one-liner someone saved)
# paired with a NEW zip produces a broken hybrid: the old installer lays the
# new payload out the old way, writes an old-style launcher, and the tool
# then fails at runtime with no clue why. The zip carries its own installer,
# so make that the authority: if the script now running is not the one inside
# the payload we just verified, hand over to it and let it do the install.
#
# This is what makes a stale one-liner safe on any phone - the fix arrives
# with the download instead of depending on the caller's cache.
_self="$TARGET/.ikram_selfcheck.$$"
if command -v sha256sum >/dev/null 2>&1; then
    _h1=$(sha256sum "$0" 2>/dev/null | cut -d' ' -f1)
    _h2=$(sha256sum "$TMPX/install.sh" 2>/dev/null | cut -d' ' -f1)
    if [ -n "$_h1" ] && [ -n "$_h2" ] && [ "$_h1" != "$_h2" ] && [ -f "$TMPX/install.sh" ]; then
        printf "\n"
        printf "  \033[1;33m>> Stale installer detected (cached copy).\033[0m\n"
        printf "     \033[0;33mHanding over to the installer inside this release...\033[0m\n"
        printf "     \033[0;90mwas %s / release %s\033[0m\n" "${_h1:0:12}" "${_h2:0:12}"
        _argv=""
        for _a in "$@"; do _argv="$_argv $(printf '%q' "$_a")"; done
        TOOL_URL="$TOOL_URL" bash "$TMPX/install.sh" $_argv
        _rc=$?
        rm -f "$_self" "$TMPX" "$DLZIP"
        exit $_rc
    fi
fi
# One-time layout migration. Early installs kept the user's folders in
# lowercase drop/ and result/ next to a hidden .engine/. Move their contents
# into the uppercase DROP/ and RESULT/ the tool uses now. Files already present
# in the destination win, so a re-run can never overwrite anything.
for _pair in "drop:DROP" "result:RESULT"; do
    _old="${_pair%%:*}"; _new="${_pair##*:}"
    if [ -d "$TARGET/$_old" ]; then
        mkdir -p "$TARGET/$_new"
        for _f in "$TARGET/$_old"/* "$TARGET/$_old"/.[!.]*; do
            [ -e "$_f" ] || continue
            [ -e "$TARGET/$_new/${_f##*/}" ] && continue
            mv "$_f" "$TARGET/$_new/" 2>/dev/null || true
        done
        rmdir "$TARGET/$_old" 2>/dev/null || rm -rf "$TARGET/$_old"
    fi
done

# Very old releases kept the user's folders flat, as siblings of the runtime:
# pak/ lua/ inject/ extracted/ processed/ ... directly in Ikram_Tool/. The
# transaction below moves every top-level entry it does not recognise into
# .old_runtime and discards it, so those folders have to be rescued HERE or the
# user's paks silently vanish on the next install. Same rule as above: a file
# already present in the destination wins, nothing is ever overwritten.
for _root in pak lua inject injected extracted processed CostomPak Repacked; do
    _src="$TARGET/$_root"
    [ -d "$_src" ] || continue
    case "$_root" in
        pak|lua|inject) _dest="$TARGET/DROP" ;;
        *)             _dest="$TARGET/RESULT" ;;
    esac
    mkdir -p "$_dest/$_root"
    for _f in "$_src"/* "$_src"/.[!.]*; do
        [ -e "$_f" ] || continue
        [ -e "$_dest/$_root/${_f##*/}" ] && continue
        mv "$_f" "$_dest/$_root/" 2>/dev/null || true
    done
    rmdir "$_src" 2>/dev/null || rm -rf "$_src"
done

# Install as a transaction, not a delete-then-copy. Every existing top-level
# entry is MOVED aside first, the new runtime is copied into .engine/, and the
# result is verified. If any step fails the partial copy is dropped and the
# previous runtime is moved straight back, so a failed reinstall can never
# leave the user with no tool at all. DROP/RESULT hold the user's files and are
# never touched -- the old .engine/ tree, including the DROP/RESULT symlinks it
# used to carry, goes into $OLDRT and is discarded once the new copy verifies.
OLDRT="$TARGET/.old_runtime"
rm -rf "$OLDRT"; mkdir -p "$OLDRT"
_take_aside() {
    for _e in "$TARGET"/* "$TARGET"/.[!.]*; do
        [ -e "$_e" ] || continue
        case "${_e##*/}" in
            DROP|RESULT|.old_runtime|.ikram_tmp) continue ;;
        esac
        mv "$_e" "$OLDRT/" 2>/dev/null || true
    done
}
_restore() {
    for _e in "$TARGET"/* "$TARGET"/.[!.]*; do
        [ -e "$_e" ] || continue
        case "${_e##*/}" in
            DROP|RESULT|.old_runtime|.ikram_tmp) continue ;;
        esac
        rm -rf "$_e"
    done
    [ -d "$OLDRT" ] && cp -r "$OLDRT"/. "$TARGET"/ 2>/dev/null
    return 0
}
_take_aside
# the user's folders are rebuilt every install so a missing subfolder is fixed
mkdir -p "$TARGET/DROP/pak" "$TARGET/DROP/lua" "$TARGET/DROP/inject" \
         "$TARGET/RESULT/extracted" "$TARGET/RESULT/injected" "$TARGET/RESULT/lua" \
         "$TARGET/RESULT/processed" "$TARGET/RESULT/CostomPak" "$TARGET/RESULT/Repacked"
# copy from temp -> Ikram_Tool/.engine/ (runtime only; DROP/RESULT stay put)
mkdir -p "$ENG"
if ! cp -r "$TMPX"/. "$ENG"/ 2>/dev/null; then
    _restore
    fail "Install failed while copying — your previous version was restored."
    rm -rf "$TMPX" "$STAGE" "$DLZIP"
    exit 1
fi
# A restrictive umask (Android/Termux commonly 0077) leaves the copied binaries
# and scripts owner-only, which breaks the tool the moment it is run as any
# other user or from a wrapper that drops privileges. Re-apply the execute bit
# explicitly so the install does not depend on the caller's umask.
for _x in lua_patched luac_patched unluac_rs repak \
          run.sh install.sh update.sh; do
    [ -f "$ENG/$_x" ] && chmod 755 "$ENG/$_x"
done
# verify the copy really landed before declaring victory
_vmissing=""
for _need in ikram.pyc ikram_patch.py menus.py engines.py paths.py vip_ui.py \
             run.sh update.py; do
    [ -f "$ENG/$_need" ] || _vmissing="$_vmissing $_need"
done
if [ -n "$_vmissing" ]; then
    _restore
    fail "Install incomplete — missing:$_vmissing"
    printf "${C_GOLD}             your previous version was restored.${C_RESET}\n"
    rm -rf "$TMPX" "$STAGE" "$DLZIP"
    exit 1
fi
# The new runtime is verified and live. Only now is the old one discarded.
rm -rf "$OLDRT"
# TMPX may have been re-pointed at the unwrapped inner directory, so the
# outer extraction dir is named explicitly here.
rm -rf "$TMPX" "$STAGE" "$DLZIP"
# DROP/RESULT skeleton — always created (fresh install starts empty)
# V114 Fixed-Path System: DROP/{pak,lua,inject} + RESULT branches
# (Section G frozen — original mixed-case spellings).
# paths.py ensure_dirs() also creates these at launcher time; creating them
# here too so the first boot shows no 'FOLDERS CREATED' box.
mkdir -p "$TARGET/DROP/pak" "$TARGET/DROP/lua" "$TARGET/DROP/inject" \
         "$TARGET/RESULT/extracted" "$TARGET/RESULT/injected" \
         "$TARGET/RESULT/lua" "$TARGET/RESULT/processed" \
         "$TARGET/RESULT/CostomPak" "$TARGET/RESULT/Repacked"
if [ -f "$ENG/ikram.pyc" ] && [ -f "$ENG/ikram_patch.py" ]; then
    ok "Tool installed"
    advance "$((DL_BASE + PW_DL + PW_EXTRACT))" "Tool installed"
else
    fail "Install failed — try again."
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

# Ikram Tool launcher (ikram_patch.py = full A-to-Z file load)
ikram() { PYTHONDONTWRITEBYTECODE=1 python3 "@@ENG@@/ikram_patch.py" "$@"; }
EOF
# real executable - won't reload from bashrc function, always ready in PATH
cat > "$PREFIX/bin/ikram" <<'EOF'
#!/data/data/com.termux/files/usr/bin/bash
export PYTHONDONTWRITEBYTECODE=1
if ! command -v python3 >/dev/null 2>&1; then
    echo ""
    echo "  python3 not found! Install it:"
    echo "    pkg update -y && pkg install -y python"
    echo ""
    exit 1
fi
# if the patch is missing, self-repair (fresh full zip download)
if [ ! -f "@@ENG@@/ikram_patch.py" ]; then
    echo ""
    echo "  ⚠ Tool files missing — self-repairing..."
    mkdir -p "@@ENG@@"
    cd "@@ENG@@"
    curl -sL -o repair.zip "https://github.com/ikram571/ikram-tool/releases/latest/download/IkramTool.zip"
    REPAIR_ROOT="@@ENG@@/.repair"
    rm -rf "$REPAIR_ROOT" && mkdir -p "$REPAIR_ROOT"
    if (cd "$REPAIR_ROOT" && unzip -q -o "@@ENG@@/repair.zip"); then
        # The release wraps its payload in a single Ikram_Tool/ directory, so
        # the entry point is one level down. Descend into it, or the check
        # below never finds ikram.pyc and repair always fails.
        SRC="$REPAIR_ROOT"
        if [ ! -f "$SRC/ikram.pyc" ] && [ -f "$SRC/Ikram_Tool/ikram.pyc" ]; then
            SRC="$SRC/Ikram_Tool"
        fi
        if [ -f "$SRC/ikram.pyc" ]; then
            cp -r "$SRC"/. "@@ENG@@"/ 2>/dev/null
            chmod +x "@@ENG@@/run.sh" "@@ENG@@/luac_patched" "@@ENG@@/lua_patched" \
                     "@@ENG@@/repak" "@@ENG@@/unluac_rs" 2>/dev/null
            rm -rf "$REPAIR_ROOT" "@@ENG@@/repair.zip"
            echo "  ✓ Repair done! Tool khul raha hai..."
            exec python3 "@@ENG@@/ikram_patch.py" "$@"
        fi
    fi
    rm -rf "$REPAIR_ROOT" "@@ENG@@/repair.zip"
    echo "  ✗ Repair failed. Reinstall with:"
    echo "    curl -fL https://cdn.jsdelivr.net/gh/ikram571/ikram-tool@main/install.sh | bash"
    echo ""
    exit 1
fi
# pyc magic check — if python is outdated, upgrade it ourselves
MAGIC_NEEDED=$(python3 -c "import importlib.util;print(importlib.util.MAGIC_NUMBER.hex())" 2>/dev/null)
MAGIC_HAVE=$(python3 -c "
import struct
p = open('@@ENG@@/ikram.pyc','rb').read(4)
print(p.hex())
" 2>/dev/null)
if [ -n "$MAGIC_HAVE" ] && [ "$MAGIC_HAVE" != "$MAGIC_NEEDED" ]; then
    echo ""
    echo "  ⬆ Python purana hai — upgrade kar raha hoon..."
    pkg update -y >/dev/null 2>&1 </dev/null
    DEBIAN_FRONTEND=noninteractive pkg upgrade -y python 2>&1 </dev/null | tail -3
    if [ "$(python3 -c "import importlib.util;print(importlib.util.MAGIC_NUMBER.hex())" 2>/dev/null)" = "$MAGIC_NEEDED" ]; then
        echo "  ✓ Python upgraded! The tool is starting..."
        exec python3 "@@ENG@@/ikram_patch.py" "$@"
    fi
    echo "  ✗ Python upgrade failed. Run these:"
    echo "    pkg update -y && pkg upgrade -y"
    echo "    ikram"
    echo ""
    exit 1
fi
    exec python3 "@@ENG@@/ikram_patch.py" "$@"
EOF
# A quoted heredoc expands nothing, so the install path is baked
# in after the write. The installer knows where it put the engine;
# the generated launchers must not have to guess at it.
sed -i "s#@@ENG@@#$ENG#g; s#@@ROOT@#$ENG#g" \
    "$RC" "$PREFIX/bin/ikram" 2>/dev/null
chmod +x "$PREFIX/bin/ikram"
# The launcher is generated from a quoted heredoc and patched afterwards, so it
# can silently come out wrong: an unexpanded $TARGET, a leftover @@ENG@@, or a
# path pointing at a folder this install does not use. None of that is visible
# from the install log, and the user only finds out when `ikram` fails. Verify
# the artefact instead of assuming it.
_lb_bad=""
[ -f "$PREFIX/bin/ikram" ] || _lb_bad="missing"
[ -x "$PREFIX/bin/ikram" ] || _lb_bad="${_lb_bad:+$_lb_bad,}not-executable"
grep -q '@@ENG@@\|@@ROOT@' "$PREFIX/bin/ikram" 2>/dev/null && _lb_bad="${_lb_bad:+$_lb_bad,}unexpanded-placeholder"
grep -q '\$TARGET' "$PREFIX/bin/ikram" 2>/dev/null && _lb_bad="${_lb_bad:+$_lb_bad,}undefined-var"
grep -qF "$ENG/ikram_patch.py" "$PREFIX/bin/ikram" 2>/dev/null || _lb_bad="${_lb_bad:+$_lb_bad,}wrong-engine-dir"
# the launcher must never point the tool at the user-data folders
grep -qF "$ENG/DROP" "$PREFIX/bin/ikram" 2>/dev/null && _lb_bad="${_lb_bad:+$_lb_bad,}drop-inside-engine"
if [ -n "$_lb_bad" ]; then
    warn "'ikram' launcher looks wrong ($_lb_bad)"
else
    ok "'ikram' command ready (new version)"
fi

chmod +x "$ENG/run.sh" "$ENG/install.sh" 2>/dev/null || true
chmod +x "$ENG/luac_patched" "$ENG/lua_patched" 2>/dev/null || true
chmod +x "$ENG/repak" "$ENG/unluac_rs" 2>/dev/null || true

# 7B) post-install boot test (shows key prompt + main menu once)
if [ -f "$ENG/ikram_patch.py" ]; then
    boot_test "$ENG/ikram_patch.py"
else
    warn "Boot test skipped (ikram_patch.py not found)"
fi

advance 100 "Setup complete"
# storage end-check — the background request should have settled by now
if [ ! -d "$HOME/storage/shared" ]; then
    warn "Storage share not found yet — run later: termux-setup-storage"
fi
V_VER=$(cat "$ENG/VERSION" 2>/dev/null || echo "latest")
BW=$((W - 2))
# right-pad each line so the box closes flush (tool-style VIP finish)
pad_line() { local txt="$1"; local L="${#txt}"; local P=$((BW - L)); [ $P -lt 1 ] && P=1; printf '%s%s%s' "$txt" "$(printf '%*s' $P '')" "${C_GREEN}│${C_RESET}"; }
printf "\n${C_GREEN}╭$(printf '─%.0s' $(seq 1 $BW))╮${C_RESET}\n"
# Assert the layout this release promises before claiming success. The install
# can produce a working tool and still not be the layout the launcher expects,
# and that mismatch is what makes "installed!" a lie.
_layout_ok=1
for _need in "$ENG/ikram_patch.py" "$ENG/ikram.pyc" "$TARGET/DROP" "$TARGET/RESULT"; do
    [ -e "$_need" ] || { _layout_ok=0; printf "  missing: %s\n" "$_need"; }
done
# A stray engine that still holds user data is a migration bug, not cosmetic.
for _stray in "$ENG/DROP" "$ENG/RESULT"; do
    if [ -d "$_stray" ] && [ -z "$(find "$_stray" -type f -print -quit 2>/dev/null)" ]; then
        rm -rf "$_stray"
    elif [ -d "$_stray" ]; then
        printf "  %s still holds files - move them into DROP/ or RESULT/\n" "$_stray"
    fi
done
# find's -name matches the BASENAME, so it has to be given the basename of $ENG,
# not the full path - passing the full path silently counted .engine itself as
# an unexpected entry and rolled back every good install.
_engname=$(basename "$ENG")
_extra=$(find "$TARGET" -mindepth 1 -maxdepth 1 \
            ! -name "$_engname" ! -name 'DROP' ! -name 'RESULT' -print 2>/dev/null | head -5)
if [ -n "$_extra" ]; then
    _layout_ok=0
    printf "  unexpected entries in Ikram_Tool: %s\n" "$(printf '%s' "$_extra" | tr '\n' ' ')"
fi

# The bashrc function shadows the real launcher in an interactive shell, so a
# broken launcher is what a user actually hits. Do not parse those scripts with a
# regex - their paths go through "~", quotes and variables, and a wrong guess
# here rolls back a perfectly good install. Check the things that are exact:
# the launcher exists, is a real file, and is executable.
if [ ! -f "$RC" ]; then
    _layout_ok=0
    printf "  launcher not generated at %s\n" "$RC"
elif [ ! -s "$RC" ] || ! grep -q 'ikram_patch' "$RC" 2>/dev/null; then
    _layout_ok=0
    printf "  launcher at %s does not reference ikram_patch\n" "$RC"
elif [ ! -x "$RC" ]; then
    chmod +x "$RC" 2>/dev/null || {
        _layout_ok=0
        printf "  launcher at %s is not executable\n" "$RC"
    }
fi
if [ "$_layout_ok" -ne 1 ]; then
    fail "Install did not produce the expected three-folder layout - rolled back."
    _restore
    exit 1
fi
printf "${C_GREEN}│${C_RESET}%s\n" "$(pad_line "  ${C_GREEN}${C_BOLD}✅ IKRAM TOOL INSTALLED!${C_RESET}")"
printf "${C_GREEN}│${C_RESET}%s\n" "$(pad_line "  ${C_GOLD}${C_BOLD}Now wait for key...${C_RESET}")"
printf "${C_GREEN}│${C_RESET}%s\n" "$(pad_line "  ${C_DIM}(KEY REQUIRED - owner se lo)${C_RESET}")"
printf "${C_GREEN}│${C_RESET}%s\n" "$(pad_line "  ${C_DIM}Version: ${C_GOLD}${C_BOLD}${V_VER}${C_RESET}")"
printf "${C_GREEN}│${C_RESET}%s\n" "$(pad_line "  ${C_GOLD}${C_BOLD}Run: ${C_CYAN}${C_BOLD}ikram${C_RESET}")"
printf "${C_GREEN}╰$(printf '─%.0s' $(seq 1 $BW))╯${C_RESET}\n"
printf "\n"
