# IkramTool V111 → V112 — FLOW DOCUMENT (original ground truth)

Source of truth: original live install at `~/Ikram_Tool/.engine/` (V111),
verified by (a) plaintext overlay source, (b) `marshal`+`dis` bytecode
disassembly of `ikram.pyc` and every `.pyc`, (c) prior analysis docs
(`IkramTool_Analysis/INJECT_WIZARD_SPEC.md`, `UI_MAP.md`, `OPTIONS.md`,
`PHASE1_MAP.md`). Every flow below was confirmed against live bytecode on
Python 3.14.6.

Purpose: single reference proving the upgraded tool preserves the original
A-to-Z behaviour. Anything marked **NEVER-CHANGE** must be byte-identical in
V112. Anything in §10 is the ONLY permitted delta.

---

## 1. Entry / install / launch

1. Install: `curl -sL https://raw.githubusercontent.com/ikram571/ikram-tool/main/install.sh | bash`
   - creates `~/Ikram_Tool`, installs python/git/curl/unzip/lua53/clang/java,
     pip `rich pycryptodome zstandard gmalg`, bundling `run.sh`,
     `unluac.jar`, `unluac_rs`, `lua_patched`, `luac_patched`, `repak`,
     `ikram_sm4_fast.so`(+`.c`), `ljd.zip`, all `.pyc` cores, all overlays.
   - install.sh writes the `ikram` shell function to `~/.bashrc` and a
     `/data/data/com.termux/files/usr/bin/ikram` launcher.
2. `ikram` (bash fn / bin):
   - `PYTHONDONTWRITEBYTECODE=1`
   - if `~/.bashrc` fn run in a fresh shell: if `ikram_patch.py` missing →
     silent self-repair (downloads release zip, `cp -r` into `.engine`,
     `chmod +x`, rerun). If `ikram.pyc` magic ≠ current python magic →
     `pkg upgrade -y python`, rerun.
   - % -> `python3 ~/Ikram_Tool/.engine/ikram_patch.py "$@"`.
3. `ikram_patch.py` (plaintext overlay, 1106 lines):
   - imports the whole compiled core: `spec_from_file_location("ikram", ikram.pyc)`.
   - mkdirs ALL folders (§3).
   - `_purge_legacy_repacked_folders()` — removes any legacy lowercase
     `RESULT/repacked` twin so only `RESULT/Repacked` survives (the V109
     "2 repacked files" fix).
   - `_patch_ue4_default_key()` — patches a hardcoded default UE4 AES key
     into the loaded `ue4` module.
   - defines 6 PAK functions and monkey-patches them onto `ikram`:
     `pak_extract`, `ensure_input_folder`, `pak_inject`, `pak_repack_folder`,
     `pak_costom_pak`, `pak_tool_menu`.
   - V112 addition: tail is `if __name__ == "__main__": import vip_ui`
     (V112 UI layer takes over the menu shell; engines unchanged).
4. CLI flags (compiled `ikram.pyc` `__main__`): `--setkey <key>` writes a
   keyhash via keymod; `--checkupdate` prints UPDATE/LATEST.

## 2. Boot lifecycle (`ikram.main()`)

```
main():
  clear_screen()
  _cleanup_old_layout()        -> rm tree of legacy dirs under RESULT/lua
  check_updates_auto():
      ver = update.latest_remote()   GET api.github.com/repos/ikram571/ikram-tool/releases/latest
      if ver > keymod.current_version():       # version_tuple compare, strip vV
          update_screen()                      # "⬇ Updating... downloading new update ⬇"
          update.do_install()                  # §8
          console.print "Update installed! Restarting..." ; time.sleep(2)
          os.execv restart                     # re-exec python3 ikram_patch.py
  key_lock():                                  # returns True/False; False -> exit silently
  welcome_splash()
  loop:
      c = main_menu()
      '1' -> pak_tool_menu()     # patched overlay (4 options)
      '2' -> lua_tool_menu()     # compiled (2 options)
      '0' -> exit_screen() + sys.exit(0)
      else -> invalid_choice() + pause()
```

### key_lock (NEVER-CHANGE behaviour)
- banner: `✦` × width(60) centered gold, `print_title()` rainbow brand,
  `✦` × width(60) accent stripe, then a box:
  - width: `box_w = min(console.width - 4, 44)` if tty else 40.
  - top `╭` + `─`*(box_w-2) + `╮`
  - label row: `│  [bold VIP]🔑 Enter key:[/] [bold CYAN]` (drawn with
    `end=""`, no newline)
  - key prompt `input("")` → strip → `k`
  - **quirk preserved**: bottom border is `╰` + `─`*(box_w-2) + **`╮`**
    (right corner is `╮`, not `╯`).
- `if k.lower() in ("exit","quit","q")` → return False.
- `key_ok = keymod.check(k)` — check lives in key.pyc; ties to VERSION +
  `ikram_key.json` `key_hash` (THE hash is **never** re-derived/re-exported).
- key_ok → `✔ Key valid. Tool unlocked!` then `telemetry.send_login()`
  (posts device name + time to owner Telegram), sleep 1, return True.
- else → `✘ Invalid key! Please try again.`, sleep 1, loop.

### welcome_splash
- non-tty: only prints `◈ IKRAM TOOL ◈` horizontally centered. No boxes, no
  delays.
- tty: full splash — `✦` bars, "Welcome to Ikram Tool 👑", `📦 PAK • 📜 LUA`,
  `✦ Ikram Tool ✦`, then `Loading...` 1.5 s, `Starting...` 1.5 s, sleep 0.5,
  clear.

### exit_screen
- `Thank You for using Ikram Tool!`
- `❤ made with love, for all players ❤` (coloured line)
- `✦ See you soon ✦`

## 3. PATH SYSTEM (NEVER-CHANGE — Section G)

Tool dir: `~/Ikram_Tool/.engine/` (= `TOOL_DIR`). Repo/install also mirrors:
`~/Ikram_Tool/DROP` → symlink to repo `drop`; `~/Ikram_Tool/RESULT` → `result`.

```
DROP/pak     input paks / assets to process        (LOWERCASE sub)
DROP/lua     lua sources / bytecode to process     (LOWERCASE sub)
DROP/inject  files to inject into the pak          (LOWERCASE sub)

RESULT/extracted   unpacked pak trees              (exact names)
RESULT/injected    paks after injection
RESULT/lua         all compile/decompile results
RESULT/processed   unpack secondary sidecars (option-1 auto-process)
RESULT/CostomPak   custom paks            (NOTE: "CostomPak" spelling)
RESULT/Repacked    repacked paks          (NOTE: "Repacked" spelling)
```

**NEVER-CHANGE rules for outputs:**
- Unpacked tree: `RESULT/extracted/<pakstem>/`, and if that exists,
  `RESULT/extracted/<pakstem> (1)/`, `... (2)/` — never overwrite.
- Injected: `RESULT/injected/<pakname>.pak`, conflicts resolved by
  ` (<n>)` suffix inside PakWriter — original pak file is NEVER modified.
- Repacked: `RESULT/Repacked/<pakstem>.pak` — overwrite IS allowed here
  (that's the original behaviour).
- Costom: `RESULT/CostomPak/<name>.pak` — never overwrite.
- Conflict rule everywhere: `name (1)`, `name (2)` — space + parentheses.
  No underscores.

## 4. MAIN MENU (compiled — NEVER-CHANGE content)

- `Table` HEAVY box inside a panel; title `MAIN MENU [bold MUTED](<ver>)`
  (ver from keymod.current_version()), subtitle `choose a number`.
- rows:
  - `[1] 📦 PAK TOOL (UNPACK, INJECT, REPACK)` — help `unpack, inject, repack pak files`
  - `[2] 📜 LUA TOOL (COMPILING, DECOMPILING)` — help `compile / decompile lua (auto-detect)`
  - `[0] EXIT` — help `close the tool`
- prompt: `➜ SELECT: `
- invalid → `invalid_choice()` (red `✘ Invalid option — choose a number from the menu above.`) + pause.
- **V112 delta (§10)**: menu becomes `1 PAK Tool · 2 Lua Tool · 3 Themes · 0 Exit`.
  Themes is NEW (not in V111). Items 1/2/0 preserved.

## 5. PAK TOOL (overlay, monkeypatched `pak_tool_menu`)

Title `📦 PAK TOOL 📦`, box `MENU_BOX`, prompt `-> Select: `.
Rows + WORK/PUT-FILE-IN/OUTPUT help (NEVER-CHANGE help text):
- `[1] 📦 Unpack PAK` — WORK: take all files out of the pak. PUT FILE IN: DROP/pak. OUTPUT: RESULT/extracted/
- `[2] 📦 Inject File` — WORK: put any file (lua/uasset/asset) into the pak — type is found automatically and added to the game. 1 file or all files at once — auto or manual path. PUT FILE IN: DROP/inject + DROP/pak. OUTPUT: RESULT/injected/
- `[3] 📦 Repack PAK` — WORK: build the pak again. 1) first UNPACK the pak 2) edit files in RESULT/extracted 3) old pak files are NEVER touched. OUTPUT: RESULT/Repacked/
- `[4] 📦 Costom Pak` — WORK: make an empty pak. ENTER (no typing) = ALL folders + all file names but EMPTY files (real in game when you inject into it). number = pick 1 folder · typed path = only that path + its files copied (not empty). PUT FILE IN: DROP/pak. OUTPUT: RESULT/CostomPak/
- `[0] Back` — back to main menu

Dispatch: `1`→pak_extract, `2`→pak_inject, `3`→pak_repack_folder,
`4`→pak_costom_pak, `0`→return, else invalid_choice+pause.
**V112 delta**: the SAME 4 options rendered by the theme layer; added extra
`C` Clear DROP/pak and `R` Clear RESULT helpers (additive, default-off menu utils).
Label `Costom Pak` spelling preserved.

### 5.1 UNPACK (`pak_extract` — overlay)
1. items = all files under `DROP/pak` (recursive, hidden excluded).
   none → error `✘ No PAK/asset files found in DROP/pak. Add some and try again.` + pause.
2. show UNPACK MODE table:
   - `[1] UNPACK ONE FILE`
   - `[2] UNPACK ALL N FILES`  (N = count)
   - `[0] CANCEL`
   - prompt `> CHOOSE MODE: ` → invalid paths reuse invalid_choice.
3. `0` → error `✘ Cancelled — nothing unpacked.` + pause.
4. Mode 1 (`_choose_pak_index`):
   - pak list table `📦 FILES IN DROP/pak (N)` (numbered, sizes)
   - `0 = cancel`
   - prompt `> UNPACK ONE number (ENTER = auto first): `
     - ENTER → first pak
     - invalid int / out of range → `✘ Invalid number — 1 se N tak choose karo.` + pause.
5. per pak: `raw_dir = RESULT/extracted/<stem>` via `_unique_out_dir` (never overwrite).
   `_unpack_one(raw_dir)` → detect type (tencent / ue4 / zip) →
   `engines.unpack_pak` with a progress overlay `📦 <pakname>` (per-file `▸ <file>` summary rows, live).
   - 0 files → error `✘ No files unpacked from <pak> (may be encrypted or unsupported).` + TG `send_error`.
   - else success `✔ <N> files unpacked -> RESULT/extracted/<stem>` then AUTO-PROCESS:
     `_auto_process_tree` → `RESULT/processed/<stem>/` sidecar JSON/text for each asset
     with a `⚙ PROCESSING FILES` progress title; final `✔ <name> unpacked/processed -> ...`.
6. Standalone (non-pak) file: header `=== PROCESSING <name> ===`,
   `_process_standalone` → raw copy to `RESULT/extracted/<stem>/` + sidecars to
   `RESULT/processed/<stem>/`. success `✔ <name> unpacked/processed -> ...`; errors → `report_error`.
7. Mode 2: loop all items (pak ⇒ 5/6; asset ⇒ 6).
   Final totals box: `✔ Total: N pak(s) unpacked (M files) + K asset file(s) processed`
   or (0 total) red `0 files unpacked total — check the files are supported.` + pause.

### 5.2 INJECT (`pak_inject` overlay → compiled wizard)
1. items = all files under `DROP/inject` (rglob). none → error + pause.
2. `pakf = ensure_input_folder()` — pick a `.pak` from `DROP/pak` (numbered list, `pick_file`). none → error + pause.
3. `kind = detect_pak_type(pakf)` (tencent / ue4 / zip). unsupported → `_unsupported_pak(pakf)` + pause.
4. build path index: all paths inside pak (basenames lowered, sorted); folders = unique folders minus hidden `.txt`.
5. INJECT FILES table: `# / name / size / typ(e)`; then CHOOSE MODE box:
   - `[1] INJECT ONE FILE`
   - `[2] INJECT ALL N FILES`
   - `[0] CANCEL`
   - prompt `> Select: `.
6. Mode 1: prompt `FILE NUMBER` → the file; show `File: <name>`.
   `_resolve_inject_path(file, ...)`:
   - WHERE TO PUT THIS FILE? box shows the auto-suggested target (or `✘ could not find a match` warn)
   - EXAMPLE PATHS box (when no suggestion) and Game folders box (when folders exist)
   - prompt `ENTER = auto · number = folder · path = full path → `:
     - a number → that folder
     - a `/` path → that target (validated; `✘ Path not found in this pak` retry)
     - ENTER → auto suggestion
   - remembered: `(file, target, is_new)` where is_new = folder not present.
   - `placed` list accumulates (mode 2 loops all files; >1 match → `_pick_from_matches` box
     `found in N places — where to put it?` `number = choose path · 0 = cancel`; 0 → resolve prompt).
7. READY box `📦 N FILE(S) READY` — each row `📦 <name> -> <target>` and
   `(new — folder will be created)` or `(replace existing)`.
8. pre-write: `_inject_working_bytes` per file (lua → game bytecode via univ/mega_lua;
   uasset → cooked bytes; raw → as-is). empty/broken → `contact_owner` + skip that file.
9. progress `📦 INJECTING` → `_inject_many_into_pak`: tencent → PakWriter.inject_files
   (target_path, force_add, auto-replace same-name); ue4 → replace/add via repak.
   Output `RESULT/injected/<pakf.name>` (unique-` (n)` inside writer if exists).
10. done box `📦 INJECTED N FILES` → subtitle `-> RESULT/injected/<name>` then
    `show_success("Done: N files injected (game-ready)")`. exception → `report_error`. pause.

**Inject wizard ordering (Section G, NEVER-CHANGE):** type detect → target list →
show paths → confirm → inject → output. The compiled wizard functions
(`pak_inject`, `pak_inject_all`, `pick_inject_file`, `_inject_into_pak`,
`_inject_many_into_pak`) are kept as-is and are the flow V112 wires into.

### 5.3 REPACK (`pak_repack_folder` — overlay)
1. `pakf = ensure_input_folder()`.
2. `edit_dir = RESULT/extracted/<pakstem>`; missing →
   `✘ Extracted folder nahi mili: RESULT/extracted/<stem>` +
   `Pehle is pak ka UNPACK karo, phir REPACK karo.` + pause.
3. `out = RESULT/Repacked/<pakstem>.pak` (mkdir; delete existing so fresh).
4. header `Repacking <pak> -> <out> (auto folder: RESULT/extracted/<stem>)`. (warn line)
5. detect type: ue4 → prompt `-> <pak> AES key (ENTER = built-in default): ` (engines key store).
6. `engines.repack_folder` — tencent: PakWriter inject-tree force_add (mount-normalized);
   ue4: repak pack Zlib → python-ue4 fallback.
7. `_purge_legacy_repacked_folders()` after.
8. success `✔ <N> files repacked -> out` else `report_error`. pause.

### 5.4 COSTOM PAK (`pak_costom_pak` — overlay)
1. paks = `DROP/pak` `.pak` files. none → error + pause.
2. `_choose_pak_index` (title `COSTOM PAK`). Header `=== COSTOM PAK <name> ===`.
3. `out = RESULT/CostomPak/<name>.pak` (unique, never overwrite).
4. detect type: ue4 → AES key prompt; tencent → `_pick_folders`:
   - box `📦 "<name>" — N folders` (folder list, numbered, recursive chains)
   - help `number = choose folder · 0 = cancel · type new path = auto under ShadowTrackerExtra`
   - prompt `> Select: `
   - ENTER → `_SKELETON` sentinel → FULL SKELETON (every folder + every file name, ALL EMPTY bodies)
   - `0` → cancel (error + pause)
   - number → that folder chain, files copied REAL
   - typed path → `_sanitize_custom_path` (auto under `ShadowTrackerExtra`); if target NOT in
     source → `_prompt_empty_file_name`:
     box `Folder 'X' source pak me nahi hai → empty file banega.`
     `0 = cancel`, prompt `> File name (e.g. Xxx.lua): ` → single EMPTY file at that path.
5. `_make_costom_pak`: tencent PakWriter skeleton/empty-file/subtree-copy
   (`inject_skeleton`, `inject_empty_file`, `inject_subtree_copy`, `_trim_tencent_pad`);
   ue4 standard → repak pack Zlib (empty).
6. result rows:
   - skeleton → `• ALL folders + all file names, EMPTY bodies`
   - chain → `• <dir>` per dir
   - empty file → `• <file> (empty file)`
   - subtree → `• N file(s) copied byte-identical`
   then `show_success("✔ Costom Pak ready: N folders, M files -> out")`. exception → `report_error`. pause.

## 6. LUA TOOL (compiled `lua_tool_menu`)

Title `📜 LUA TOOL 📜`, box `MENU_BOX`, prompt `-> Select: `.
- `[1] 📜 Compile (+ PROTECT)` — compile lua to game bytecode; `.lua` also protected
- `[2] 📜 Decompile` — decompile game bytecode back to readable source
- `[0] Back`
Dispatch `1`→lua_compile_one, `2`→lua_decompile_one, `0`→return, else invalid_choice+pause.
**V112 delta (§10)**: same 2 options in theme layer + `C`/`R` clear utils. No behaviour change.

### 6.1 Compile flow (compiled)
1. `_scan_lua_inputs('compile')` = every file under `DROP/lua` recursive with ext in
   `.py / .json / .java / .lua`. none → `✘ No files found in DROP/lua. Add files there and try again.` + pause.
2. `_pick_lua_items(title="📜 Compile — choose a file")`:
   - 1 file → auto pick it
   - many → numbered table `# | name | size` + `[A] = ALL files · 0 = cancel`, prompt `> Select number: `
     - `A` → all files
     - `0` → None (→ silent return)
3. per file: header `▸ <relpath>`, then `lua_compile_path(src)`:
   - `kind = univ.detect(src)`
   - if kind is already bytecode (Lua 5.x / LuaJIT / encrypted, not `Lua source`) →
     fail `✘ This file is already compiled. Use Decompile (option 2) instead.`
   - `.py` → `RESULT/lua/<name>.pyc`; `.java` → `RESULT/lua/<stem>.class`;
   - `.lua` → `lua_protect.protect_compile(src, RESULT)`:
     panel `📜 Compiled + Protected` + `1 file -> RESULT/lua/` (artifact `<stem> [compiled].lua`)
   - else (incl. `.json`): `[bold X]Compiling... please wait[/]` + progress box `🔨 Compiling...` +
     `univ.compile_any(src, out)`:
       - success → `📜 Compiled` + `1 file -> RESULT/lua/<name>` + `show_success("Compiled")`
       - failure → `telemetry.send_error(RuntimeError("compile failed: "+msg))` + `contact_owner`
   - per-file row: `✔ <name> compiled` / `✘ <name> failed`; final `📜 Compile Done`
     + `Failures:` rows `- <name>` (+ `... and N more files`).
4. V112 (engine only, §10): compile now routes through `mega_lua.compile_bgmi` →
   `lua_pipeline` (same tiered std-compile chain: patched luac keeps debug info,
   `_std_to_bgmi` conversion, register-cap 255 check). Output naming/paths unchanged.

### 6.2 Decompile flow (compiled)
1. `_scan_lua_inputs('decompile')` = EVERY file under `DROP/lua` recursive (no ext filter).
   none → same error box as compile. pick via `_pick_lua_items("📜 Decompile — choose a file")`.
2. per file: header `▸ <relpath>` → `lua_decompile_path(src)`:
   - `[bold X]Decompiling... please wait[/]`; `out_root = RESULT/lua` (mkdir).
   - `kind = univ.detect(src)`:
     * `Lua source` / `Python source` / `Java source` → `shutil.copy2(src, RESULT/lua/<name>)` →
       `📜 Decompiled` + `Already readable — copied as working file` (ok).
     * Unreal asset (UETool JSON) → copy as `<stem> [UnrealEngine]<ext>` →
       `UETool JSON — already editable -> RESULT/lua/` (ok).
     * non-Lua binary map (`univ.decompile_any`): UE blueprint→`<stem> [decompiled].json`,
       pyc→`.py`, Java JVM→`.java`, DEX/APK→`.java`, ELF→`.c`, PE→`.c`, Mach-O→`.c`;
       file must exist and be non-empty; ok → `show_success("Decompiled — working file ready.")`.
     * else (Lua bytecode / unknown) → `univ.decompile_multi_engines(src, out_root)`:
       result rows `✔ <label>` (green) / `✘ <label> (no output)` (red);
       header `📜 Decompiled` + `{ok}/{N} methods OK -> RESULT/lua/`;
       - ok==0 → `contact_owner("This file could not be decompiled. It may be protected or encrypted.")`
       - ok>0 → `show_success("Decompiled — working file ready.")`
   - per-file row: `✔ <name> decompiled` / `✘ <name> failed`; final `📜 Decompile Done` + failures.
3. V112 (engine only, §10): the multi-engine call routes through `univ.decompile_multi_engines`
   → `mega_lua.decompile_bgmi` → `lua_pipeline` tier cascade (same outer contract:
   8-check validator, readable-source trust, honest decrypt-fail on hostile input).
   Artifacts still land `RESULT/lua/`, still `*_GAME.lua` for readable output.

## 7. Shared helpers (compiled, behaviour NEVER-CHANGE)

- `safe_input(prompt)` — returns stripped input; EOFError/KeyboardInterrupt →
  exit path.
- `eof_exit()` — True after EOF marker; exits menu loops.
- `pause()` — `Press ENTER to continue...`.
- `invalid_choice()` — `✘ Invalid option — choose a number from the menu above.`
- `pick_file(folder, exts, title)` — numbered file picker (`0 = cancel`).
- `drop_files(folder)` — list DROP files.
- `show_error/show_success/show_info/contact_owner` — themed panels; `contact_owner` is the
  "contact the owner" TG/report path.
- `report_error(e)` + `friendly_error(e)` — typed error panels + telegram on unexpected.
- `build_menu_table(rows, title, caption)` — rich Table (HEAVY box), numbered rows + help col.
- `detect_pak_type(path)` / `_unsupported_pak` — tencent/ue4/zip classify; unsupported box.
- `print_title()` — rainbow-gradient `IKRAM TOOL` + `📦 PAK • 📜 LUA`.
- `_cleanup_old_layout()` — rmtree legacy dirs under RESULT/lua.
- `_ProgressUI(title)` — live progress spine (phase + counter).
- `keymod.check(u)`, `current_version()`, `make_key` — key gate (VERSION-tied).
- telemetry `send_login()` / `send_error(exc, extra)` — owner TG, threaded, bounded.
- V112: all the above are rendered through `theme_engine`/`box_engine` (boxes keep the
  same content text; frame style comes from the theme). Content strings never change.

## 8. AUTO-UPDATE + SELF-REPAIR (Section E tie-in)

- `update.py`: `--check` → prints `remote|local`. Full run: `do_install()`:
  - GET `releases/latest`; asset `IkramTool.zip` (falls back to any `.zip`).
  - splash `✦ IKRAM TOOL UPDATE ✦ / 📦 PAK • 📜 LUA`; download progress box `⬇ Downloading update`.
  - extract to `.ikram_update_tmp`; unwind one nesting level if a single dir holds `ikram.pyc`.
  - `_clean_replace(src)`: delete every old file/folder in `.engine` EXCEPT
    `DROP, RESULT, VERSION, ikram_key.json, .ikram_update.zip, .ikram_update_tmp, .repair, repair.zip`;
    copy new files in; chmod 755 run.sh/install.sh/lua_patched/luac_patched/unluac_rs/repak.
  - stamp `VERSION` = `V<tag>` and `ikram_key.json.version` = same; key_hash untouched.
  - `✅ UPDATE INSTALLED SUCCESSFULLY!` / `Restart the tool to continue...`; spawn
    `_fix_env()` (pkg/pip deps + rewrite both launchers) in a daemon thread.
- `$PREFIX/bin/ikram` self-heal: missing `ikram_patch.py` → download zip → extract →
  `cp -r` into `.engine` → exec python3 ikram_patch.py.
- V112 publishes the same release shape (`IkramTool.zip` asset, tag `v<VERSION>`) so
  `check_updates_auto` performs a clean V111→V112 rollover on next `ikram`.

## 9. PAK/LUA ENGINE (Section C/F — internals, not behaviour)

- `engines.py` dispatch table: tencent → bunded `pak` (PakWriter), ue4 → `repak` →
  python `ue4` module (`_parse_full_directory_index` overlay-patched).
- `pakcrypto.pyc` holds Tencent CHUNK key material; `_patch_ue4_default_key` holds the
  default UE4 AES key; saved-UE4-key store in engines.
- `univ.py` (plaintext shim) exports detect/decompile_any/decompile_multi_engines/
  compile_any; delegates Lua to `mega_lua.py` (BGMI pipeline) and everything else back
  to the legacy `univ.pyc`. V112 bolts `lua_pipeline.py` in as the tier orchestrator
  with the same call contract; engine internals may improve, results do not change
  shape/where they land.
- Binaries (all on device, verified): `lua_patched`(5.3.6), `luac_patched`, `unluac_rs`
  1.3.1, `unluac.jar`, `ljd.zip` (LuaJIT), `repak` 0.2.3, `ikram_sm4_fast.so`, quickbms/u4pak optional.

## 10. V112 DELTA — the ONLY permitted changes

| Area | Original V111 | V112 | Frozen? |
|---|---|---|---|
| Menus shell | compiled rich UI | `vip_ui` theme layer, same options | content frozen |
| Main menu | PAK, LUA, EXIT | + **3 THEMES** (new feature) | base frozen |
| Themes | none | 10 themes (`theme_engine.THEMES`), persist in `~/.ikramtool/config`, live switch | new |
| PAK flows | overlay + compiled wizard | same exact flows through menus.py | Section G frozen |
| Lua engine | mega_lua cascade | mega_lua + `lua_pipeline` tier cascade + 8-check validator | contract frozen |
| Paths | lowercase DROP subfolders + mixed-case RESULT | **MUST match original exactly** (see §3) | Section G frozen |
| Deps | install-time | launch-time auto-check/install (Section E) | additive |
| Version | V111 | V112 (VERSION + ikram_key.json) | key_hash frozen |
| Release | tag v111, asset IkramTool.zip | tag v112, asset IkramTool.zip (update-compatible) | shape frozen |

## 11. ALIGNMENT CHECKLIST (must all pass before publish)

- [ ] `paths.py` recreated with original §3 paths (lowercase DROP subfolders,
      mixed-case RESULT incl. `processed`, `CostomPak`, `Repacked`); `unique` rule `(1)`.
- [ ] on-disk repo `DROP/` and `RESULT/` subfolders renamed to match.
- [ ] no `CUSTOMPAK` / uppercase subfolder string anywhere (menus, lua_pipeline, tests).
- [ ] Option-4 label stays `Costom Pak` (UI + help text).
- [ ] `VERSION`=V112, `ikram_key.json` version V112, key_hash byte-identical.
- [ ] grep `v111\|V111` empty except CHANGELOG history + git history.
- [ ] `run.sh` boots V112 UI green in non-tty audit (no ANSI, all boxes).
- [ ] tests: engine 73 + flow 55+ green after path rewrite; add path-set + unique-rule cases.
- [ ] live matrix: 696-entry Tencent pak (unpack → edit → repack hash-equal), inject (single+all,
      auto path + number + typed + new-folder), costom skeleton/folder-chain/empty-file,
      lua compile→decompile round-trip, decompile hostile-input honest-fail.
- [ ] CHANGELOG + README + INSTRUCTIONS fully V112 and truthful.
- [ ] tag `v112` → push → GitHub release `IkramTool V112` with `IkramTool.zip` asset
      (update-compatible URL preserved).