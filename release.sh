#!/data/data/com.termux/files/usr/bin/bash
# =============================================
#  Ikram Tool - GitHub Release Publisher
#  Naya version GitHub pe push karta hai.
#  Users ke tool me auto-update aa jata hai.
#  Use: bash release.sh V86
# =============================================
set -e
VERSION="${1:?Usage: bash release.sh VERSION (e.g. V86)}"

SOURCE_DIR="$(cd "$(dirname "$0")" && pwd)"
STAGE="$HOME/.ikram_release"
# IMPORTANT: client code (install.sh, update.py ZIP_NAME, bin/ikram repair)
# sab "IkramTool.zip" download karta hai via
#   .../releases/latest/download/IkramTool.zip
# Isliye asset ka EXACT naam "IkramTool.zip" hona chahiye, warna 404.
ZIP="$STAGE/IkramTool.zip"

# NOTE: The wartah tool = flat runtime installed at $HOME/Ikram_Tool
# (run.sh -> ikram_patch.py -> compiled .pyc chain). The release zip MUST
# mirror that exact flat layout. We ship NO modules/ folder and NO ikram.py
# source (both caused broken updates before). Source = the installed tool.
echo "[*] Making release $VERSION ..."
rm -rf "$STAGE"
mkdir -p "$STAGE"

if [ ! -d "$HOME/Ikram_Tool" ]; then
  echo "[!] $HOME/Ikram_Tool not found. Install/sync the flat runtime first."
  exit 1
fi

# Copy the whole flat runtime layout, excluding temp/private junk.
(cd "$HOME/Ikram_Tool" && cp -r . "$STAGE"/)
rm -rf "$STAGE"/__pycache__ "$STAGE"/.ikram_tool "$STAGE"/DROP "$STAGE"/RESULT
rm -f "$STAGE"/Memory.md "$STAGE"/activation.json

# Stamp the new version into VERSION + ikram_key.json (key_hash unchanged).
echo "$VERSION" > "$STAGE/VERSION"
printf '{\n  "version": "%s",\n  "key_hash": "7360b6c497b3f043eb4d74ae1100f8681b6a968719135cd6de7b58f3363d5c36"\n}\n' "$VERSION" > "$STAGE/ikram_key.json"

cd "$STAGE"
# KEEP .pyc: they are required. Only drop __pycache__ junk.
zip -r "$ZIP" . -x "__pycache__/*" -x "*/__pycache__/*"

echo "[*] Uploading to GitHub..."
gh release create "$VERSION" "$ZIP" \
  --repo ikram571/ikram-tool \
  --title "Ikram Tool $VERSION" \
  --notes "Ikram Tool $VERSION" || true

echo "[+] Done! Users ab auto-update kar sakte hain."
