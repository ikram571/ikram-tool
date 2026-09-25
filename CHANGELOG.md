# Changelog

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