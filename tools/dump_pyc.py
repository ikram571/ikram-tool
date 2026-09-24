import dis, marshal, sys, types
from pathlib import Path

def walk_code(co, depth=0):
    yield co, depth
    for c in co.co_consts:
        if isinstance(c, types.CodeType):
            yield from walk_code(c, depth + 1)

def dump(path, out_dir):
    data = Path(path).read_bytes()
    if data[:4] == b"\x2b\x0e\x0d\x0a":
        data = data[16:]  # strip 3.7+ 16-byte header
    code = marshal.loads(data)
    mod = Path(path).stem
    d = out_dir / mod
    d.mkdir(parents=True, exist_ok=True)
    lines = []
    idx = []
    nf = 0
    for i, (co, depth) in enumerate(walk_code(code)):
        name = co.co_name
        nf += 1
        nloc = getattr(co, "co_localsplus", len(co.co_varnames) + len(co.co_cellvars) + len(co.co_freevars))
        lines.append("\n### [%d] %s%s%s :: line %d, args %d, locals %d, stack %d, consts %d" % (
            i, "  " * depth, name if name else "<module>",
            "" if co.co_filename == str(path) else "  (file=%s)" % Path(co.co_filename).name,
            co.co_firstlineno, len(co.co_varnames), nloc, co.co_stacksize,
            len(co.co_consts)))
        if depth == 0:
            idx.append("MODULE %s" % mod)
        else:
            idx.append("  fn %s (line %d)" % (name, co.co_firstlineno))
        lines.append(dis.Bytecode(co).dis())
    (d / "full.txt").write_text("\n".join(lines), encoding="utf-8", errors="replace")

    top = code
    apis = sorted({n for n in top.co_names if not n.startswith("__")})
    strconsts = sorted({c for c in top.co_consts if isinstance(c, str)})
    (d / "index.txt").write_text(
        "# %s\n# funcs=%d\n# top-level names:\n%s\n# module str consts:\n%s\n" % (
            mod, nf, "\n".join("  " + n for n in apis),
            "\n".join("  %r" % s for s in strconsts)),
        encoding="utf-8", errors="replace")
    return d

if __name__ == "__main__":
    src = Path(sys.argv[1])
    out = Path(sys.argv[2])
    for p in sorted(src.glob("*.pyc")):
        try:
            d = dump(p, out)
            print("dumped %-28s -> %s" % (p.name, d.name))
        except Exception as e:
            print("FAIL %-28s %s" % (p.name, e))