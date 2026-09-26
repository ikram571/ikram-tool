import ast
import re, pathlib, collections

root = pathlib.Path("analysis/pyc_dump")
strs = collections.Counter()
imps = collections.Counter()

# LOAD_CONST '<string>'  (dis output; strings repr'd, may use \x escapes)
RE_CONST = re.compile(r"LOAD_CONST\s+\d+\s+\(('(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\")\)\s*$")
RE_IMPORT = re.compile(r"IMPORT_NAME\s+\d+\s+\((\w+)\)\s*$")

for f in root.glob("*/full.txt"):
    mod = f.parent.name
    src = f.read_text(errors="replace")
    for ln in src.splitlines():
        m = RE_CONST.search(ln)
        if m:
            try:
                s = ast.literal_eval(m.group(1))
                strs[(mod, s)] += 1
            except Exception:
                pass
        m = RE_IMPORT.search(ln)
        if m:
            imps[(mod, m.group(1))] += 1

with open("analysis/evidence.txt", "w") as out:
    out.write("=== IMPORTS (compiled chain) ===\n")
    for (mod, n), c in imps.most_common():
        out.write("%-18s %s (%d)\n" % (mod, n, c))
    out.write("\n=== STRING CONSTANTS (compiled chain) ===\n")
    for (mod, s), c in strs.most_common(260):
        out.write("%-18s %r (%d)\n" % (mod, s, c))

print("imports=%d unique, strings=%d unique" % (len(imps), len(strs)))