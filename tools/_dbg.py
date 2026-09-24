import re
src = open("analysis/pyc_dump/crypto_engine/full.txt", errors="replace").read()
line = None
for ln in src.splitlines():
    if "LOAD_CONST" in ln and "('" in ln:
        line = ln
        break
print("len:", len(line))
RE1 = re.compile(r"LOAD_CONST\s+\d+\s+('(?:[^'\\]|\\.)*'\s*)$")
print("RE1 match:", bool(RE1.search(line)))
RE2 = re.compile(r"LOAD_CONST.*\)$")
print("RE2 match:", bool(RE2.search(line)))
# diagnose: find where it stops
m = re.compile(r"LOAD_CONST\s+\d+\s+'(?:[^'\\]|\\.)*").search(line)
print("partial:", m.end() if m else None, repr(line[m.end()-30:m.end()+5]) if m else "")