#!/data/data/com.termux/files/usr/bin/bash
# =============================================
#  Ikram Tool - GitHub Release Publisher
#  Pushes a new version to GitHub.
#  Users' tools then get it via auto-update.
#  Use: bash release.sh V86
# =============================================
set -e
VERSION="${1:?Usage: bash release.sh VERSION, e.g. V86  (add --build-only to skip publishing)}"

# --build-only stops after the archive is built and proven, so the ZIP can be
# inspected before anything is pushed or published. Publishing is a separate,
# deliberate act.
BUILD_ONLY=0
for _arg in "${@:2}"; do
  case "$_arg" in
    --build-only) BUILD_ONLY=1 ;;
    *) echo "[!] Unknown option: $_arg"; exit 1 ;;
  esac
done

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
# The local action log is a RUNTIME artefact: it is written next to the module
# the first time the tool records anything, so on the machine that builds the
# release it is always present and always full of the builder's own runs.
# Shipping it would leak the maintainer's file paths into every download.
rm -f "$STAGE"/telemetry.log "$STAGE"/*.log
# Any .zip in the tree is a build product or an unrelated archive someone
# committed by accident. Neither belongs in the release.
rm -f "$STAGE"/*.zip
# Timestamped pre-edit backups live beside their sources in the working tree.
# They must never ship to users.
find "$STAGE" -name '*.bak_*' -delete
rm -f "$STAGE"/luac.out
# Docs are for the repo, not for the runtime zip — the zip ships ONLY files
# the tool needs to run and do its work.
# Every .md is repo documentation. The tool prints its own help; none of this
# belongs in a download. .gitignore goes with them.
rm -f "$STAGE"/*.md "$STAGE"/.gitignore
# release.sh is how the maintainer cuts a release. A user never runs it, and it
# is the one file in the tree that can push to github, so it stays in the repo.
rm -f "$STAGE"/release.sh

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
# Prove the contents too. An archive that is internally valid but carries the
# maintainer's log, the test tree, or the analysis dump is still a bad release,
# and every one of those has been committed by accident at some point.
LEAKED=$(unzip -Z1 "$ZIP" | grep -E '(^|/)(__pycache__|analysis|tests|\.git)(/|$)|telemetry\.(log|pyc)|\.bak_|\.zip$|^\./' || true)
if [ -n "$LEAKED" ]; then
  echo "[x] The archive carries files that must never ship:"
  printf '%s\n' "$LEAKED" | head -20
  exit 1
fi
echo "[*] Archive OK: $(du -h "$ZIP" | cut -f1), $(unzip -l "$ZIP" | tail -1 | awk '{print $2}') entries"

if [ "$BUILD_ONLY" = "1" ]; then
  echo "[*] --build-only: archive built and proven, nothing pushed or published."
  echo "[*] ZIP: $ZIP"
  exit 0
fi

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
