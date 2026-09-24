import re, pathlib, collections

root = pathlib.Path("analysis/pyc_dump")
RE = re.compile(r'LOAD_CONST\s+\d+\s+\(\'((?:[^\'\\]|\\.)*)\'|"((?:[^"\\]|\\.)*)"\)\s*$')

pats = {
    "VERSION_STR": r"V\d{2,3}|version",
    "URL": r"http|github|jsdelivr|t\.me|telegram",
    "LICENSE": r"key|hash|licen|regist|expire|owner|FREETOOL",
    "ENGINES": r"Decompile|Repack|Decrypt|Inject|Migrate|luckymod|Global|Unpack",
    "CRYPTO": r"AES|SM4|XOR|zstd|pakcrypto|ue4|lz4",
    "EXTERNAL": r"unluac|ljd|repak|u4pak|quickbms|ghidra|reko|cfr|java|luac|binwalk",
}
found = collections.defaultdict(set)
for f in root.glob("*/full.txt"):
    mod = f.parent.name
    for ln in f.read_text(errors="replace").splitlines():
        m = RE.search(ln)
        if not m:
            continue
        s = m.group(1) if m.group(1) else m.group(2)
        if s is None:
            continue
        for p, rx in pats.items():
            if re.search(rx, s, re.I):
                found[p].add((mod, s))

for p, items in found.items():
    print("### %s (%d unique)" % (p, len(items)))
    for mod, s in sorted(items)[:24]:
        print("  %-14s %r" % (mod, s[:90]))