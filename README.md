# IKRAM TOOL
**PAK / OBB / LUA Modding Tool** — Termux ke liye (PUBG / BGMI)

Unpack, inject, repack pak files · Compile/decompile lua · Unpack/repack obb.

---

## INSTALL (Termux)

Sirf ye ek command Termux me paste karo:

```
curl -sL -o install.sh https://raw.githubusercontent.com/ikram571/ikram-tool/main/install.sh && bash install.sh
```

Ya phir `install.sh` file download karo aur:
```
bash install.sh
```

Install hone ke baad **naya terminal kholo** aur likho:
```
ikram
```

---

## USE KAISE KARNA HAI

Tool ke `DROP` folder me files daalo, phir option choose karo.

| Folder | Kya daalo |
|--------|-----------|
| `DROP/pak` | pak files (unpack / inject ke liye) |
| `DROP/lua` | lua / luac files |
| `DROP/obb` | obb files |
| `DROP/inject` | koi bhi file jo inject karni hai |

Result har kaam ke baad `RESULT` folder me milta hai.

### PAK TOOL
- **Unpack PAK** — pak kholo, saari files folder me nikal lo
- **Inject Lua** — pak ke andar folder choose karo, lua wahan daalo
- **Inject File** — koi bhi file (uasset/png/json) pak ke andar daalo
- **Repack PAK** — edit ki files se naya pak banao

### LUA TOOL
- **Compile Lua** — source .lua ko bytecode .luac banao
- **Decompile Lua** — .luac ko readable source banao (unluac.jar chahiye)
- **Compile Folder** — poore folder ke .lua ek saath compile karo

### OBB TOOL
- **Unpack OBB** — obb kholo
- **Repack OBB** — naya obb banao

---

## KEY

Tool unlock karne ke liye key chahiye. Key ke liye owner se rabta karo.

---

## UPDATE

Tool har baar start/REFRESH hote hi **naya version automatically check** karta hai —
naya ho to khud download+install ho jata hai. Kuch nahi karna.

---

## ISSUES

- **AES key puchta hai?** — Encrypted pak hai, AES key chahiye.
- **unluac.jar nahi?** — LUA_TOOL folder me unluac.jar rakho (decompile ke liye).
- **Permission problem?** — Termux ko storage access do: `termux-setup-storage`
