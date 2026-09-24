# PHASE 1 MAP — Ikramtool V111 static audit + README/INSTRUCTIONS reality map

Source: fresh clone `~/ikram_work/ikram-tool` (git tag V111, commit 949c0ff), Python 3.14.6.
Evidence corpus: `analysis/pyc_dump/<module>/{full,index}.txt` (all 16 pyc disassembled via `marshal`+`dis`),
`analysis/evidence.txt` (140 unique imports / 1712 unique string constants).

---

## 1. Architecture (verified)

Two-layer build, V111:

```
install.sh / release.sh / CI (main)
└─ ikram  (launcher fn in ~/.bashrc)
   └─ python3 .engine/ikram_patch.py          [PLAINTEXT overlay, V111]
      ├─ loads compiled core:  ikram.pyc      [V110-era UI, rich-based]
      │     └─ import/exec chains to engines:
      │        univ, pak, ue4, lua_ops, key, lua_protect, update, telemetry,
      │        (optional rich, struct, subprocess, sys...)
      ├─ overlays engines via importlib: engines.pyc(s) + pak/ue4/univ/crypto/lua pyc
      └─ bridges: assets (assetprocs.py), lua pipeline (univ.py -> mega_lua.py -> lua_bgmi.pyc)
```

### Compiled core modules (16 pyc, all honest `co_filename`)
`ikram, pak, ue4, univ(328KB), pakcrypto, crypto_engine, key, lua_engine, lua_ops,
lua_bgmi, lua_beautify, lua_protect, pattern_analyzer, sm4_custom, telemetry, update`.
Minor anti-forensics only: some code objects carry synthetic `co_filename`
(`<i__init__>`, `<p>`, `<e>`) — cosmetic, no payload hiding.

### Plaintext overlay (the V111 delta)
- `ikram_patch.py` — entry; patches compiled UI:
  * COSTOM PAK option `[4]` appended to PAK TOOL menu table
  * full Costom implementation: ENTER=skeleton, `<n>`=one folder chain (real copies), custom path,
    zero-pad removal, UE4 standard empty-pak builder (`_make_costom_pak`)
  * `_patch_ue4_default_key()` hardcodes/patches a default UE4 AES key into the loaded ue4 module
  * pak unpack/extract/repack glue, multi-file inject, TG notify + finish reports, folder pickers
  * `_purge_legacy_repacked_folders()` (the "2 repacked files" V109 fix)
- `engines.py` — external-tool resolver: repak/quickbms/u4pak PATH find, UE4 AES key candidates
  + saved-keys store, Oodle stats probe, sdk/version string builder.
- `assetprocs.py` — asset preprocessors: text/uasset/ubulk/locres/locmeta/shader(SPIR-V, DXBC)/binary → JSON+text.
- `mega_lua.py` (3080 lines) + `univ.py` — BGMI Lua pipeline (below).

### pip / external layer (all present on device)
- `rich 15.0.0`, `pycryptodome 3.23.0`, `zstandard 0.25.0`, `gmalg 1.1.2` — `install.sh` installs individually w/ retry.
- `lua_patched`, `luac_patched` (Lua 5.3 VM/compiler), `unluac_rs`, `repak` — bundled binaries.
- `unluac.jar` + `cfr.jar` via `java` (openjdk-17 per install), `ljd.zip` LuaJIT decompiler imported via zipimport
  (`sys.path.insert(0, <dir>/ljd.zip)`), `ikram_sm4_fast.so` (C SM4, ctypes) with `.c` source shipped.
- Optional external fallbacks seen in code: quickbms, u4pak, Ghidra (`_GHIDRA_ROOT`), reko — PATH-discovered, not bundled.

### BGMI Lua pipeline (mega_lua.py, verified from source + disasm)
- Decompile: BGMI bytecode → `_bgmi_to_std(lua_bgmi.bgmi_to_std)` → unluac-rs → readable →
  `_decrypt_prologue` (protected string tables) → `_fix_explicit_close` (unluac error marker
  goto-loop skeleton → structured for/if rewrite, parser-verified) → `_strip_prologue` →
  dead-register cleanup → name promotion → auto-close — one final `*_GAME.lua`.
- Cascade for hostile inputs: nadeem protector detect → zlib multi-section reconstruct →
  tool v3 protect decrypt → auto key-recovery (XOR/add) → dialect detect (LuaJIT/5.1/5.2/5.4/BGMI)
  → obfuscated-stub string-table decode → sandbox capture — honest failures, never raw dump.
- Compile: patched luac (keeps debug info → readable round-trip) → `_std_to_bgmi(lua_bgmi.std_to_bgmi)`
  → register-cap check (255) via lua_engine proto walk.

---

## 2. Feature → Reality (verified)

| README/INSTRUCTIONS claim | Status | Where |
|---|---|---|
| Install: one-line curl\|bash | ✅ verified (isolated HOME install exit 0) | install.sh |
| Runs as `ikram` after install | ✅ (bashrc function, self-repair + pyc magic check + auto python upgrade) | install.sh |
| DROP/pak|lua|inject → RESULT/extracted\|injected\|lua\|CostomPak\|Repacked\|processed | ✅ folder set created by installer + overlay | install.sh, ikram_patch.py:26 |
| PAK: Unpack | ✅ Tencent + UE4 (+OBB), per-file/all | pak.pyc, ikram_patch._unpack_one |
| PAK: Inject file | ✅ with type auto-detect (lua/uasset/asset), single+multi, saved-key reuse | pak.pyc, ikram_patch.pak_inject |
| PAK: Repack | ✅ Tencent; UE4 standard; ⚠ v10+ UE4 = extract-only ("v10+ repack abhi supported nahi") | pak.pyc PakWriter, ue4.pyc |
| PAK: Costom | ✅ implemented ONLY in V111 overlay (ikram_patch.py) — compiled ikram.pyc menu is V110 3-option; overlay patches `[4] Costom Pak` | ikram_patch.py:1060 |
| LUA: Compile (+PROTECT) | ✅ luac_patched + lua_protect.pyc; BGMI output; register-cap warn; strip flag kept-name round-trip | mega_lua.compile_bgmi |
| LUA: Decompile → *GAME.lua | ✅ full cascade; encrypted files handled honestly (no garbage-as-success) | mega_lua.decompile_bgmi |
| Auto-update every start | ✅ check_updates_auto in core + update.pyc (GitHub releases/latest → IkramTool.zip) | ikram.pyc, update.pyc |
| Self-repair | ✅ launcher downloads IkramTool.zip + repairst when ikram_patch.py missing | install.sh:620 |
| Key system | ✅ version-tied (key.pyc reads VERSION + ikram_key.json key_hash); FREETOOL boot-verified | key.pyc, ikram_key.json |
| Encrypted pak → AES prompt | ✅ ue4.pyc + engines._resolve_ue4_key + saved keys | engines.py:296 |
| pip libs "rich, pycryptodome, zstandard..." | ✅ (install also adds gmalg; README's "..." covers it) | install.sh:489 |

---

## 3. Discrepancies / issues found (fix candidates)

1. **Version stamp drift** — `VERSION`=V111 vs `ikram_key.json` version `"V110"` vs README header `V109`
   vs INSTRUCTIONS header `V110`. Key system is version-tied → MUST decide (Phase 4) whether key binds to
   core version (V110, intentional) or repo VERSION (V111). README/INSTRUCTIONS headers are plainly stale.
2. **README ISSUES § "unluac.jar ko LUA_TOOL folder me rakho"** — no `LUA_TOOL` folder exists in the release;
   unluac.jar is bundled + self-managed in `.engine/`. Readme instruction is obsolete/wrong.
3. **README "2 repacked files — V109 fix"** — implemented in overlay `_purge_legacy_repacked_folders()`,
   but readme frames it as V109-era and doesn't reflect the overlay architecture.
4. **INSTRUCTIONS "COSTOM PAK new in V110"** — the compiled core menu is V110 (3 options); Costom ships as a
   V111 overlay patch. Doc drift vs actual versioning.
5. **UE4 v10+ repack gap** — README sells Repack generically; compiled ue4.pyc states v10+ extract-only.
   Overlay does not override (no repack for v10+). Should be documented or implemented in Phase 3/6.
6. **`lua_simplify` legacy import** — univ.pyc `IMPORT_NAME lua_simplify` guarded + not bundled → dead path,
   always skipped. Harmless; candidate for removal or comment.
7. **Telemetry scope (Phase 4)** — telemetry.pyc posts device name + time to `https://api.telegram.org/bot...`
   on login ("OWNER ONLY" docstring). Verify data shape/min vs privacy expectations.
8. **Hardcoded crypto material (Phase 3/4)** — `pakcrypto.pyc` contains base64 blob `Q0hVTKey$as*1ZFlQCiA`
   (Tencent CHUNK key); overlay `_patch_ue4_default_key()` patches a default UE4 AES key hex. Confirm both
   against game-family defaults; these are active secrets-by-design (public game constants) — audit for
   accidental owner-specific material.
9. **Synthetic `co_filename`** on some code objects (`<i*>`, `<p>`, `<e>`) — cosmetic; noted, not a defect.

---

## 4. Verification evidence (Phase 0+1)

- Isolated install: `HOME=<fake> bash install.sh` → exit 0, "Boot test passed - Key prompt + Main menu OK", V111 box.
- Remote release: `releases/latest/download/IkramTool.zip` → 302 to tag **V111** asset (matches repo).
- pyc integrity: all 16 marshal-decode on Python 3.14.6 (magic `2b0e0d0a`); function count in index.txt per module.
- Installer creates exact RESULT/DROP dir set incl. CostomPak/Repacked/processed.

## 5. Suggested follow-ups (feed next phases)
- Phase 3: verify Tencent pak schema + CHUNK key material against pakcrypto parsing; UE4 key default provenance.
- Phase 4: key_hash == sha256("FREETOOL")? decide V110/V111 key binding; telemetry data audit; hardcoded material review.
- Phase 5/6: ANSI/rich palette audit (ACCENT/BG_DEEP/PALETTE consts), 60-col floor, alignment.
- Phase 7: version stamps sync (V111 everywhere), README/INSTRUCTIONS rewrite for V111 overlay architecture,
  document UE4 v10+ repack limitation, restore lua_simplify doc or remove guard.