# IKRAM TOOL
**PAK / LUA Modding Tool** — Termux ke liye (PUBG / BGMI)

Unpack, inject, repack pak files · Compile/decompile lua. V109.

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

Tool ke `DROP` folder me files daalo, phir option choose karo.

| Folder | Kya daalo |
|--------|-----------|
| `DROP/pak` | pak files (unpack / inject / repack / costom ke liye) |
| `DROP/lua` | lua / luac files (compile / decompile) |
| `DROP/inject` | koi bhi file jo inject karni hai |

Result har kaam ke baad `RESULT` folder me milta hai:
`result/Repacked`, `result/injected`, `result/extracted`, `result/lua`, `result/CostomPak`.

### PAK TOOL
- **Unpack PAK** — pak kholo, saari files folder me nikal lo (1 ya sab)
- **Inject File** — koi bhi file (lua/uasset/asset) pak ke andar daalo
- **Repack PAK** — edit ki files se naya pak banao (result me 1 hi file milti hai)
- **COSTOM PAK** — pak ka folder chain jitna file/chunk nikal ke naya chhota pak

### LUA TOOL
- **Compile (+ PROTECT)** — source .lua ko protect karke game bytecode banao (Lua 5.3)
- **Decompile** — .luac / game bytecode ko readable source banao

### EXTRA
- **Auto-update** — har start pe naya GitHub release check hota hai, mila to khud update.
- **Self-repair** — tool files missing ho to `ikram` launcher khud download karke repair.

---

## KEY

Tool unlock karne ke liye key chahiye. Key ke liye owner se rabta karo.

---

## UPDATE

Tool har baar start hote hi **naya version automatically check** karta hai —
naya ho to khud download+install ho jata hai. Kuch nahi karna.

---

## ISSUES

- **AES key puchta hai?** — Encrypted pak hai, AES key chahiye.
- **unluac.jar nahi?** — LUA_TOOL folder me unluac.jar rakho (decompile ke liye).
- **Permission problem?** — Termux ko storage access do: `termux-setup-storage`
- **Python purana?** — launcher khud `pkg upgrade -y python` karke repack kar leta hai.
- **Result me 2 repacked files?** — V109 fix: purani `repacked/` twin ab khud delete hoti hai.