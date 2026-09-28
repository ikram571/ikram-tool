# Ikram Tool V120 — Fixes & Audit Notes

Audit scope: the shipped zip (now the source of truth), not the dev tree.
Every item below was reproduced before the fix and re-verified after it.

---

## 1. Compile engine (`mega_lua.py`)

### 1.1 Output was not game-ready
Compile emitted an `IKRM`-wrapped blob that the game VM refuses to load.
The header is now bare BGMI Lua 5.3:

```
1b 4c 75 61 53 19 93 0d 0a 1a 0a
```

Byte 4 is `0x53` (Lua 5.3), bytes 6-12 are `\x19\x93\r\n\x1a\n`.
`luac_patched` and the real game load these directly.

The separate **Protect** menu (`protect_compile.py`, shim at
`lua_bgmi.pyc:protect_compile`) is untouched and still produces `IKRM`
output — that feature is independent and still passes its own round-trip.

### 1.2 Repair pass
`_seal_dead_code` plus a compiler-driven `_repair_from_error()` fixpoint
loop. Repairs applied, in order:

| Repair | Handles |
|---|---|
| missing-label / invalid goto | `no visible label` for a function that is defined and used |
| split `_G` key | `_G.__RAJPUT Session` split across two lines |
| dead statements | code after `return` / `break` in the same block |
| missing terminator | unclosed `if`/`for`/`while`/`function` → append `end` |
| unterminated long string | `[[` / `[=[` with no closing bracket |
| truncated bracket | unclosed `{` / `(` at EOF |
| orphaned branch | `else` / `elseif` with no opening `if` |
| duplicate label | same label twice in one function |
| reserved-word label | `::in::`, `::end::`, … |

The fixpoint loop is what makes multi-error files work: it re-runs the
compiler after each repair, parses the next error, repairs, and repeats
until clean or until the error is one it cannot fix.

### 1.3 Goto safety regression (caught by the safety suite)
An early version rewrote *any* function containing a goto, which silently
destroyed valid forward, backward, nested-block, and cross-function-scope
gotos. The repair is now gated on the compiler actually reporting a goto
error. 30/30 valid snippets are byte-identical after the full chain.

---

## 2. Dead code

`_all_label_names` — never called anywhere, including the compiled
`.pyc` chain. Removed.

Deliberately **kept**: the 22 `proc_*` functions in `assetprocs.py` are
reached through the `PROCESSORS` dispatch table, and `version_tuple` is
referenced by `ikram.pyc` / `update.pyc`. Neither is dead.

No duplicate top-level definitions, no `TODO`/`FIXME`/`XXX`/`HACK`, no
`if False` branches anywhere in the tree.

---

## 3. `update.sh` — wrong path

It looked for the updater at `.engine/update.py`. The tool root *is* the
engine directory now (see §4), so the real file is `update.py` sitting
next to it. It also assumed it was being run from the tool directory.
Both fixed: it now resolves `TOOL_DIR` from `$0` and calls
`$TOOL_DIR/update.py`.

---

## 4. Installed layout — engine flattened, `DROP`/`RESULT` lifted out

Old installs buried everything under a hidden `.engine/` and reached the
user's folders through symlinks:

```sh
ln -sfn "$TARGET/drop"   "$TARGET/.engine/DROP"
ln -sfn "$TARGET/result" "$TARGET/.engine/RESULT"
```

So `paths.py` had to branch on `.engine` and deliberately pick the
**lowercase** `drop`/`result` parent, and the compiled `ikram.pyc` looked
for `DROP` inside its own directory. Two folder spellings for one thing,
and a hidden indirection between the engine and the user's data.

V120 installs the engine **directly** into `~/Ikram_Tool` and keeps the
data folders as plain uppercase siblings:

```text
~/Ikram_Tool/
├── DROP/{pak,lua,inject}/
├── RESULT/{extracted,injected,lua,processed,CostomPak,Repacked}/
├── deps/                 ← LJD decompiler runtime, required
└── <engine files>        ← ikram.pyc, ikram_patch.py, run.sh, ...
```

No `.engine`, no symlinks, no duplicate `DROP`/`RESULT` spelling. The
`else` branch in `paths.py` (repo/dev layout, uppercase) is now the only
path the installed tool takes, so the `.engine` special case is dead code
kept only for the dev tree. `ikram_patch.py` still overrides the compiled
module's `DROP`/`DROP_PAK`/`DROP_LUA`/`DROP_INJ`/`RESULT` globals with
the resolved paths, which is what keeps user data out of the engine dir.

### 4.1 Legacy migration

`install.sh` migrates an existing install in place before the runtime is
replaced: every file under `drop/` and `result/` is moved to `DROP/` and
`RESULT/`, and `.engine/` is retired. Existing target files win over
incoming legacy ones of the same name, and nothing is overwritten or
dropped. Verified 7/7 planted legacy files (including a nested `.luac`
and a `CostomPak/custom.pak`) survive a migration intact.

### 4.2 Three bugs found while testing this

- **`_take_aside` moved the extraction temp dir.** The staging dir
  `.ikram_tmp` is *inside* `$TARGET`, so the transaction swept it into
  `.old_runtime/` and the subsequent `cp` failed with its own source
  gone — every install failed. It is now excluded, as is `.old_runtime`.
- **Boot test hung forever and leaked its temp files.** The tool stops at
  the activation-key prompt and keeps reading stdin, so under `curl |
  bash` / `</dev/null` `boot_test` never returned and the installer had to
  be killed, leaving `.boot_plan.*` and `.boot_drv.*.py` behind. The
  test is now bounded by `timeout 30`.
- **A healthy boot was reported as a failure.** An unactivated tool exits
  at the key gate via `SystemExit`, which `except Exception` cannot
  catch, so it ends non-zero with an *empty* traceback log. The pass
  condition is now "no traceback", not "exit 0"; a real crash still fails
  loudly. The test also exports `PYTHONDONTWRITEBYTECODE=1` so it stops
  writing `__pycache__/` into the install.

---

## 5. `install.sh` — wrapped-zip support

The release zip is `IkramTool.zip` containing a single top-level
`Ikram_Tool/` directory. `install.sh` assumed the payload sat at the zip
root, so it would have installed nothing and bailed with
"ikram.pyc not found in zip — release is broken."

Fixed to accept **both** layouts: if `ikram.pyc` is not at the extracted
root, it descends into the single top-level directory that contains it.
`update.py` already did this (it unwraps before `_clean_replace`), so the
two are consistent, and legacy flat zips (V119 and older) still install.

One gap left in the self-repair path: it re-extracted and checked
`$TMPX/ikram.pyc` without unwrapping, so a wrapped zip could not repair
itself. The same unwrap is applied there.

Verified: a wrapped V120 zip installs to `$HOME/Ikram_Tool/ikram.pyc` with
no nested wrapper, and reports `Version: V120`.

---

## 6. `release.sh` — no longer auto-publishes

It created the GitHub release unconditionally as its last step. It now
**builds only** by default and requires an explicit opt-in:

```bash
bash release.sh V120             # build, upload nothing
bash release.sh V120 --publish   # build, then upload
```

Also stages the payload under `Ikram_Tool/` so the zip has exactly one
root, and drops the QA harness (`v120_safety.py`, `v120_regress.py`,
`option_test.py`) from the shipped payload.

---

## 7. Permissions

`run.sh`, `install.sh`, `update.sh` and `release.sh` shipped mode 644 and
were not executable. All four are 755, and the mode survives the zip
round-trip.

---

## 8. Things checked and left alone (not bugs)

- **`luac_patched` local-variable limit is 1000 per scope.** Stock
  `luac5.3` allows 200; the patched compiler allows 1000. A file with
  more than 1000 locals in a *single* scope cannot compile. This limit
  is compiled into the bundled binary — raising it means rebuilding the
  Lua VM, which is out of scope. Sources with >1000 locals in one scope
  are refused with a clear error instead of crashing. Real game scripts
  and all 6 corpus `.pak` files are far below this.
- **The activation key prompt is a feature.** `ikram_key.json` ships only
  a `key_hash`, never the key, so interactive branches past the gate
  cannot be driven in an automated run. Every subsystem behind the gate
  was tested directly at the layer the UI calls.
- **`telemetry.pyc` contains Telegram bot credentials and ships in the
  package.** Anyone who downloads the release gets them. It is only used
  to message the owner. Recommend regenerating the token and moving the
  bot behind a small server-side proxy before the release goes wide, or
  stripping `telemetry.pyc` from the payload. Flagged, not changed —
  removing it would change tool behaviour.

---

## 9. Not bugs (environmental)

`Error processing line 1 of .../zz-bekit-argon2.pth: ModuleNotFoundError:
No module named 'bekit_argon2_shim'` is printed by the *system* Python at
startup. It comes from a file in the Termux `site-packages`, not from
this tool — nothing in the tree references Bekit or Argon2. It appears in
every local Python invocation and has no effect on the tool.
