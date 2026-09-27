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
# Timestamped pre-edit backups live beside their sources in the working tree.
# They must never ship to users.
find "$STAGE" -name '*.bak_*' -delete
rm -f "$STAGE"/luac.out
# Docs are for the repo, not for the runtime zip — the zip ships ONLY files
# the tool needs to run and do its work.
rm -f "$STAGE"/README.md "$STAGE"/INSTRUCTIONS.txt "$STAGE"/CHANGELOG.md "$STAGE"/.gitignore

# Stamp the new version into VERSION + ikram_key.json (key_hash unchanged).
# The hash is read from the existing ikram_key.json, never retyped here, so
# there is exactly one place the activation hash lives.
KEY_HASH="$("${TERMUX_PREFIX:-/data/data/com.termux/files/usr}/bin/python3" -c \
  "import json;print(json.load(open('ikram_key.json'))['key_hash'])")"
echo "$VERSION" > "$STAGE/VERSION"
printf '{\n  "version": "%s",\n  "key_hash": "%s"\n}\n' "$VERSION" "$KEY_HASH" > "$STAGE/ikram_key.json"

cd "$STAGE"
# KEEP .pyc: they are required. Only drop __pycache__ junk.
zip -r "$ZIP" . -x "__pycache__/*" -x "*/__pycache__/*"

# Prove the archive before announcing it. A zip that cannot even list itself is
# not something to hand to users.
if ! unzip -tq "$ZIP" >/dev/null 2>&1; then
  echo "[x] The built archive is corrupt — refusing to upload."
  exit 1
fi
echo "[*] Archive OK: $(du -h "$ZIP" | cut -f1), $(unzip -l "$ZIP" | tail -1 | awk '{print $2}') entries"

echo "[*] Pushing $VERSION source to origin/main..."
git -C "$SOURCE_DIR" push origin main

echo "[*] Uploading to GitHub..."
if ! gh release create "$VERSION" "$ZIP" \
  --repo ikram571/ikram-tool \
  --title "Ikram Tool $VERSION" \
  --notes "Ikram Tool $VERSION"; then
  # This used to be `|| true`, which printed "Done! Users can now auto-update"
  # after a release that did not exist.
  echo "[x] Release $VERSION was NOT created — users cannot auto-update to it."
  exit 1
fi

echo "[+] Done! Release $VERSION is live. Users can now auto-update."
