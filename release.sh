#!/data/data/com.termux/files/usr/bin/bash
# =============================================
#  Ikram Tool - GitHub Release Publisher
#  Pushes a new version to GitHub.
#  Users' tools then get it via auto-update.
#  Use: bash release.sh V120            (build only - safe default)
#       bash release.sh V120 --publish  (build, then upload)
# =============================================
set -e
VERSION="${1:?Usage: bash release.sh VERSION [--publish]}"
PUBLISH=0
[ "${2:-}" = "--publish" ] && PUBLISH=1

SOURCE_DIR="$(cd "$(dirname "$0")" && pwd)"
# Release work only happens in the opencode folder (no ikram junk at root).
STAGE="$HOME/opencode/.ikram_release"
# IMPORTANT: client code (install.sh, update.py ZIP_NAME, bin/ikram repair)
# all download "IkramTool.zip" via
#   .../releases/latest/download/IkramTool.zip
# That is why the asset's EXACT name must be "IkramTool.zip", else 404.
ZIP="$STAGE/IkramTool.zip"
# Release payload sits under a single top-level "Ikram_Tool/" directory.
# install.sh and update.py both unwrap that layer, so the same
# installer accepts flat (legacy) and wrapped (current) zips.
PKG="$STAGE/Ikram_Tool"

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
# Everything lands inside $PKG so the zip has exactly one "Ikram_Tool/" root.
# -a preserves modes; the explicit chmod below is umask-proof (this box runs
# umask 0077, which would otherwise strip group/other bits to 700 and ship
# scripts that only their owner can run).
mkdir -p "$PKG"
(cd "$SOURCE_DIR" && cp -a . "$PKG"/)
for _x in lua_patched luac_patched unluac_rs repak \
          run.sh install.sh update.sh release.sh; do
    [ -f "$PKG/$_x" ] && chmod 755 "$PKG/$_x"
done
rm -rf "$PKG"/__pycache__ "$PKG"/.ikram_tool "$PKG"/DROP "$PKG"/RESULT "$PKG"/output
rm -rf "$PKG"/original "$PKG"/logs
rm -f "$PKG"/Memory.md "$PKG"/activation.json "$PKG"/OWNER_INFO.txt "$PKG"/USER_MESSAGE.txt
rm -rf "$PKG"/.git "$PKG"/.github
rm -rf "$PKG"/analysis "$PKG"/tests "$PKG"/tools "$PKG"/dev_work
# Timestamped pre-edit backups live beside their sources in the working tree.
# They must never ship to users.
find "$PKG" -name '*.bak_*' -delete
rm -f "$PKG"/luac.out
# Docs are for the repo, not for the runtime zip — the zip ships ONLY files
# the tool needs to run and do its work.
rm -f "$PKG"/README.md "$PKG"/INSTRUCTIONS.txt "$PKG"/CHANGELOG.md "$PKG"/.gitignore
# Audit notes live in the repo; the payload ships runtime files only.
rm -f "$PKG"/FIXES_V120.md

# --- dead weight, verified unreferenced at runtime ---------------------
# cfr.jar 2.0MB : Java .class decompiler. Zero references in any .py; only a
#                 comment in install.sh. This tool decompiles Lua/PAK.
# ljd.zip  0.8MB: the loader uses deps/ljd/ (LJD_DIR). lua_pipeline.py:1177
#                 checks the DIRECTORY, not this zip. Kept: deps/ljd/.
# ikram_sm4_fast.c : C source for a prebuilt .so that already ships. Nothing
#                 compiles it at install or run time.
# release.sh: the publisher itself, not part of the runtime. install.sh only
#                 chmods it behind a `[ -f ]` guard, so its absence is safe.
rm -f "$PKG"/cfr.jar "$PKG"/ljd.zip "$PKG"/ikram_sm4_fast.c "$PKG"/release.sh
# QA harness lives in the working tree, not in the shipped payload.
rm -f "$PKG"/v120_regress.py "$PKG"/v120_safety.py "$PKG"/option_test.py

# Stamp the new version into VERSION + ikram_key.json (key_hash unchanged).
echo "$VERSION" > "$PKG/VERSION"
printf '{\n  "version": "%s",\n  "key_hash": "7360b6c497b3f043eb4d74ae1100f8681b6a968719135cd6de7b58f3363d5c36"\n}\n' "$VERSION" > "$PKG/ikram_key.json"

cd "$STAGE"
# KEEP .pyc: they are required. Only drop __pycache__ junk.
rm -f "$ZIP"
zip -r "$ZIP" "Ikram_Tool" -x "__pycache__/*" -x "*/__pycache__/*"

echo "[*] Built $ZIP ($(du -h "$ZIP" | cut -f1))"

if [ "$PUBLISH" -ne 1 ]; then
  echo "[=] Build only. Nothing was uploaded."
  echo "[=] Re-run with --publish to upload: bash release.sh $VERSION --publish"
  exit 0
fi

echo "[*] Uploading to GitHub..."
gh release create "$VERSION" "$ZIP" \
  --repo ikram571/ikram-tool \
  --title "Ikram Tool $VERSION" \
  --notes "Ikram Tool $VERSION"

echo "[+] Done! Users can now auto-update."
