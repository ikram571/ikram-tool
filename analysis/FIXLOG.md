# Fix/Findings Log — IkramTool V111 audit, Phase 0..7

All changes land ONLY in the working tree
(/data/data/com.termux/files/home/ikram_work/ikram-tool). The live install
(~/Ikram_Tool) and golden test fixtures are never touched. Every fix is
re-verified before the next phase starts.

## F-001 — install.sh: clang missing from core packages (APPLIED)
install.sh installed python/git/curl/unzip/lua53 but never clang. The TenCRYPT
path compiles ikram_sm4_fast.so from embedded C at runtime;
sm4_custom.pyc rebuilds a .so if missing (verified self-repair, Phase 2).
Without clang, a clean install without the prebuilt .so breaks the Tencent pak
path.
Fix: added `clang` to the core `install_pkgs` list. Verdict: PASS (isolated
fake-home run, boot test OK).

## F-002 — runtime dependency audit (APPLIED, docs-only)
pip layer pinned/verified on-device: rich 15.0.0, pycryptodome 3.23.0,
zstandard 0.25.0, gmalg 1.1.2. openjdk chain 17->21->25. verified executables
(Phase 2): lua_patched (Lua 5.3.6), luac_patched, unluac_rs 1.3.1, repak_cli
0.2.3, unluac.jar (OpenJDK 17 ok), ljd.zip (zipimport).
No runtime gap found.

## F-003 — bundled ikram_key.json version drift breaks a fresh install (APPLIED)
KEY FILE: repo/release bundles ikram_key.json with version "V110" while the
VERSION file says "V111". The compiled gate key.check() (key.pyc line 59)
compares ikram_key.json['version'] to current_version() and REJECTS the key on
mismatch — so a fresh V111 install answered "✘ Invalid key!" for FREETOOL.
(My Phase-0 fake-home "PASS" was an artifact: I had regenerated ikram_key.json
there earlier; the pristine tree boots red.) Verified: after setting version
"V111" in the bundled ikram_key.json, a scratch copy of the tree boots
"✔ Key valid. Tool unlocked!" + main menu + clean exit 0. key_hash untouched
(same free key) — purely a version stamp sync. Note: is_activated() itself
never reads ikram_key.json.version; the entry-point check() does.

## F-004 — >100-col lines in plaintext sources (INFO, deferred)
Counts: ikram_patch.py 11, install.sh 17, update.py 6, mega_lua.py 11,
assetprocs.py 1, engines.py 0, univ.py 0. No raw ANSI escapes and no
hardcoded color markup anywhere in the overlay sources (Phase 5). Long lines
are strings/usage text — not churned, to honour the nothing-breaks mandate.

## P3-* — Phase 3 functional verification (all PASS)
- P3-001 Tencent unpack: 696/696 files, byte-identical to live golden
  extraction (byte-diff 0).
- P3-002 Tencent repack round-trip: edit one .lua -> repack_folder -> out pak
  (tencent magic) -> re-unpack -> full-tree sha256 equality incl. injected
  file. PASS.
- P3-003 30 MB Tencent pak: 1635 files in 1.6s (~18.6 MB/s), sane tree.
- P3-004 Lua decompile (BRPlayerCharacterBase.luac-in-.lua): output
  byte-identical to shipped golden *GAME.lua (601 lines, 0 diff hunks).
- P3-005 Lua compile->decompile round-trip: collect_award_module source ->
  BGMI luac (7466 B) -> 167/167 lines reconstructed. PASS.

## P3-NOTE — live artifacts worth knowing (INFO)
- RESULT/Repacked/game.pak is 4 bytes (detect None) — an empty/broken repack
  frame from some earlier live session. Not a tool bug we reproduce; logged as
  a robustness note for gen-2. Default UE4 round-trip could not be exercised:
  every fixture in the live set is Tencent-crypto (no standard-UE4 pak on
  disk). The UE4 path was verified by binary execution + engines.py key
  resolution, not on real data. Limitation documented.

## P4-* — Phase 4 (see analysis/PHASE4_SECURITY.md)
- S-001 telemetry scope fully mapped; keep-as-is per ownership + behavior
  mandate.
- S-002 license gate verified offline-hash + VERSION-tie; F-003 cosmetic.
- S-003/S-004 crypto constants + endpoints are format/owner authorised.

## P5-* — Phase 5 (UX/ANSI/60-col) — see analysis/PHASE5_UX.md
## R112-* — V112 REBUILD TEST SWEEP (engine + flow suites)
- R112-001 theme load_theme still read the retired CFG_FILE constant after
  the config_file() change -> silent NameError -> always fell back to Cyber
  Blue. load_theme/save_theme bodies switched to cfg.read_text(); round-trip
  test now green.
- R112-002 theme_engine Rainbow in non-TTY emitted a bare "\x1b[0m" RESET
  with no colour (colour support off) -> dirty pipes. _rainbow_char now
  returns the plain char when _fansi() gives "". Rainbow unit tests force
  is_tty for real colour-math assertions.
- R112-003 Theme.apply(None, role) -> "None" string instead of empty text.
  Normalised to "" (empty) for all roles.
- R112-004 detect_report labelled BGMI bytecode with entropy 2.9 (<4.0) as
  "source": band heuristic alone mislabels compact bytecode. Bands kept as
  documented; reporting now also exposes "kind" from magic bytes so format
  and band are separate signals. Tests assert band-in-set + kind.
- R112-005 decompiler validator (6-check) rejected a legit tiny decompiled
  script (only 1 keyword, stripped build). Spec rule is ≥3 keywords -> kept;
  tests now compile a structured function-heavy fixture (strip=False) so the
  real-output validator assertion is 6/6.
- R112-006 ALL_DIRS/_FOLDERS are a snapshot tuple built at paths import; test
  Env swapped DROP/RESULT constants but ensure_dirs still created the REAL
  repo folders and never created the temp ones, so inject's .tmp write
  blew up FileNotFoundError. Env now rebuilds ALL_DIRS + _FOLDERS before
  ensure_dirs; all deep pak flows green (696-entry Tencent unpack, inject,
  tencent repack hash-match, custom pak).
- R112-007 menus called vip.ProgressFrame(...) but ProgressFrame is now a
  module-level class in vip_ui. Re-wired via `from vip_ui import ProgressFrame`.

## PHASE FINAL (pipeline upgrade + live matrix)
- P-001 lua_pipeline unluac tier piped bytes into `java -jar` via stdin;
  unluac needs a real file arg. Now writes a temp file + passes the path,
  cleaned up in finally. Standard 5.1/5.3 + LuaJIT fixtures decompile.
- P-002 validator STRUCTURE_TOKENS missing "end" + per-token -1 undercounted
  small but valid files (5-line fixture scored 7/8 structures). Tokens now
  counted bare (function/if/while/for/repeat/do/end); small valid scripts
  pass 8/8.
- P-003 _xor_sweep accepted any dec head whose first 4 bytes equalled \x1bLua,
  which the key-recovery math guarantees by construction -> garbage.bin false
  "decrypted". Now requires a full magic + valid version byte (0x51..0x54) or
  LuaJIT version byte, or a detect-dialect hit.
- P-004 plain-source pass-through required band=="source", but a small valid
  .lua (42 B) reads as 4.37 entropy -> "standard bytecode" band -> never hit
  the pass-through and died in unluac. Gate is now kind=="unknown" AND
  (looks_like_source OR compiles_as_lua); readable source is trusted as
  success (validator score reported but not gating).
- P-005 theme_engine.apply appended RESET unconditionally even when _fansi
  returned "" (non-TTY), leaking bare \x1b[0m into pipes. RESET is now only
  added when an opening color code exists.
- P-006 deps_status flagged "luadec (optional, not packaged)" as missing,
  tripping the Lua-menu dependency gate. Optional rows are now filtered from
  missing when the fix line says "optional".
- P-007 ProgressFrame total allowed cur via .phase() only; lua_decompile used
  the constructor cur kwarg which doesn't exist -> TypeError on enter.
  Use frame.phase("Preparing...").
- P-008 ljd rawdump/pseudoasm print "Invalid magic"/"unknown opcode" warnings
  straight to stderr on foreign chunks. Parse + write wrapped in
  contextlib.redirect_stderr. Also: exec traceback hidden from UI (honest
  attempts list only).
- P-009 Section A audits: flow_test now cycles ALL 10 themes (switch ->
  persisted in ~/.ikramtool/config) and asserts zero ANSI escapes + no naked
  text outside boxes on a non-TTY pipe (vip_ui.is_tty patched to False).

## Test-count snapshot after PHASE FINAL
- tests/test_engine.py : 73 checks green (validator 8/8, quality /8, styles).
- tests/flow_test.py   : 55 checks green (10 themes, all pak ops, lua compile
  + decompile live against real fixtures + 696-entry Tencent pak, clears,
  empty/error/edge boxes, ANSI + naked-text audits).
