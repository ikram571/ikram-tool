# V123 — Custom PAK, the update chain, and user-data loss: audit and delivery report

Repo: `ikram571/ikram-tool` · branch `main` · base commit `b116e49` (V122)
Target: **V123** · asset `IkramTool.zip` · 95 entries · 6,320,556 bytes
Commit: `3897531` — "V123 — Custom PAK shipped 0-byte files, and the update check never ran again"
Status: committed, pushed, published. `releases/latest` → **V123**. Verified against the live asset.

```
sha256(IkramTool.zip) = 3fec7ff61416cf1218d1c811f7d9c88e5316473da6d6884be960d7325c29c924
```

---

## Change table

| File | ± | What changed |
|---|---|---|
| `engines.py` | +328 | Full-content Custom PAK build: real inventory, per-path sizes, output readback verification, partial-output cleanup, unencrypted-PAK key resolution |
| `menus.py` | +222 −126 | Numbered source-PAK and path selection, input validation, output naming, confirmation, progress |
| `vip_ui.py` | +105 | `_update_gate()` restored before the key screen; re-exec into a new release |
| `update.py` | +21 | `_is_protected()` case-insensitive matching for `DROP`/`RESULT` |
| `ikram_patch.py` | +43 | Baki ENTER branch delegates to the same full-content builder |
| `tests/test_update_gate.py` | +267 | New: 65 assertions on gate order, re-exec, offline, version compare, data survival |
| `tests/test_costom_pak.py` | +133 − | Rewritten: 25 assertions on selection, bytes, naming, verification, cleanup |
| `tests/flow_test.py` | +28 | Updated for the new prompts |
| `VERSION`, `ikram_key.json` | ±1 | Version stamp → V123; **key hash unchanged** |

10 files, **+1067 −210**. Only the 7 non-test files ship in the asset.

---

## Phase 1 — Custom PAK wrote 0-byte files

**The defect.** `menus.pak_custom()` sent both the ENTER branch and the numbered
pick through `engines.costom_pak(..., copy=False)`, and that path builds
`{internal_path: b""}`. The resulting pak had correct names and a correct
directory structure but **every body was empty**, so the game could not read it.
Only the "type a path by hand" branch ever copied real bytes. The menu text
promised a subset repack; the code produced a name-only index.

Two more faults shipped in the same function: it silently picked whichever pak
sorted first rather than asking, and it named the output
`costom_<timestamp>.pak` instead of after the source pak.

**The fix** (`engines.py`, `menus.py:191`):

| Line | Function | Role |
|---|---|---|
| `engines.py:547` | `list_pak_paths` | every internal path of the source, ordered |
| `engines.py:679` | `custom_session_dir` | one temp dir per build, in the tool's own temp root |
| `engines.py:691` | `cleanup_custom_session` | removes it, called from `finally` |
| `engines.py:699` | `custom_pak_inventory` | extracts once, returns `(path, real_decompressed_size)` per entry |
| `engines.py:773` | `_verify_custom_pak` | reads the finished pak back, re-resolves each path, compares size |
| `engines.py:828` | `build_custom_pak` | full content, not stubs |

Flow at `menus.py:191`: list every pak in `DROP/pak` with a number, `0` cancels,
EOF on an empty list returns rather than raising; list internal paths with
their real sizes; `ENTER` selects all, a number selects exactly that path, and a
typed string resolves as exact path → basename → folder prefix, with an
unmatched entry re-prompting instead of crashing. The output name defaults to
the source pak's stem, with a numeric suffix when that name is taken.

**Success is now proven, not assumed.** `build_custom_pak` calls
`_verify_custom_pak` after writing. Every selected path must be present in the
finished pak, non-empty, and equal to the source decompressed size. A failed
build deletes its own partial output, because the error box at `menus.py:293`
claims nothing was written — that claim is now true.

`engines.py:266 _key_candidates` / `engines.py:302 _resolve_ue4_key` were
corrected so a genuinely **unencrypted** PAK is accepted instead of being forced
through a default key that fails to decrypt it.

## Phase 2 — The update chain was severed, not broken

`ikram.pyc`'s `main()` has always done `check_updates_auto` → `os.execv` →
`key_lock`. Nothing called `main()` any more. `ikram_patch.py` drives
`vip_ui.Vip.run()`, and `run()` went straight from `ensure_dirs()` to the key
screen. An old install therefore **never checked for updates again** while the
key prompt opened exactly as it always had — the most plausible-looking possible
explanation for "the tool never updates."

Restored at `vip_ui.py:575`, ordered ahead of the key screen at
`vip_ui.py:692` → `:694`:

```
Vip.run()  ->  _update_gate()  ->  _key_gate()  ->  menus
```

`_update_gate` keeps the core's own rules: 5-second network bound, integer
version compare, install-then-`os.execv` only when `update.do_install()`
(`vip_ui.py:624`) reports a real complete install, and silent pass-through when
the release is same, older, absent, or unreachable. A failed or offline check
never blocks the key screen.

`update.version_tuple` parses numerically and returns `[0]` for unparseable
input — an intentionally conservative "treat as older" so a corrupted `VERSION`
still permits an update.

## Phase 3 — Updates deleted user data

**The defect.** `update.PROTECTED` (`update.py:159`) listed only uppercase
`DROP` and `RESULT`. On a pre-`.engine` install, `TOOL_DIR` **is** the tool
root, and the current installer creates lowercase `drop/` and `result/`. The
transaction in `_clean_replace` therefore moved those real user directories
into the backup — where they were then deleted with it. `ensure_dirs()` quietly
made empty replacements on the next launch, so the loss looked like a reset
rather than a delete.

Fixed by `_is_protected()` (`update.py:171`, used at `:291` and `:297`), which
compares case-insensitively. The reasoning is recorded at `update.py:154` so it
is not reverted as an "unnecessary" abstraction.

**This one was reproduced for real, not reasoned about.** A sandbox was
installed from the actual V122 release asset with lowercase `drop/pak/user.pak`
and `result/mine.lua`, then updated by **V122's own** updater:

```
VERSION now : V123
drop/pak/user.pak   -> *** DELETED ***
result/mine.lua     -> *** DELETED ***
stale_from_v118.py  -> removed (good)
```

That is the old bug, live, and it is why the case-insensitive fix is not
cosmetic. The same scenario then ran through **V123's** `update.do_install()`
— real download, real `_safe_extract`, real `_clean_replace`, real version
stamp, real `_fix_env()`, with the genuine V123 asset served over `file://`:

```
VERSION now              : V123
key version now          : V123
drop/pak/user.pak        : MY PRECIOUS PAK
drop/pak/second.pak      : ANOTHER ONE
result/mine.lua          : -- my decompiled output
result/CostomPak/built   : BUILT OUTPUT
stale V118 file          : removed (good)
backup/staging residue   : none
```

All user data survived, the stale pre-V118 file was correctly removed, and no
`.old_*` / `.new_*` residue was left behind. `_clean_replace` is the only code
that moves the old tree, so this is the whole deletion surface.

## Phase 4 — The Baki path had the same bug

`ikram_patch._make_costom_pak()` fed its ENTER branch into
`_inject_skeleton`, which writes empty bodies — the identical defect, on the
secondary menu. `_build_full_content_custom()` at `ikram_patch.py:931` now
delegates to the same `engines.build_custom_pak` the VIP menu uses
(call sites `ikram_patch.py:981`, `:1007`), so both entry points emit the same
bytes and clean up their session in a `finally`.

## Phase 5 — Tests

| Suite | Result |
|---|---|
| `tests/test_costom_pak.py` | 25 passed, 0 failed |
| `tests/test_update_gate.py` | 65 passed, 0 failed |
| `tests/test_updater_safety.py` | 60 passed, 0 failed |
| `tests/test_menu_e2e.py` | 60 passed, 0 failed |
| `tests/test_decompile_safety.py` | 40 passed, 0 failed |
| `tests/flow_test.py` | ALL FLOW TESTS GREEN |
| `tests/test_release_e2e.py` | ALL 13 RELEASE GATES GREEN |
| Full suite (13 suites) | all passed |

`test_updater_safety` drives a real `do_install()` against a real payload over
`file://` — download, extract, transaction, stamp, restore — and asserts the
user files come out the far side. `test_update_gate` asserts the order
(update before key), same/older/no-release/offline pass-through, numeric
comparison, and case-insensitive survival.

**One flake, reported rather than hidden.** An early `test_decompile_safety` run
printed 39/1. Four consecutive reruns and the final full-suite run were 40/0 and
the failing identity was never captured. I could not reproduce it, so it is
recorded as an unresolved non-reproducible failure, not as a pass.

Static checks: Python AST parse on every changed module, `bash -n` on
`run.sh` / `install.sh` / `update.sh` / `release.sh`, and `git diff --check`.

## Phase 6 — Packaging and publication

- Version stamped to V123 in `VERSION` and `ikram_key.json`; **`key_hash`
  unchanged**, so no re-key and no key screen change.
- Asset: 95 entries, 6,320,556 bytes, identical file set to V122.
- Contents inspected: no `tests/`, no `DROP/`, no `RESULT/`, no `.pak`, no logs,
  no caches. The only zero-byte entry is
  `deps/ljd/ljd/rawdump/opcode/__init__.py`, an unchanged legitimate Python
  package marker. The `.pyc` files are the tool's own compiled core and ship
  intentionally.
- Only 7 files differ from V122 — the 3 test files stay in the repo, not the zip.
- `releases/latest` resolves to
  `https://github.com/ikram571/ikram-tool/releases/tag/V123`.
- The downloaded live asset was re-hashed and re-listed; it matches the staged
  build and contains `_update_gate` and `_is_protected`.
- `DROP/pak` and `RESULT/CostomPak` are empty and gitignored; worktree is clean
  at `3897531`.

## Phase 7 — What is still open

1. **V122 users cannot auto-update to V123.** The gate is the thing being
   restored, and V122's installed code does not have it — its `vip_ui.py` has no
   `_update_gate` and its `run()` goes straight to `_key_gate`, and the
   persistent `$PREFIX/bin/ikram` only self-repairs a missing patch file. One
   manual `bash update.sh` is required, and that run is performed by **V122's
   exact-case updater**, which is the code demonstrated above to delete
   lowercase `drop/` and `result/` on a flat install. This is a bootstrap limit
   of the fix, not a defect in it: nothing shipped after V123 can lose data.
   **V122 users on the flat layout should back up `drop/` and `result/` before
   their first V123 update.** Data dirs outside `TOOL_DIR` (the `.engine`
   layout) were never at risk.
2. **No Tencent PAK fixture.** The Tencent writer mirrors the proven PakWriter
   layout and the readback verification covers it, but no real Tencent pak was
   available to produce a game-loadable subset.
3. **No AES-encrypted fixture.** Bundled `repak 0.2.3 pack` exposes no
   encryption option, so an encrypted-input fixture could not be built. The
   unencrypted path is covered.
4. **No dedicated Baki regression.** The Baki change is structurally identical
   to the tested VIP path and both call sites were inspected, but it has no
   permanent test of its own.
5. The `test_decompile_safety` 39/1 flake in Phase 5 remains unreproduced.
