"""Isolated LJD worker process.

Run as:  python3 ljd_worker.py <input.luac> <ljd_dir> <output.lua>

lua_pipeline._ljd_decompile launches this and enforces a wall-clock timeout on
it. ljd.tools.decompile walks the bytecode graph in pure Python, so a truncated
or hostile chunk can send it into an unbounded loop. In-process that loop
cannot be interrupted at all, which is why the tool used to freeze instead of
reporting a timeout. Out here the parent can simply kill it.

The result is written to a file rather than stdout because ljd prints progress
chatter of its own, and a short write on stdout would be indistinguishable
from a genuinely short decompile.
"""
import contextlib
import io
import sys


def main(argv) -> int:
    if len(argv) != 4:
        return 2
    src, ljd_dir, out_path = argv[1], argv[2], argv[3]

    sys.path.insert(0, ljd_dir)
    from ljd.rawdump import parser
    import ljd.tools as tools
    import ljd.lua.writer as lua_writer

    sink = io.StringIO()
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
            header, proto = parser.parse(src)
            if header is None:
                return 1
            ast = tools.decompile(header, proto)
            lua_writer.write(buf, ast)
    except BaseException:
        # BaseException on purpose: a worker that dies must exit non-zero so
        # the parent reports "could not parse" instead of an empty success.
        return 1

    text = buf.getvalue()
    if not text or not text.strip():
        return 1
    try:
        with open(out_path, "w", encoding="utf-8") as fh:
            fh.write(text)
    except OSError:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
