#!/data/data/com.termux/files/usr/bin/bash
# =============================================
#  Ikram Tool - GitHub Release Publisher
#  Pushes a new version to GitHub.
#  Users' tools then get it via auto-update.
#  Use: bash release.sh V86
# =============================================
set -e
VERSION="${1:?Usage: bash release.sh VERSION (e.g. V86)}"

SOURCE_DIR="$(cd "$(dirname "$0")" && pwd)"
# Release work only happens in the opencode folder (no ikram junk at root).
STAGE="$HOME/opencode/.ikram_release"
# IMPORTANT: client code (install.sh, update.py ZIP_NAME, bin/ikram repair)
# all download "IkramTool.zip" via
#   .../releases/latest/download/IkramTool.zip
# That is why the asset's EXACT name must be "IkramTool.zip", else 404.
ZIP="$STAGE/IkramTool.zip"

# NOTE: Release = SOURCE_DIR (repo) flat runtime layout
# (run.sh -> ikram_patch.py -> compiled .pyc chain). This repo is the canonical
# source — install + publish happen from here. Private/derived junk is
# excluded, and the compiled .pyc MUST be kept.
echo "[*] Making release $VERSION ..."
rm -rf "$STAGE"
mkdir -p "$STAGE"

if [ ! -d "$SOURCE_DIR" ]; then
  echo "[!] Source dir not found."
  exit 1
fi

# Copy the whole flat layout from the REPO, excluding temp/private junk.
(cd "$SOURCE_DIR" && cp -r . "$STAGE"/)
rm -rf "$STAGE"/__pycache__ "$STAGE"/.ikram_tool "$STAGE"/DROP "$STAGE"/RESULT "$STAGE"/output
rm -rf "$STAGE"/original "$STAGE"/logs
rm -f "$STAGE"/Memory.md "$STAGE"/activation.json "$STAGE"/OWNER_INFO.txt "$STAGE"/USER_MESSAGE.txt
rm -rf "$STAGE"/.git "$STAGE"/.github
rm -rf "$STAGE"/analysis "$STAGE"/tests "$STAGE"/tools "$STAGE"/dev_work
rm -f "$STAGE"/luac.out
# Docs are for the repo, not for the runtime zip — the zip ships ONLY files
# the tool needs to run and do its work.
rm -f "$STAGE"/README.md "$STAGE"/INSTRUCTIONS.txt "$STAGE"/CHANGELOG.md "$STAGE"/.gitignore

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

echo "[+] Done! Users can now auto-update."
