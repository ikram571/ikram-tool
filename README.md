# IkramTool
![Version](https://img.shields.io/badge/version-v115-blue)
![Platform](https://img.shields.io/badge/platform-Termux-green)
![Status](https://img.shields.io/badge/status-stable-success)

**PAK / LUA Modding Tool** — built for Termux (PUBG / BGMI)

Unpack, inject, repack, costom-pak files · Compile/decompile lua.
**V115 — IKRM-Protected Compile:** every Lua compile now ships encrypted +
inflation-armored (2–4 MB dead-proto payload, per-file HKDF-SHA256 rotating
key, `IKRM` wrapper) so decompilers are rejected at byte 0; Decompile and the
internal pipeline auto-decrypt IKRM files so round-trips keep working.
**V114 — VIP Rebuild:** 11 colour themes, boxed menus + live progress,
fixed DROP/RESULT folder system, and the original compiled pak/lua
engines kept intact (delegated 1:1, verified byte-exact).

---

## INSTALL (Termux)

Paste this one command into Termux (new terminal / fresh Termux):

```
curl -fL https://cdn.jsdelivr.net/gh/ikram571/ikram-tool@main/install.sh | bash
```

This installs: python, git, curl, unzip, openjdk-17, lua53,
all pip libraries (rich, pycryptodome, zstandard...), the tool files, and
the `ikram` command — everything automatically, just once.

Or download `install.sh` and run:
```
bash install.sh
```

After install, **open a new terminal** and type:
```
ikram
```

> The install pipeline is non-blocking: `curl | bash` never waits for Enter
> during install, every package installs separately with 3 retries, and a
> progress % is shown.

---

## HOW TO USE

Put files into the tool's **DROP** folder, then choose an option. No typing
needed — just pick a number from the list.

| Folder | What to put in it |
|--------|-------------------|
| `DROP/pak` | pak files (unpack / inject / repack) |
| `DROP/lua` | lua / luac files (compile / decompile) |
| `DROP/inject` | any file you want to inject or pack |

The result of every job lands in the **RESULT** folder:

| Folder | What you get |
|--------|--------------|
| `RESULT/extracted/<name>/` | Files after unpack — edit them here (raw tree stays clean; unpacked copies go to sidecar) |
| `RESULT/processed/<name>/` | Unpack sidecar files (game-processable lua/asset copies) |
| `RESULT/injected/<name>.pak` | The pak after inject |
| `RESULT/Repacked/<name>.pak` | The new pak from repack (the original DROP pak is never changed) |
| `RESULT/CostomPak/<name>.pak` | Costom Pak (fresh pak skeleton) |
| `RESULT/lua/` | compiled `.luac`, decompiled `.lua` / `.FAILED.txt` |

> Folder names are **case-sensitive** (Android FS): always write lowercase
> `DROP/pak`, `DROP/lua`, `DROP/inject`.

### PAK TOOL (4 operations + clear)
- **1 Unpack** — open the pak, take all files out to `RESULT/extracted/<name>/`
- **2 Inject** — put `DROP/inject/` files into a pak (auto put /
  one-by-one mode) → `RESULT/injected/<name>.pak`
- **3 Repack** — edit the extracted files, then build a new pak →
  `RESULT/Repacked/<name>.pak`
- **4 Costom Pak** — build a new pak from the extracted tree →
  `RESULT/CostomPak/<name>.pak`
- `C` / `R` — clear `DROP/pak` or `RESULT`

### LUA TOOL (2 operations + intelligence engine)
- **1 Compile** — turn source `.lua` into protected game bytecode →
  `RESULT/lua/`
- **2 Decompile** — turn game bytecode back into readable source. On
  success → `<name>_decompiled.lua` + quality score. If encrypted /
  unreadable → `<name>_FAILED.txt` with the reason.

### THEMES
11 themes — Original Color (default), Neon Pink, Cyber Blue, Blood Red, Matrix
Green, Gold VIP, Purple Reign, Ice White, Sunset Orange, Ocean Teal, Lava.
The theme is saved and remembered on the next launch.

---

## KEY

You need a key to unlock the tool: **FREETOOL** (same for every version,
free). When the key is valid you get "Tool unlocked!".

---

## UPDATE

At every start the tool **automatically checks for a new version** — if
one exists it downloads and installs itself. Nothing to do.

---

## ISSUES

- **Got a Decompile FAILED.txt?** — The file is properly encrypted or the
  owner locked it. The tool tries every decompiler and reports honestly.
- **It asks for an AES key?** — It's an encrypted pak; it needs the AES key.
- **unluac.jar missing?** — It's bundled (unluac_rs + unluac.jar + ljd.zip
  included). If decompile struggles, `lua_patched`/`unluac_rs` are in the
  same folder.
- **Permission problem?** — Give Termux storage access: `termux-setup-storage`
- **Python outdated?** — the launcher itself runs `pkg upgrade -y python` and repairs itself.