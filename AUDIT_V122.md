# V122 — Phase 0–10 audit, fix and delivery report

Repo: `ikram571/ikram-tool` · branch `main` · base commit `608751e` (V121)
Target: **V122** · asset `IkramTool.zip` · 85 files · 6.1 MB
Status: fixes complete, all suites green, archive built and inspected.
**Not committed, not pushed, not published.** Awaiting release confirmation.

---

## Phase 0 — Baseline and ground truth

Established before touching anything:

| Fact | Value |
|---|---|
| Requested repo | `github.com/opencode/Ikram_Tool` → **404, does not exist** |
| Actual repo | `github.com/ikram571/ikram-tool` |
| Base commit | `608751e` — "V121" |
| Published `latest` | **V119** (V120 and V121 were committed but never published) |
| Installed locally | `~/Ikram_Tool/.engine/VERSION` = V119 |
| Update URL | `releases/latest/download/IkramTool.zip` |
| Layout under test | `~/Ikram_Tool/.engine/` + sibling `drop/`, `result/`, symlinks `DROP`/`RESULT` |

The published release being two versions behind the source is a release-hygiene
fact, not a code defect: `release.sh` pushes and publishes in one step, so any
release cut where the push succeeded and `gh release create` did not leaves the
source ahead of `latest`. The updater has therefore been offering nothing to
V119 users. V122 fixes the ordering risk (see Phase 7).

## Phase 1 — The beacon

`ikram_patch._notify_tg()` loaded `telemetry.pyc` straight off disk and posted
the machine, the file list and the failure text to a Telegram chat. That file is
deleted; the replacement is `telemetry.py`, a local-only append-only action log.

- No `socket`/`urllib`/`requests` import anywhere in the shipped code
  (asserted per module — `update.py` is the single permitted exception, it is
  the updater).
- Loading by path also *bypassed* `sys.modules`, so the pin installed in
  `ikram_patch` never applied to it. The local module is now imported normally.
- `telemetry.py:32` `MAX_BYTES`, `telemetry.py:89` `_rotate()`: the log keeps
  its last 500 rows once it passes 1 MB. One write per action, one bracketed row
  per line, fields truncated and newline-stripped so no field can forge a row.
- Every menu action is recorded: `vip_ui.py:632` `Vip.logged()` and
  `vip_ui.py:637` `Vip.act()` wrap the PAK/LUA dispatch and the theme setter,
  and the PAK file level adds `pak.unpack` / `pak.repack` with engine, count and
  output size.
- Logging never raises. A read-only or missing log directory is a no-op.

## Phase 2 — The key screen

The compiled core's key screen had no attempt counter and no end-of-input check:
a wrong key spun forever, and a closed stdin hung on the prompt with nothing on
screen. `vip_ui.py:180` `_KeyScreen` supplies both from outside, without
redrawing a line of the screen itself.

- Exactly 3 attempts, then `✘ Too many attempts. Exiting.` A 4th prompt is never
  drawn. The cap is raised as `SystemExit` — a `BaseException` — so the
  compiled `except Exception` around the prompt cannot swallow it.
- EOF / closed stdin exits instead of hanging, on the first prompt and mid-prompt.
- `exit`, `quit`, `q` (any case, padded) stay graceful and are not counted as
  strikes.
- `builtins.input` and the core's console are restored on every path, including
  the error path.
- `vip_ui.py:164` `_fix_bottom_corner`: the compiled bottom border closes with
  `╮` where `╯` belongs. Only a line opening with `╰` is touched.
- `vip_ui.py:201` `_fit_row`: the core pads the key row by `len()` arithmetic
  that does not know the key glyph is two columns wide, so the row overshot the
  right border and wrapped. The fill is now *solved* for, and `vip_ui.py:150`
  `_width()` charges east-asian-width and combining glyphs correctly. Every row
  on the key screen is exactly as wide as the border it sits between.
- Known limit, unchanged: a key longer than the 26 free columns of the key box
  still uses the compiled core's full echo and can wrap. Making that fit would
  mean redrawing the screen, which is out of scope here.

## Phase 3 — Repack counts

`engines.repack_folder()` reported the number of *staged* edits, not the number
of entries in the pak it actually wrote. A repack that silently dropped entries
still said "N files repacked".

- `engines.py:393` `_count_packed()` reads the written archive and counts real
  entries; `engines.py:415` `_packed_count()` prefers that and falls back to the
  staged count only when the archive cannot be read back.
- All three write paths (unpack / repack / costom) report from the written pak.

## Phase 4 — Updater, env repair, launchers

- `update.py:29` `VERSION_CHECK_TIMEOUT = 5` (was 30). A launch no longer sits
  silent for half a minute. The release download keeps `timeout=120` — that one
  legitimately transfers megabytes.
- `update.py:415` `_fix_env()` is synchronous and announces each step
  (`ENV_REPAIR: …`). It was a daemon thread, so a slow `pkg install` produced a
  frozen screen with no output and the main flow racing the install. Blocking is
  the honest behaviour: a ten-minute wait that prints progress reads as
  progress; a thread that prints nothing reads as a hang.
- Launchers derive `TOOL_DIR` from their own location. `install.sh` generated
  shell through a quoted heredoc and substituted `@@ENG@@` / `@@ROOT@`
  afterwards — `.format()` on shell full of braces raised, the write was
  swallowed, and the user got no launcher and no error message.
- `.bashrc` is created when missing, and the block is idempotent: a second run
  leaves the file byte-identical.

## Phase 5 — Themes

The menu digits were the one hardcoded colour left in the renderer, so every one
of the 267 themes showed the same six numbers.

- `box_engine.py:26` `vip_num_cycle(pal, theme_name)` maps the six slots through
  the active theme's palette; `box_engine.py:23` `_DEFAULT_NUM_CYCLE` pins the
  default so the original look cannot drift.
- **Original Color is byte-identical**: `0→183, 1→45, 2→51, 3→39, 4→118, 5→119`.
- All 267 themes render; every theme yields all six digits.

## Phase 6 — Tests that could not fail

Three suites were incapable of detecting the defects they claimed to cover.

- `tests/test_costom_pak.py` hardcoded a home path and died on
  `ModuleNotFoundError` anywhere but the authoring machine. Now repo-relative.
- `tests/test_corpus.py` required a licensed Lua corpus that is not in the repo.
  Now honours `IKRAM_TEST_CORPUS` and otherwise falls back to a self-contained
  synthetic set, so a fresh clone actually runs. Real-game fidelity is still
  only as good as the corpus you point it at — that is stated, not hidden.
- `tests/test_engine.py` and `tests/flow_test.py` and `tests/live_drive.py` all
  pointed at one absolute fixture path. Discovery is now env-overridable
  (`IKRAM_TEST_FIXTURES`) with repo-relative fallbacks, and an absent fixture is
  reported as an explicit **skip** rather than a silent pass.
- `test_engine.py` D5 is split: **D5a** is the tencent round trip, which needs a
  real tencent archive (the writer bootstraps only from a reader, so it cannot
  be synthesised) and is skipped honestly when absent; **D5b** is a UE4
  pack → extract → repack → re-extract round trip built with the bundled
  `repak`, which now runs on every machine.

## Phase 7 — Packaging

- `release.sh --build-only` builds and proves the archive without pushing or
  publishing, so the ZIP can be inspected before anything irreversible happens.
- The archive is now *content-verified*, not just `unzip -t`'d: the build refuses
  to finish if the zip carries `analysis/`, `tests/`, `__pycache__/`, `.git/`,
  `telemetry.log`, `telemetry.pyc`, `*.zip`, `*.bak_*`, `README.md` or
  `release.sh`. A corrupt-looking release is a build failure, not a warning.
- **Fixed during this pass:** `telemetry.log` (the maintainer's own action log,
  including their file paths) was being copied into every download; `release.sh`
  itself shipped to users; and `ljd.zip` — an 812 KB unrelated archive — was
  committed in the repo root and was being packaged. `ljd.zip` is now untracked
  (the file is untouched on disk) and `*.zip` is ignored.
- `release.sh` writes `VERSION` from `$1`. Adding `--build-only` to the
  `${1:?...}` usage message put a `]` and a `}` into the value, because Bash ends
  a parameter expansion at the first `}`, and the archive was stamped
  `V122 [--build-only]}`. Fixed, and the stamp is now asserted in the gates.

## Phase 8 — Release gates

`tests/test_release_e2e.py` — 13 scenarios, **137 assertions, 0 failures**. Every
menu journey runs in a fresh process, the way a user launches the tool; a hang
is a failed gate rather than a stuck run.

| # | Gate | What it proves |
|---|---|---|
| E01 | install | Builds the real zip, installs it **offline** via `install.sh`'s own `TOOL_URL` override into a `$HOME` containing a space; layout, symlinks, `VERSION`, launcher validity, archive contents |
| E02 | launch | Banner, folder status, clean exit; `ikram_key.json` agrees with `VERSION`; activation hash intact |
| E03 | key strikes | 3 and only 3 attempts, 4th never asked, quit is not a strike, good key gets in, globals restored |
| E04 | EOF | Closed stdin and mid-prompt stdin death both exit, restore globals, never hang |
| E05 | version check | 5 s timeout; an unreachable API returns `None` in 0.0 s, not an exception; asset name unchanged |
| E06 | env repair | Announces itself, creates `.bashrc`, second run byte-identical, no daemon thread |
| E07 | telemetry | One bracketed row per action, rotation bounded, newline injection cannot forge a row, overlong fields truncated, unwritable log never raises, version read from the shipped `VERSION` |
| E08 | pak round trip | build → unpack → edit → repack → re-read: the edit survives, untouched files are byte-identical, counts come from the written pak |
| E09 | costom pak | Declares every name with zero-byte bodies; one folder declares only that name; a typed path copies the real bytes |
| E10 | inject | Injected file reads back byte-exact, original entries still readable |
| E11 | lua | python → pyc → python round trip through the menus |
| E12 | themes | Default cycle byte-identical, another theme uses its own palette, all 267 render |
| E13 | hygiene | No beacon, no network outside the updater, every `urlopen` bounded, no absolute home path, runtime artefacts untracked, the real archive rebuilt and inspected: no dotfiles, no docs, no caches, no logs, compiled chain and native decompilers all present |

Plus `tests/test_fixes_regression.py` (35 tests) and `tests/test_key_screen.py`
(17 tests), each pinning one audit defect so it cannot come back.

## Phase 9 — Verification

| Suite | Result |
|---|---|
| `flow_test.py` | ALL FLOW TESTS GREEN |
| `test_layers.py` | green |
| `test_themes.py` | 267 themes green |
| `test_engine.py` | ALL ENGINE TESTS GREEN (1 honest skip: D5a, no tencent fixture) |
| `test_menu_e2e.py` | green |
| `test_updater_safety.py` | green |
| `test_decompile_safety.py` | green |
| `test_key_screen.py` | 17/17 |
| `test_costom_pak.py` | 20/20 |
| `test_corpus.py` | 7/7 synthetic |
| `test_fixes_regression.py` | 35/35 |
| `test_release_e2e.py` | 13 gates, 136 assertions, 0 failed |

Static gates: `git diff --check` clean · 36 Python files parse · `install.sh`,
`run.sh`, `release.sh` pass `bash -n` · no added line carries trailing
whitespace.

Archive: `IkramTool.zip`, 85 files, 6.1 MB, `unzip -t` clean, contents proven
against the junk list above, and then diffed file-by-file against the repo: every
exclusion is a doc, a cache, a build product or the publish script, and nothing
extra is present.

## Phase 10 — What ships, and what is still open

Shipping: the local-only logger, the key-screen rules, honest repack counts, the
5 s version check and blocking env repair, path-derived launchers, theme-aware
menu numbers, the repaired test suites, the 13 release gates, and a packaging
step that refuses to ship the maintainer's own artefacts.

Open, deliberately:

- **V120 and V121 were never published.** `latest` is V119. Publishing V122 as
  the next tag leaves the changelog honest and gives the updater something to
  offer again; it does not retro-publish V120/V121.
- The real Lua corpus and real tencent PAK fixtures are licensed game data and
  are not in the repo. D5a and real-game Lua fidelity are skipped on a fresh
  clone, visibly, not silently.
- An overlong key still wraps the key box (Phase 2).

Confirmation needed before: commit, tag, push, `gh release create`.
