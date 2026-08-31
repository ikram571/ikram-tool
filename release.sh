#!/data/data/com.termux/files/usr/bin/bash
# =============================================
#  Ikram Tool - GitHub Release Publisher
#  Naya version GitHub pe push karta hai.
#  Users ke tool me auto-update aa jata hai.
#  Use: bash release.sh 1.1.0
# =============================================
set -e
VERSION="${1:?Usage: bash release.sh VERSION (e.g. 1.1.0)}"

SOURCE_DIR="$(cd "$(dirname "$0")" && pwd)"
STAGE="$HOME/.ikram_release"
ZIP="$STAGE/ikram-tool-v$VERSION.zip"

# NOTE: real release flow = manual staging in ~/ikram_test_temp/v55zip/
# (flat layout with compiled .pyc chain + bytecode-surgery variants).
# This script is a helper; it MUST include .pyc (install.sh/ikram launcher
# require ikram.pyc) and ship the installed-style flat layout.
echo "[*] Making release v$VERSION ..."
rm -rf "$STAGE"
mkdir -p "$STAGE"

# Build a flat layout like the installed tool: source .py + compiled .pyc chain.
cp "$SOURCE_DIR"/ikram.py "$SOURCE_DIR"/run.sh "$SOURCE_DIR"/ikram.sh \
   "$SOURCE_DIR"/install.sh "$SOURCE_DIR"/ikram_key.json \
   "$SOURCE_DIR"/README.md "$STAGE/"
cp "$SOURCE_DIR"/mega_lua.py "$SOURCE_DIR"/univ.py "$STAGE"/
# copy the compiled chain from the installed tool (has the surgery-fixed pycs)
if [ -d "$HOME/Ikram_Tool" ]; then
  cp "$HOME"/Ikram_Tool/*.pyc "$STAGE"/ 2>/dev/null || true
fi
mkdir -p "$STAGE"/modules
cp "$SOURCE_DIR"/modules/*.py "$STAGE"/modules/
# ship the runtime sm4 lib + lua binaries the flat layout needs
cp "$HOME"/Ikram_Tool/ikram_sm4_fast.c "$HOME"/Ikram_Tool/ikram_sm4_fast.so "$STAGE"/ 2>/dev/null || true
rm -rf "$STAGE"/__pycache__ "$STAGE"/modules/__pycache__

cd "$STAGE"
# KEEP .pyc: they are required. Only drop __pycache__ junk.
zip -r "$ZIP" . -x "__pycache__/*" -x "*/__pycache__/*"

echo "[*] Uploading to GitHub..."
gh release create "v$VERSION" "$ZIP" \
  --repo ikram571/ikram-tool \
  --title "Ikram Tool v$VERSION" \
  --notes "Ikram Tool v$VERSION" || true

echo "[+] Done! Users ab auto-update kar sakte hain."
