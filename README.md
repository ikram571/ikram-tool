# IKRAM TOOL

**PAK / LUA Modding Tool** — Termux ke liye (PUBG / BGMI)

Unpack, inject, repack pak files · Compile/decompile lua.

## Install (ONE LINE)

Termux kholo aur ye **ek line** paste karo — sab kuch khud install ho jayega
(python, java, lua, git + tool): non-root, koi permission nahi chahiye.

```
curl -sL https://raw.githubusercontent.com/ikram571/ikram-tool/main/install.sh | bash
```

📌 Ya phir `ikram` command banane ke baad:

```
ikram
```

Pehli baar valid **KEY** maangi jayegi — owner se lo.

## Auto-update

Tool har baar kholne par **khud check** karta hai ki naya version aaya hai
ya nahi. Aaya toh **khud update** ho jata hai — kuch karna nahi padta.
Naye version ke liye nayi key chahiye hogi (owner se).

## Folders

| Folder | Kya daalo |
|--------|-----------|
| `DROP/pak` | pak files |
| `DROP/lua` | lua / luac files |
| `DROP/inject` | koi bhi file |
| `RESULT` | har kaam ka output yahan |

## Notes

- Original pak kabhi change nahi hota — result hamesha `RESULT` me naya file.
- Tool protected hai — source modify nahi ho sakta, sirf use hota hai.
