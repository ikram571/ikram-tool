# IkramTool
![Version](https://img.shields.io/badge/version-v112-blue)
![Platform](https://img.shields.io/badge/platform-Termux-green)
![Status](https://img.shields.io/badge/status-stable-success)

**PAK / LUA Modding Tool** — Termux ke liye (PUBG / BGMI)

Unpack, inject, repack, costom-pak files · Compile/decompile lua.
**V112 — VIP Rebuild:** 10 colour themes, boxed menus + live progress,
fixed DROP/RESULT folder system, and the original compiled pak/lua
engines kept intact (delegated 1:1, verified byte-exact).

---

## INSTALL (Termux)

Sirf ye ek command Termux me paste karo (naya terminal / fresh Termux):

```
curl -fL https://cdn.jsdelivr.net/gh/ikram571/ikram-tool@main/install.sh | bash
```

Ye command install karta hai: python, git, curl, unzip, openjdk-17, lua53,
sab pip libraries (rich, pycryptodome, zstandard...), tool files, aur `ikram`
command — sab khud, sirf ek baar.

Ya phir `install.sh` file download karo aur:
```
bash install.sh
```

Install hone ke baad **naya terminal kholo** aur likho:
```
ikram
```

> Install pipeline non-blocking (only piped runner) hai: `curl | bash` ke
> dauraan Enter nahi poochta, har package alag + retry 3x, progress % ke saath.

---

## USE KAISE KARNA HAI

Tool ke **DROP** folder me files daalo, phir option choose karo. Kuch type
karna nahi — sirf list me se number chuno.

| Folder | Kya daalo |
|--------|-----------|
| `DROP/pak` | pak files (unpack / inject / repack) |
| `DROP/lua` | lua / luac files (compile / decompile) |
| `DROP/inject` | koi bhi file jo inject ya pack me daalni hai |

Result har kaam ke baad **RESULT** folder me milta hai:

| Folder | Kya milta hai |
|--------|---------------|
| `RESULT/extracted/<name>/` | Unpack hone ke baad ki files — edit yahin karo (raw tree clean rehti hai; unpacked copies sidecar me) |
| `RESULT/processed/<name>/` | Unpack ke sidecar files (game-processable lua/asset copies) |
| `RESULT/injected/<name>.pak` | Inject hone ke baad ka pak |
| `RESULT/Repacked/<name>.pak` | Repack ka naya pak (original DROP pak kabhi nahi badalta) |
| `RESULT/CostomPak/<name>.pak` | Costom Pak (fresh pak skeleton) |
| `RESULT/lua/` | compile ke `.luac`, decompile ke `.lua` / `.FAILED.txt` |

> Folder names **case-sensitive** hain (Android FS): lowercase `DROP/pak`,
> `DROP/lua`, `DROP/inject` hi likho.

### PAK TOOL (4 operations + clear)
- **1 Unpack** — pak kholo, saari files `RESULT/extracted/<name>/` me nikal lo
- **2 Inject** — `DROP/inject/` ki files ek pak ke andar daalo (auto put /
  one-by-one mode) → `RESULT/injected/<name>.pak`
- **3 Repack** — extracted files edit karke naya pak banao →
  `RESULT/Repacked/<name>.pak`
- **4 Costom Pak** — extracted tree se ek naya pak banao →
  `RESULT/CostomPak/<name>.pak`
- `C` / `R` — `DROP/pak` ya `RESULT` clear karo

### LUA TOOL (2 operations + intelligence engine)
- **1 Compile** — source `.lua` ko protected game bytecode banao →
  `RESULT/lua/`
- **2 Decompile** — game bytecode ko readable source banao. Success →
  `<name>_decompiled.lua` + quality score. Encrypted/unreadable →
  `<name>_FAILED.txt` me reason likha milta hai.

### THEMES (3)
10 themes — Rainbow (har character colored), Cyber Blue, Blood Red, Matrix
Green, Gold VIP, Purple Reign, Ice White, Sunset Orange, Ocean Teal, Lava.
Theme save hota hai aur next launch pe yaad bhi rehta hai.

---

## KEY

Tool unlock karne ke liye key chahiye: **FREETOOL** (same har version,
free). Key valid ho to "Tool unlocked!" milta hai.

---

## UPDATE

Tool har baar start hote hi **naya version automatically check** karta hai —
naya ho to khud download+install ho jata hai. Kuch nahi karna.

---

## ISSUES

- **Decompile FAILED.txt mila?** — File properly encrypted hai ya owner ne
  lock kiya hai. Tool har decompiler try karke honest report deta hai.
- **AES key puchta hai?** — Encrypted pak hai, AES key chahiye.
- **unluac.jar nahi?** — bundled hai (unluac_rs + unluac.jar + ljd.zip tool
  ke saath). Decompile me dikkat aaye to `lua_patched`/`unluac_rs` ek hi
  folder me hain.
- **Permission problem?** — Termux ko storage access do: `termux-setup-storage`
- **Python purana?** — launcher khud `pkg upgrade -y python` karke repack kar leta hai.