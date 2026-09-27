# Changelog

## V121

### Bug fixes — a failed reinstall could leave you with no tool at all
- **The installer is now a transaction instead of a delete-then-copy.** This is
  the same hole V120 closed in the *updater*, in the *installer*. `install.sh`
  ran `rm -rf .engine` and then `cp -r` with the copy's stderr thrown away and
  its exit code never checked — and the script has no `set -e`, so a failed copy
  did not stop it. A full disk, a permission problem, or a Ctrl-C in that window
  left the user with a deleted engine and a half-written replacement, and the
  only way back was a manual reinstall.
- **The whole payload is now validated before anything is touched.** All eight
  required entry points (`ikram.pyc`, `ikram_patch.py`, `menus.py`, `engines.py`,
  `paths.py`, `vip_ui.py`, `run.sh`, `update.py`) must be present in the
  extracted package first. A truncated download is refused with the list of what
  is missing and an explicit "Nothing was changed."
- **The old runtime is moved aside, never deleted,** the new one is copied in,
  and the copy is then verified entry point by entry point. If any step fails,
  the partial copy is dropped and the previous version is moved straight back.
- **The success message can no longer be a lie.** The old final check accepted
  either `.engine/ikram.pyc` *or* a stale root-level `ikram.pyc`. On a legacy
  flat install that stale file survived, so a completely empty `.engine` could
  still report "Tool installed."
- **Legacy split-brain installs are cleaned up.** Pre-`.engine` versions left
  `ikram.pyc`, `ikram_patch.py` and `run.sh` in the install root next to the new
  `.engine/`, so the old root `run.sh` would keep launching the old engine
  forever. They are now removed — but only after the new install is verified.

### Also fixed
- **The banner can no longer lie about the version.** `vip_ui._read_version()`
  had a hardcoded `"v120"` fallback. Any environment where `VERSION` is not
  readable — including the test sandbox, which remaps paths away from the repo —
  silently showed that frozen literal instead of the real version, so a version
  bump could go green across the suites and still ship a wrong banner. The
  fallback chain is now the `VERSION` file, then `ikram_key.json` (which the
  updater rewrites on every install), then the literal string `unknown`, which is
  obviously wrong rather than plausibly stale. The test harness now stages the
  real metadata so the production path is what gets exercised.
- **`release.sh` no longer hardcodes a version** in its push message.

### Tests
- The install section is extracted verbatim out of `install.sh` and run against a
  sandbox with failures injected, so the shipped shell text is what gets tested:
  fresh install, reinstall over a working install, truncated payload (must change
  nothing), copy failure (must restore the previous engine), and a legacy flat
  install (must clean the stale root engine while keeping the user's files).
  20 checks, all green.
- **Every published release was verified to auto-update to this version.** For
  each of V105, V106, V107, V108, V109, V110, V111, V113, V114, V116, V118 and
  V119: that release's real zip was installed using that release's own layout,
  then that version's **own** updater was run — because the update is performed
  by whichever version the user currently has, not by the new one. All twelve
  reached V120, all twelve kept `DROP/` and `RESULT/` intact, all twelve ended
  with a correct activation-key hash, and all twelve still booted afterwards.
  The four flat-layout versions (V105–V108) and the eight `.engine` versions
  were both covered.

### Notes
- The V120 changelog overstated what its updater fix did; the correction is
  recorded in that entry rather than quietly rewritten.
- UI, menu text, menu flow, colors, engine order and the DROP/RESULT layout are
  unchanged. This release touches installation safety only.

## V120

### Bug fixes — the tool could freeze with no error, and the updater stopped telling the truth
- **The updater is now a verified transaction, and cannot half-apply:** the
  payload is validated first (every required entry point must be present, file
  count sane), extraction is guarded against archive entries that write outside
  the staging directory, the old runtime is **moved aside** instead of deleted,
  the new set is copied and then verified, and every failure path restores the
  previous install. DROP, RESULT, VERSION and the activation key are never
  touched.
  - *Correction, V121:* the original V120 note claimed the old updater
    "deleted the running tool's files first and copied the new payload second,
    with nothing in between", and that a stopped download therefore left users
    uninstalled. That was wrong about the updater. Its replacement removed only
    files **absent from the new zip** and always downloaded before touching
    anything on disk, so an interrupted download could not have uninstalled
    anyone. The genuine delete-then-copy hole was in `install.sh`, which was not
    touched until V121 — see that entry.

- **Updates report the truth:** `do_install` returns a real success value,
  `INSTALLED_OK` is printed only after a complete verified install, a refused
  payload prints `UPDATE_ABORTED` with the reason, and `update.sh` (which runs
  under `set -e`) no longer prints "Update done" after a failed update.
- **Activation key hash typo fixed:** the fallback branch in `update.py` held a
  transposed copy of the key hash. If the key file was ever unreadable, the
  tool would have written a hash it could no longer validate. The hash now has
  a single source of truth (`ikram_key.json`); `release.sh` reads it instead of
  retyping it, and a test cross-checks all three.
- **Key sweep no longer freezes the UI:** recovering a protected chunk's XOR /
  additive key tried 3,600 candidates and transformed the *whole* file in a
  Python byte-loop for each one, so a 350KB file could sit frozen for minutes
  with no output. The transform is now one C-level pass per key phase, a
  12-byte header check gates every candidate before any full transform, the
  search is capped by a wall-clock budget and a subprocess-probe cap, and it
  reports progress. All 12 real key lengths still recover exactly.
- **LJD decompile can now be stopped:** the LuaJIT engine ran in-process, so
  its timeout was decorative — a malformed chunk could spin forever and the
  tool froze with no error. It now runs in a dedicated child process, so the
  timeout is enforced and a hang is killed instead of hanging the tool.
- **The time budget is a real ceiling:** the pipeline arms a hard deadline that
  every engine timeout is clamped to, so the cascade cannot overshoot the
  user-visible limit by one long engine run on a late tier. An exhausted budget
  is reported as an attempt line instead of looking like a freeze.
- **The pipeline never raises:** an unexpected failure anywhere in the cascade
  becomes the normal honest failure report with its `FAILED.txt` and method
  list, so the menu can't get stuck on a spinner behind a traceback.

### PAK TOOL option 4 (Costom PAK) — the option now does what its own menu text promised
- **Option 4 used to crash:** the compiled core has no `pak_costom_pak`, so
  choosing Costom PAK raised `AttributeError` and dropped the user into the
  "Unexpected error" box. It is now implemented in `menus.pak_custom()` against
  the same engine layer the other three PAK options use.
- **A number now picks a FOLDER, as advertised.** The menu has always said
  "number = pick 1 folder", but the handler picked a single *file* out of the
  flat path list. The numbered list is now built from the pack's real folder
  prefixes, with each entry showing how many files it holds, and choosing one
  takes every file under it.
- **A typed path now COPIES, as advertised.** The menu has always said a typed
  path is "copied (not empty)", but every branch wrote 0-byte bodies. A typed
  path now pulls that file's real bytes out of the template pack; the empty
  skeleton trick is kept for ENTER and for folder numbers, which is what those
  two are for.
- **The subset is exact.** `Ue4Pak.repack()` keeps every original entry unless
  told what to delete, so a subset build would silently have shipped the whole
  pack. The delete list is what makes "one folder" mean one folder.
- The output is `RESULT/CostomPak/costom_<timestamp>.pak` and never overwrites
  an existing file.

### Also fixed
- **`run.sh` no longer fails silently:** when neither `ikram_patch.py` nor
  `ikram.pyc` was present it exited 0 having done nothing, so a half-extracted
  or broken install looked exactly like a clean run. It now says what is wrong
  and exits 1.
- **Closed input no longer spins forever:** `input()` keeps raising `EOFError`
  on a closed stdin, so every "invalid option — try again" loop turned into a
  100% CPU spin that could never end. Every re-prompt now checks for end of
  input and unwinds to the previous menu instead. A real ENTER is still treated
  as a real ENTER.
- **No more crash on the first-run dependency install:** the dependency prompt
  called a `close()` on the progress box that has no such method, so a missing
  Lua tool on a fresh phone ended in the error box instead of installing.
- **One version, one place:** the banner carried its own hardcoded `v119` while
  `VERSION`, the activation key and this changelog were already `V120`. The
  banner now reads the `VERSION` file, which is the same one the updater and the
  key check use.

### Tests
- Four new permanent suites plus an end-to-end driver, all green:
  `tests/test_decompile_safety.py` (40) and `tests/test_updater_safety.py` (60)
  for the safety work, `tests/test_costom_pak.py` (20) for option 4 including
  engine interop and closed-stdin behaviour, `tests/test_menu_e2e.py` (60) for
  every advertised menu path, all 267 themes, real clears and navigation, and
  `tests/flow_test.py` which drives the real compiled core through PAK 1/2/3/4
  and Lua 1/2 on generated packs, including a byte-exact inject check.
- The decompile suite covers transform parity, all 12 key lengths, the 350KB
  sweep, the LJD timeout (including a worker that deliberately never returns),
  empty/truncated/garbage inputs, the cascade exception guard, the hard
  deadline, payload validation, zip-slip, mid-install copy failure rollback,
  incomplete-install rollback, and a full `do_install` run over a real archive.
- **Three tests were lying or fragile and were repaired rather than deleted:**
  a non-TTY colour check ended in `or True` and could never fail; a progress
  assertion counted how many offsets finished inside a wall-clock budget, so it
  failed on a fast machine with nothing broken; and the Costom PAK case still
  expected the old output name and wording.

### Notes
- UI, menu text, menu flow, colors, engine order and the DROP/RESULT layout are
  unchanged. Option 4 is the one behavioural change, and it is a change *toward*
  the text it already shipped with.
- **Known limits, stated rather than hidden:** a v10+ UE4 pak cannot be built as
  a Costom PAK (the engine refuses to repack them, and the external packer
  writes a corrupt index when a pack mixes 0-byte entries), so the tool reports
  that plainly instead of writing a broken file. No genuine Tencent pack was
  available to verify against, so the Tencent copy path is written defensively
  and raises a clear error rather than guessing.
- No changelog entry exists for V117–V119; this is the first entry above V116.

## V116

### Bug fixes
- **Install-layout paths fixed:** on the installed layout the tool resolves
  DROP/RESULT to the lowercase outer `drop`/`result` folder (where you drop
  and collect files). The end-to-end flow suite now runs against the real
  installed layout and every scenario passes (unpack, inject, repack,
  costom-pak, clear, lua round-trip) — on top of the release-layout suite.
- **Trailing fix in minute phrasing** — banner now shows the current version
  instead of a stale "v114" label (menu header + exit box).

### Notes
- Runtime payload identical to V115 apart from the display-version sources;
  published so the update channel can roll everyone from V115 to a clean
  all-green build after V115 was removed.

## V115

### Features — IKRM-protected Compile (every Lua compile now ships armored)
- **Compile is protected by default:** every Lua compile now runs the full
  IKRM pipeline — dead-proto inflation (2–4 MB payload) + per-file HKDF-SHA256
  rotating-key encryption + `IKRM` wrapper header + SHA-256 checksum — so the
  output cannot be decompiled or re-read by automated tools (unluac.jar,
  unluac_rs, ljd, luadec all reject at byte 0).
- **Tool internals stay compatible:** Decompile and the internal pipeline
  auto-detect the `IKRM` wrapper and decrypt before working, so
  compile → decompile round-trips keep working; corrupted payloads get an
  honest error instead of a silent dump.
- **Every source shape routes to the protected compiler:** single-line /
  minimal scripts (`print("X")`, `x = 1`) now classify as Lua source and hit
  the protected path instead of falling through to the legacy unprotected
  compiler.
- **UI, paths and messages are identical** — same menu labels, same
  DROP/RESULT flow, same `OK -> BGMI bytecode (...)` message (now with an
  `IKRM-protected` note + register check). Kill-switch `IKRM_PROTECT=0` still
  reproduces the old exact output.

### Notes
- Game/loader side must strip the `IKRM` wrapper before use — reference
  decryptor logic is `stage3_unwrap` (ikram_upgrade.py).

## V114

### Bug fixes
- **Self-update success box fixed** — the TTY success panel used a 4-placeholder
  `format()` with only 3 arguments, raising `IndexError` on every successful
  on-device self-update; the update was applied but reported as failed
  (`INSTALLED_OK` never printed). Now renders and exits cleanly.
- Version bumped to V114 across the tool (UI brand, `VERSION`, key metadata,
  installer, docs, tests).

## V112

### Full Rebuild — premium VIP experience
- **Brand lock:** IkramTool v112 is the only name used anywhere in the tool.
- **Premium UI engine:** every screen is a styled box (heavy/rounded/thick on
  your terminal, minimal on pipes) with live progress frames on operations.
- **10 colour themes:** Neon Pink, Cyber Blue, Blood Red, Matrix Green, Gold
  VIP, Purple Reign, Ice White, Sunset Orange, Ocean Teal, Lava. Neon Pink
  paints every single character of the UI. Theme saved to `~/.ikramtool/config`,
  applied instantly from the Themes menu.
- **Terminal restore on exit** — Ctrl+C anywhere leaves the terminal clean.

### Original engines kept intact (delegation)
- The compiled pak/lua engines (unpack, inject wizard, repack, costom pak,
  lua compile/decompile) run **exactly as before**, unchanged, verified
  byte-exact against golden Tencent paks. V112 only re-skins and points the
  menus at them.
- Known original behaviour preserved: `RESULT/Repacked/<name>.pak`
  overwrites on repeat repacks; unpack writes game-processable copies to
  `RESULT/processed/<name>/` while the `RESULT/extracted/<name>/` tree stays
  raw-clean; the "CostomPak" spelling is original.

### Fixed folder system
- Frozen paths: `DROP/pak`, `DROP/lua`, `DROP/inject` (lowercase — Android
  is case-sensitive) and `RESULT/extracted`, `RESULT/injected`,
  `RESULT/lua`, `RESULT/processed`, `RESULT/CostomPak`, `RESULT/Repacked`.
- Legacy case-twin `RESULT/repacked/` is purged automatically on boot so the
  "Result/ me 2 folders" bug never returns (double repack fix).
- No file-picking text input anywhere — drop in, pick from the list.

### PAK TOOL — 4 operations + C/R
- Unpack — pak → `RESULT/extracted/<name>/`.
- Inject — files from `DROP/inject/` into a pak → `RESULT/injected/<name>.pak`
  (CHOOSE MODE: 1 = one file, 2 = inject all, auto-put).
- Repack — rebuild a pak from its edited extraction →
  `RESULT/Repacked/<name>.pak` (original DROP pak never touched).
- Costom Pak — extracted tree → `RESULT/CostomPak/<name>.pak`.
- `C` / `R` clear `DROP/pak` / `RESULT` from the menu.

### LUA TOOL — 2 operations + intelligence engine
- Compile — `.lua` → protected game bytecode in `RESULT/lua/`.
- Decompile — game bytecode/`.luac` → readable source. Lua Intelligence
  Engine detects file format + encryption level (magic bytes + Shannon
  entropy), tries every available decompiler, picks the best result and
  honestly validates it. Success → `<name>_decompiled.lua` with a quality
  score; unreadable/encrypted files → `<name>_FAILED.txt` explaining why.

### Engineering
- Full codebase audit; Unpack/Inject/Repack verified byte-exact against
  golden Tencent paks.
- Scripted flow suite runs every flow in a fresh isolated process (boot,
  clear, unpack empty, real 696-entry unpack, real inject, real repack,
  costom pak, lua compile+decompile round-trip) — all passing.
- Engine suite (73 checks) all passing; live key gate verified
  (`FREETOOL` unlocks).
- Errors shown in honest boxes with a "Next:" step — never a raw exception.

## V111

- COSTOM PAK for UE4-standard paks now builds a real empty pak
- Fresh installs verify correctly on first run
- Install reliability fixes for `curl | bash` on phones
- System info + storage checks during install