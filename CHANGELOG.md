# Changelog

## V112

### Full Rebuild — premium VIP experience
- **Brand lock:** IkramTool v112 is the only name used anywhere in the tool.
- **Premium UI engine:** every screen is a styled box (heavy/rounded/thick on
  your terminal, minimal on pipes) with live progress frames on operations.
- **10 colour themes:** Rainbow, Cyber Blue, Blood Red, Matrix Green, Gold
  VIP, Purple Reign, Ice White, Sunset Orange, Ocean Teal, Lava. Rainbow
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