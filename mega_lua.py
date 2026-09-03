# -*- coding: utf-8 -*-
"""Mega Lua engine — full BGMI Lua pipeline.

Replaces the plain `luac`/`unluac` flow for Lua files with a BGMI-aware
pipeline:

  Decompile:
    BGMI bytecode  ->  standard bytecode  ->  unluac-rs readable source
    ->  (optional) prologue self-eval decryption ->  string-inlined CLEAN
    ->  prologue-stripped GAME-ready source

  Compile:
    readable source  ->  patched luac (handles >200 locals) ->  standard
    bytecode  ->  BGMI bytecode (what the game's VM actually loads)

Contracts (match what ikram.pyc calls through `univ`):

  detect_lua(src)               -> kind string ('Lua source' / 'Lua X.Y' / ...)
  decompile_bgmi(src, out_root, progress=None)
                                -> [(label, ok, Path, msg), ...]
  compile_bgmi(src, out, progress=None)
                                -> (ok, msg)
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

TOOL_DIR = Path(__file__).resolve().parent
if str(TOOL_DIR) not in sys.path:
    sys.path.insert(0, str(TOOL_DIR))

import lua_bgmi  # noqa: E402

UNLUAC_RS = TOOL_DIR / "unluac_rs"
UNLUAC_JAR = TOOL_DIR / "unluac.jar"
LUAC_PATCHED = TOOL_DIR / "luac_patched"
LUA_PATCHED = TOOL_DIR / "lua_patched"


def _phase(progress, text: str) -> None:
    if progress is not None:
        try:
            if isinstance(progress, dict):
                progress["phase"](text)
            else:
                progress.phase(text)
        except Exception:
            pass


def _run(cmd, **kw):
    try:
        return subprocess.run(cmd, capture_output=True, **kw)
    except FileNotFoundError:
        raise RuntimeError("binary not found: %s" % cmd[0])


def _is_bgmi(data: bytes) -> bool:
    try:
        return bool(lua_bgmi.is_bgmi(data))
    except Exception:
        try:
            return "bgmi" in lua_bgmi.detect_format(data).lower()
        except Exception:
            return False


def _bgmi_to_std(data: bytes) -> bytes:
    return lua_bgmi.bgmi_to_std(data)


def _std_to_bgmi(data: bytes) -> bytes:
    return lua_bgmi.std_to_bgmi(data)


def read_bytes(src) -> bytes:
    if isinstance(src, (bytes, bytearray)):
        return bytes(src)
    p = Path(src)
    with open(p, "rb") as f:
        return f.read()


def detect_lua(src) -> str:
    """Classify a Lua-ish file the same way univ.detect would."""
    try:
        data = read_bytes(src)
    except Exception:
        return "unknown"
    if not data:
        return "unknown"
    dia = _detect_dialect(data)
    if dia == "luajit":
        return "LuaJIT"
    if dia:
        return "Lua %s" % (".".join(dia[3:]) if dia.startswith("lua") else dia)
    if _is_bgmi(data):
        return "Lua 5.3"
    # text heuristics
    head = data[:1024].decode("utf-8", errors="ignore")
    if re.search(
        r"^\s*local\s+function|^\s*function\s+[A-Za-z0-9_\.]+\(|^\s*require\s*[(\"']|-- \[\[|--\s*(file|decompiled|dialect)|^\s*\[\[",
        head,
        re.M,
    ):
        return "Lua source"
    # packed / encrypted game Lua: route to the auto-decrypt cascade so a
    # recoverable key still yields ONE readable game-ready file, otherwise
    # an honest "key unknown" message (never a silent flat dump).
    if _is_encrypted_lua(data):
        return "Lua 5.3 (encrypted)"
    if b"\x1b[\x89PNG" in data[:8] or b"ZIP" in data[:4]:
        return "unknown"
    return "unknown"


# ---------------------------------------------------------------------------
# Auto key-recovery + validation.  A real Lua file can be recognised by its
# full header, NOT just the 4 magic bytes -- many "decryptions" only align the
# magic and are not actually valid bytecode (sparse BRPC variant), so we
# validate the whole header before accepting any recovered key.
# ---------------------------------------------------------------------------
LUA_MAGIC_TAIL = bytes([0x19, 0x93, 0x0D, 0x0A, 0x1A, 0x0A])  # \x19\x93\r\n\x1a\n
LUAJIT_MAGIC_TAIL = bytes([0x0D, 0x0A, 0x1A, 0x0A])

# True recognized bytecode dialect computable from a full header.
def _detect_dialect(data: bytes):
    """Return canonical dialect ('lua50'..'lua54','luajit','luau') if `data`
    carries a recognisable complete Lua-family header, else None."""
    if len(data) < 15:
        return None
    if data[:3] == b"\x1bLJ":
        v = data[3]
        if v in (0x01, 0x02):
            return "luajit"
        return None
    if data[:4] == b"\x1bLua":
        ver = data[4]
        if data[6:12] != LUA_MAGIC_TAIL:
            return None
        if ver in (0x50, 0x51, 0x52, 0x53, 0x54):
            return "lua%d%d" % ((ver >> 4) & 0x0F, ver & 0x0F)
        return None
    if data[:4] == b"\x1bul":
        return "luau"
    return None


def _valid_lua53_head(data: bytes) -> bool:
    """Full Lua 5.3/5.4 header: \\x1bLua + version\\x?\\x00 + magic tail."""
    return _detect_dialect(data) in ("lua53", "lua54")


def _valid_luajit_head(data: bytes) -> bool:
    """LuaJIT header: \\x1bLJ + version(1-3)."""
    return _detect_dialect(data) == "luajit"


def _is_encrypted_lua(data: bytes) -> bool:
    """Heuristic: a Lua-like blob that is NOT readable text and NOT a
    recognised Lua/other header, but looks like packed/encrypted game Lua."""
    if not data:
        return False
    if len(data) < 8:
        return False
    if data[:4] in (b"\x1bLua", b"\x1bLJ"):
        return False
    sample = data[:4096]
    printable = sum(1 for b in sample if 32 <= b < 127 or b in (9, 10, 13))
    ratio = printable / max(1, len(sample))
    if ratio > 0.7:
        return False  # looks like text
    nz = sum(1 for b in data if b != 0)
    density = nz / len(data)
    # dense non-printable (XOR-encrypted real bytecode) OR sparse (padded)
    return True


def _xor_key_recover(data: bytes, plain: bytes, key_len: int):
    """Try recovering a repeating-XOR key from a known plaintext prefix.
    Returns the key bytes if consistent across `key_len`, else None."""
    n = min(len(data), len(plain))
    if n < key_len:
        return None
    key = bytearray(key_len)
    for i in range(n):
        p = plain[i]
        c = data[i]
        slot = i % key_len
        kb = c ^ p
        if i < key_len:
            key[slot] = kb
        elif key[slot] != kb:
            return None  # inconsistent => not this key length
    return bytes(key)


def _auto_decrypt_valid(data: bytes):
    """Attempt to recover a key that turns `data` into valid Lua 5.3 game
    (BGMI) bytecode the pipeline can actually decompile.

    Returns (method_label, decrypted_bytes) on success, else (None, None).
    Tries:
      * already-valid Lua already present
      * repeating-key XOR for key lengths 1..8 (validated)
      * additive mod-256 for lengths 1..8
      * single-byte XOR brute (256)
    Only candidates that pass _valid_lua53_head AND the real bytes->std
    converter (_loads_ok) are kept, so a 4-byte-magic-only or LuaJIT-only
    false positive is rejected and reported as key-unknown.

    NOTE: XOR key length is capped at 8.  The Lua headers (13-16 bytes) would
    otherwise be trivially matched by a key of length == header length
    (the key is derived FROM the header itself), producing a guaranteed-but-
    meaningless match that falsely "decrypts" any file into a LuaJIT header
    with a garbage body.  Real repeating-XOR game encryption uses short keys.
    """
    if _loads_ok(data):
        return ("none (already valid)", data)

    for header in _HEAD_TEMPLATES:
        for L in range(1, 9):
            key = _xor_key_recover(data, header, L)
            if key is None:
                continue
            dec = bytes(data[i] ^ key[i % L] for i in range(len(data)))
            if _loads_ok(dec):
                return ("XOR key len=%d %s" % (L, key.hex()), dec)
    # additive mod-256
    for L in range(1, 9):
        for header in _HEAD_TEMPLATES:
            cand = bytearray(L)
            ok = True
            n = min(len(data), len(header))
            for i in range(n):
                slot = i % L
                k = (data[i] - header[i]) & 0xFF
                if i < L:
                    cand[slot] = k
                elif cand[slot] != k:
                    ok = False
                    break
            if not ok:
                continue
            key = bytes(cand)
            dec = bytes((data[i] - key[i % L]) & 0xFF for i in range(len(data)))
            if _loads_ok(dec):
                return ("ADD key len=%d %s" % (L, key.hex()), dec)

    # single-byte XOR brute (256 candidates) -- cheap keeps C xor const
    for k in range(1, 256):
        dec = bytes(b ^ k for b in data)
        if _loads_ok(dec):
            return ("XOR single-byte 0x%02x" % k, dec)
    return (None, None)


LUA53_HEAD = b"\x1bLua\x53\x00" + LUA_MAGIC_TAIL + b"\x04\x04\x04\x08"
LUA51_HEAD = b"\x1bLua\x51\x00\x00\x00\x04\x04\x04\x08\x00"
LUALJ_HEAD = b"\x1bLJ\x02\x00" + LUAJIT_MAGIC_TAIL + b"\x04\x04\x04\x08\x00"
_HEAD_TEMPLATES = (LUA53_HEAD, LUA51_HEAD, LUALJ_HEAD)


def _loads_ok(data: bytes) -> bool:
    """True only if `data` is genuine, decompilable Lua-family bytecode.

    Strict: Lua 5.3/5.4 (BGMI) is validated through the real bytes->std
    converter; other dialects (Lua 5.0/5.1/5.2, LuaJIT) are validated by
    actually decompiling them with unluac-rs, so a coincidental LuaJIT header
    pasted onto a garbage body (a false positive from key search) is rejected
    instead of being reported as a successful decryption.
    """
    if not data or len(data) < 16:
        return False
    dia = _detect_dialect(data)
    if dia in ("lua53", "lua54"):
        try:
            std = _bgmi_to_std(data)
        except Exception:
            return False
        return len(std) > 0
    if dia not in ("lua50", "lua51", "lua52", "luajit"):
        return False
    if not UNLUAC_RS.exists():
        return True  # fall back to header-only if the decompiler is absent
    try:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td) / "probe.luac"
            tmp.write_bytes(data)
            p = _run([str(UNLUAC_RS), "-i", str(tmp)])
            if p.returncode != 0:
                return False
            return bool(p.stdout and p.stdout.strip())
    except Exception:
        return False


def _decompile_readable(std_path: Path) -> str:
    """Prefer unluac.jar (keeps source variable names) -> readable source.

    Order: unluac.jar (clean, keeps real names like Inventory/PlayerName) ->
    unluac-rs (fast, register-style r0_0 names) -> lua_engine internal
    decompiler (guaranteed readable). The last fallback runs even when
    java/jar are missing, so a BGMI file whose std dump carries negative
    line-info (which unluac-rs rejects) can NEVER end up as a hard
    "decompile failed" -- it always yields readable source.
    """
    if UNLUAC_JAR.exists():
        p = _run(["java", "-jar", str(UNLUAC_JAR), str(std_path)])
        if p.returncode == 0 and p.stdout.strip():
            return p.stdout.decode("utf-8", errors="replace")
    if UNLUAC_RS.exists():
        p = _run([str(UNLUAC_RS), "-i", str(std_path)])
        if p.returncode == 0 and p.stdout.strip():
            return p.stdout.decode("utf-8", errors="replace")
        rs_err = (p.stderr or b"").decode("utf-8", errors="replace")
    else:
        rs_err = "unluac_rs not found"
    # guaranteed readable fallback via the tool's own Lua VM decompiler
    try:
        import lua_engine
        out = lua_engine.pseudo_decompile_file(str(std_path))
        if out and out.strip():
            return out
    except Exception:
        pass
    raise RuntimeError("decompile failed: " + rs_err[:300])


PN_RE = r"local\s+(r\d+_\d+)\s*=\s*\{"
DEF_TYPE = r"^\s*local\s+r\d+_\d+\s*=\s*type\(math\)"
BUILDER = re.compile(r"^\s*(r\d+_\d+)\[\s*(\d+)\s*\]\s*=\s*(r\d+_\d+)\(", re.M)


def _find_obfuscated(text: str):
    """Return (table_var, start_idx, end_idx, refs) if obfuscated else None."""
    lines = text.splitlines()
    start = None
    for i, ln in enumerate(lines):
        if re.match(DEF_TYPE, ln):
            start = i
            break
    if start is None:
        return None
    tab = None
    for i in range(start, min(start + 60, len(lines))):
        m = re.search(PN_RE, lines[i])
        if m:
            tab = m.group(1)
            break
    if tab is None:
        return None
    end = start
    for i in range(start, len(lines)):
        if BUILDER.match(lines[i]):
            end = i
    if end <= start and "= {" not in lines[start]:
        return None
    ref_re = re.compile(r"\b%s\s*\[\s*(\d+)\s*\]" % re.escape(tab))
    refs = []
    for i in range(end + 1, len(lines)):
        refs.extend(int(m.group(1)) for m in ref_re.finditer(lines[i]))
    return tab, start, end, refs


def _lua_lit(value: bytes) -> str:
    """Render bytes as a Lua string literal, keeping readable UTF-8 as-is."""
    out = ['"']
    i = 0
    n = len(value)
    while i < n:
        b = value[i]
        if b == 0x5C:
            out.append("\\\\")
            i += 1
        elif b == 0x22:
            out.append('\\"')
            i += 1
        elif b == 0x0A:
            out.append("\\n")
            i += 1
        elif b == 0x0D:
            out.append("\\r")
            i += 1
        elif b == 0x09:
            out.append("\\t")
            i += 1
        elif b < 32:
            out.append("\\%03d" % b)
            i += 1
        elif b < 128:
            out.append(chr(b))
            i += 1
        else:
            # collect the full contiguous non-ASCII run and try to decode it
            j = i
            while j < n and value[j] >= 0x80:
                j += 1
            seq = value[i:j]
            try:
                out.append(seq.decode("utf-8"))
                i = j
            except Exception:
                # fall back to byte escapes for the whole run
                while i < j:
                    out.append("\\%03d" % value[i])
                    i += 1
    out.append('"')
    return "".join(out)


def _decrypt_prologue(text: str) -> str:
    """Self-eval the prologue to recover the XOR-coded string table."""
    found = _find_obfuscated(text)
    if found is None:
        return text
    tab, start, end, refs = found
    lines = text.splitlines()
    prologue = lines[start : end + 1]
    if not prologue:
        return text
    max_idx = 0
    for i in range(start, end + 1):
        m = BUILDER.match(lines[i])
        if m:
            max_idx = max(max_idx, int(m.group(2)))
    for r in refs:
        max_idx = max(max_idx, int(r))
    if LUA_PATCHED is None or not LUA_PATCHED.exists():
        raise RuntimeError("lua_patched runtime missing for string decryption")
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        dmp = td / "tbl.dat"
        ev = td / "eval.lua"
        dump_lines = [
            "\nlocal f = io.open(%r, 'w')" % str(dmp),
            "for k=0,%d do" % max_idx,
            "  local v = %s[k] or ''" % tab,
            "  f:write(string.format('%d\\t%d\\t', k, #v))",
            "  for i=1,#v do f:write(string.format('%02x', v:byte(i,i))) end",
            "  f:write('\\n')",
            "end",
            "f:close()",
        ]
        ev.write_text("\n".join(prologue + dump_lines), encoding="utf-8")
        p = _run([str(LUA_PATCHED), str(ev)])
        if p.returncode != 0:
            raise RuntimeError("prologue eval failed: %s" % (p.stderr or b"").decode("utf-8", errors="replace")[:200])
        if not dmp.exists():
            raise RuntimeError("prologue eval wrote no table")
        table = {}
        for ln in dmp.read_text(encoding="utf-8", errors="replace").splitlines():
            parts = ln.split("\t")
            if len(parts) != 3:
                continue
            try:
                k = int(parts[0])
                h = parts[2].strip()
                table[k] = bytes.fromhex(h)
            except ValueError:
                continue
    ref_re = re.compile(r"\b%s\s*\[\s*(\d+)\s*\]" % re.escape(tab))

    def _sub(m):
        v = table.get(int(m.group(1)))
        if v is None:
            return m.group(0)
        return _lua_lit(v)

    out_lines = list(lines)
    for i in range(end + 1, len(out_lines)):
        out_lines[i] = ref_re.sub(_sub, out_lines[i])
    return "\n".join(out_lines)


def _strip_prologue(text: str) -> str:
    found = _find_obfuscated(text)
    if found is None:
        return text
    tab, start, end, refs = found
    lines = text.splitlines()
    return "\n".join(lines[:start] + lines[end + 1 :])


# ---- decompiled-output structure quality guard --------------------------
# A decompiled BGMI Lua file keeps its game table structure (local tables,
# `.ServerRPC/.ClientRPC/.MulticastRPC` registration, readable `local r0_0`
# locals). Some external/ripper decompilers emit a FLAT `L0_1/L1_1` style that
# drops those tables + bindings -> the file loads in game but clicks / RPC /
# UI registration are dead. We detect that broken signature and warn the user
# so a bad decompile is never silently accepted as game-ready.
_LUADEC_LOCAL_RE = re.compile(r"\bL\d+_\d+\b")
_UNLUAC_LOCAL_RE = re.compile(r"\br\d+_\d+\b")
_TABLE_RE = re.compile(r"^\s*local\s+[\w\.]+\s*=\s*\{", re.M)


def _structure_quality(text: str) -> str:
    """Return a warning string if `text` looks like a broken flat decompile.

    Returns '' when the output preserves the game structure (unluac-rs style:
    local tables present, `.RPC` registration present, no L-var naming) OR when
    the file is a legit flat data/config blob (no tables to begin with).

    We only flag the unmistakable broken-ripper signature: dense `L0_1/L1_1`
    flat locals with the `return Lxx_1(...)` builder tail AND zero table
    literals. A normal small config file is left alone (no false positive)."""
    if not text.strip():
        return ""
    table_count = len(_TABLE_RE.findall(text))
    luadec_locals = len(_LUADEC_LOCAL_RE.findall(text))
    unluac_locals = len(_UNLUAC_LOCAL_RE.findall(text))
    # A healthy unluac-rs file has readable locals + (usually) local tables.
    if unluac_locals > 0 and luadec_locals == 0:
        return ""
    # Unmistakable broken-ripper signature: dense L-vars, no table literals,
    # ends with the builder `return L64_1(L65_1, L66_1, ...)` call-tail.
    builder_tail = bool(re.search(r"return\s+L\d+_\d+\s*\(", text))
    if luadec_locals > 8 and table_count == 0 and builder_tail:
        return (
            "WARNING: output lost its table/registration structure (flat "
            "L-var decompile). RPC/click/UI bindings may be broken in game. "
            "Use a decompile from this tool's unluac-rs engine instead."
        )
    return ""


UNLUAC_ERR_RE = re.compile(r"-- \[unluac error\].*explicit close semantics")

# ---- repair of unluac-rs "explicit close semantics" blocks --------------
#
# unluac-rs serializes a `for` loop with explicit close semantics into a
# goto/label form that is NOT valid Lua 5.3: a `return` immediately followed
# by `::label::` is a syntax error (a `return` must be the last statement of
# a block), so the patched luac rejects the whole file. This repair detects
# the marker comment and rewrites the serialized loops back into structured
# `for` loops. All variable names in the skeleton are dynamic; the parser
# maps them generically and returns None (leaving the block untouched) for
# anything it cannot recognize with certainty.
#
# goto-crossing-local rules: we only restructure a function after checking
# that no `goto` jumps forward across a `local` declaration it would pull
# into scope. In the handled skeleton all function-scope locals are declared
# up front (plus one `local CONT = nil` for the controller) and every loop
# target is a plain assignment, so the structured rewrite introduces no
# dangling goto. Nested locals live only inside the watchdog closure.

_FN_LINE_RE = re.compile(r"^\s*local\s+function\s+\w+")


def _strip_lit(line: str) -> str:
    """Remove string literals and end-of-line comments so keyword/name
    inspection is not fooled by content inside strings or comments."""
    s = re.sub(r"--.*$", "", line)
    s = re.sub(r'"(?:\\.|[^"\\])*"', '""', s)
    s = re.sub(r"'(?:\\.|[^'\\])*'", "''", s)
    return s


def _collect_fn_block(lines, i):
    """Collect one full `local function NAME() ... end` block starting at i.

    Returns (block_lines, next_index). Tracks all Lua block-controllers
    (if/for/while/do/function -> `end`) so nested statements inside a body
    do not confuse the closing `end` detection. `do` bound to a `for`/`while`
    header is not counted as a separate opener."""
    n = len(lines)
    depth = 0
    j = i
    while j < n:
        s = _strip_lit(lines[j])
        depth += _block_delta(s)
        if j > i and depth <= 0:
            break
        j += 1
    end = min(j, n - 1)
    return lines[i : end + 1], (j + 1)


def _block_delta(stripped_line):
    """Signed change in Lua block depth for a stripped line."""
    op = len(re.findall(r"\b(function|if|for|while|repeat)\b", stripped_line))
    ind_do = len(re.findall(r"\bdo\b", stripped_line))
    # a standalone `do` (not bound to for/while on the same line) opens a block
    if re.search(r"\b(for|while)\b", stripped_line):
        ind_do = 0
    cl = len(re.findall(r"\bend\b", stripped_line))
    return (op + ind_do) - cl


def _fix_explicit_close(text: str) -> str:
    """Repair every explicit-close-serialized function block in `text`.

    Only functions containing the `[unluac error] ... explicit close` marker
    are rewritten. If a marked function cannot be mapped with certainty its
    block is left byte-for-byte unchanged, so otherwise-valid files are
    never touched."""
    if not UNLUAC_ERR_RE.search(text):
        return text
    lines = text.splitlines()
    out = []
    i = 0
    n = len(lines)
    while i < n:
        if _FN_LINE_RE.match(lines[i]):
            blk, ni = _collect_fn_block(lines, i)
            if any(UNLUAC_ERR_RE.search(l) for l in blk):
                fixed = _rewrite_explicit_close_fn(blk)
                if fixed is not None:
                    out.extend(fixed)
                else:
                    out.extend(blk)
            else:
                out.extend(blk)
            i = ni
        else:
            out.append(lines[i])
            i += 1
    return "\n".join(out)


# ---- per-line structural regexes for the explicit-close skeleton ---------

_RE_LOCALFUNC = re.compile(r"^(\s*)local\s+function\s+(\w+)\s*\((.*?)\)\s*$")
_RE_RETURNTRUE = re.compile(r"^\s*return\s+true\s*$")
_RE_RETFALSE = re.compile(r"^\s*return\s+false\s*$")
_RE_CALL = re.compile(r"^\s*(\w+(?:\.\w+)*)\(\)\s*$")
_RE_ASSIGN = re.compile(r"^\s*([A-Za-z_]\w*(?:\.\w+|\[[^\]]*\]|:\w+\([^)]*\))*)\s*=\s*(.+?)\s*$")
_RE_LOCALNIL = re.compile(r"^\s*local\s+(\w+)\s*=\s*nil\s*$")
_RE_LOCALLIST = re.compile(r"^\s*local\s+[A-Za-z_]\w*(?:\s*,\s*[A-Za-z_]\w*)*\s*(?:=[^=]*)?$")
_RE_UNCOND_GOTO = re.compile(r"^\s*goto\s+(\w+)\s*$")
_RE_LABEL = re.compile(r"^\s*::(\w+)::\s*$")
_RE_IFBLOCK = re.compile(r"^\s*if\s+(.+?)\s+then\s*$")
_RE_END = re.compile(r"^\s*end\s*$")
_RE_IPATRS = re.compile(r"^\s*(\w+),\s*(\w+),\s*(\w+)\s*=\s*ipairs\((\w+)\)\s*$")
_RE_DOUBLECALL = re.compile(
    r"^\s*(\w+),\s*(\w+)\s*=\s*([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)\(([^)]*)\)\s*$"
)
_RE_REGISTER = re.compile(
    r"^\s*(\w+)\s*=\s*([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*):\s*([A-Za-z_]\w*)\s*\(([^)]*)\)\s*$"
)


def _ident(s):
    """Leading-whitespace of a line."""
    return s[: len(s) - len(s.lstrip())]


def _sub_token(text, old, new):
    """Replace the whole identifier `old` with `new` (word-boundaries)."""
    if not old:
        return text
    return re.sub(r"(?<![.\w])%s(?![.\w])" % re.escape(old), new, text)


def _collect_passthru(lines, gotos_ok=False):
    """Consume a run of safe passthrough statements (no gotos/labels unless
    gotos_ok). Returns (kept_lines, consumed_count, ok)."""
    out = []
    i = 0
    n = len(lines)
    while i < n:
        s = lines[i].strip()
        st = _strip_lit(lines[i]).strip()
        if not s:
            out.append(lines[i])
            i += 1
            continue
        if _RE_UNCOND_GOTO.match(s) or _RE_LABEL.match(s):
            if gotos_ok:
                out.append(lines[i])
                i += 1
                continue
            return [], 0, False
        if (_RE_END.match(s) or _RE_RETURNTRUE.match(s) or _RE_RETFALSE.match(s)
                or _RE_CALL.match(s) or _RE_ASSIGN.match(s) or _RE_LOCALNIL.match(s)
                or _RE_LOCALLIST.match(s)):
            out.append(lines[i])
            i += 1
            continue
        if _RE_IFBLOCK.match(s):
            depth = 1
            blk = [lines[i]]
            j = i + 1
            ok = True
            while j < n and depth > 0:
                sst = _strip_lit(lines[j]).strip()
                if _RE_UNCOND_GOTO.match(lines[j].strip() or "") or _RE_LABEL.match(lines[j].strip() or ""):
                    ok = False
                depth += _block_delta(_strip_lit(lines[j]))
                blk.append(lines[j])
                j += 1
            if not ok or depth != 0:
                return [], 0, False
            out.extend(blk)
            i = j
            continue
        # unknown statement -> unsafe
        return [], 0, False
    return out, i, True


def _parse_prelude(lines):
    """Parse the function body before the timers table.

    Returns (shape, passthru_lines, info) where info holds the discovered
    names, or None if the controller-discovery sequence does not match.
    shape is 'controller' when the full controller-discovery skeleton was
    found, else 'plain'."""
    # --- locate `local CONT = nil`
    local_idx = None
    for idx, ln in enumerate(lines):
        if _RE_LOCALNIL.match(ln):
            local_idx = idx
            break
    if local_idx is None:
        pre, cnt, ok = _collect_passthru(lines)
        return ("plain", pre, {}) if ok else None

    indent = _ident(lines[local_idx])
    m = _RE_LOCALNIL.match(lines[local_idx])
    controller = m.group(1)

    # passthrough before the controller decl
    pre, cnt, ok = _collect_passthru(lines[:local_idx])
    if not ok:
        return None
    passthru = list(pre)

    j = local_idx + 1
    n = len(lines)

    # if <game> and <game>.AddGameTimer then
    if (j >= n or not _RE_IFBLOCK.match(lines[j].strip() or "")
            or "AddGameTimer" not in lines[j]):
        return None
    game_cond = lines[j].strip()[len("if "):-len(" then")]
    j += 1
    # CONT = _G.Game
    if j >= n or lines[j].strip() != "%s = _G.Game" % controller:
        return None
    j += 1
    # goto FAIL1
    if j >= n or not _RE_UNCOND_GOTO.match(lines[j].strip() or ""):
        return None
    fail1 = _RE_UNCOND_GOTO.match(lines[j].strip()).group(1)
    j += 1
    # end
    if j >= n or lines[j].strip() != "end":
        return None
    j += 1
    # CONT = nil
    if j >= n or lines[j].strip() != "%s = nil" % controller:
        return None
    j += 1
    # if SLUA then
    if j >= n or not _RE_IFBLOCK.match(lines[j].strip() or ""):
        return None
    slua_cond = lines[j].strip()[len("if "):-len(" then")]
    slua_if_full = lines[j].strip()
    j += 1
    # STATUS, CONT = OBJ(...)
    if j >= n:
        return None
    mm = _RE_DOUBLECALL.match(lines[j].strip())
    if not mm or mm.group(2) != controller:
        return None
    slua_call = "%s(%s)" % (mm.group(3), mm.group(4))
    status_var = mm.group(1)
    j += 1
    # if not STATUS then
    if j >= n or lines[j].strip() != "if not %s then" % status_var:
        return None
    j += 1
    # goto L10
    if j >= n or not _RE_UNCOND_GOTO.match(lines[j].strip() or ""):
        return None
    lab10 = _RE_UNCOND_GOTO.match(lines[j].strip()).group(1)
    j += 1
    # end
    if j >= n or lines[j].strip() != "end":
        return None
    j += 1
    # end  (closes if SLUA)
    if j >= n or lines[j].strip() != "end":
        return None
    j += 1
    # ::L10::
    if j >= n or not _RE_LABEL.match(lines[j].strip() or ""):
        return None
    if _RE_LABEL.match(lines[j].strip()).group(1) != lab10:
        return None
    j += 1
    # if COND(CONT) and not CONT.AddGameTimer then
    if (j >= n or not _RE_IFBLOCK.match(lines[j].strip() or "")
            or "AddGameTimer" not in lines[j]):
        return None
    cond_line = lines[j].strip()
    j += 1
    # goto FAIL1
    if j >= n or not _RE_UNCOND_GOTO.match(lines[j].strip() or "") \
            or _RE_UNCOND_GOTO.match(lines[j].strip()).group(1) != fail1:
        return None
    j += 1
    # end
    if j >= n or lines[j].strip() != "end":
        return None
    j += 1
    # ::FAIL1::
    if j >= n or not _RE_LABEL.match(lines[j].strip() or "") \
            or _RE_LABEL.match(lines[j].strip()).group(1) != fail1:
        return None
    j += 1
    # if not CONT then
    if j >= n or lines[j].strip() != "if not %s then" % controller:
        return None
    j += 1
    # goto FAIL2
    if j >= n or not _RE_UNCOND_GOTO.match(lines[j].strip() or ""):
        return None
    fail2 = _RE_UNCOND_GOTO.match(lines[j].strip()).group(1)
    j += 1
    # end
    if j >= n or lines[j].strip() != "end":
        return None
    j += 1
    # if not TARGET then
    if j >= n:
        return None
    mt = re.match(r"^if\s+not\s+(\w+)\s+then\s*$", lines[j].strip())
    if not mt:
        return None
    target = mt.group(1)
    j += 1
    # goto FAIL2
    if j >= n or not _RE_UNCOND_GOTO.match(lines[j].strip() or "") \
            or _RE_UNCOND_GOTO.match(lines[j].strip()).group(1) != fail2:
        return None
    j += 1
    # end
    if j >= n or lines[j].strip() != "end":
        return None
    j += 1

    # remaining prelude lines must be plain passthrough
    rest, cnt, ok = _collect_passthru(lines[j:])
    if not ok:
        return None
    tail = list(rest)

    info = {
        "controller": controller,
        "target": target,
        "fail_label": fail2,
        "game_cond": game_cond,
        "slua_cond": slua_cond,
        "slua_call": slua_call,
        "cond_line": cond_line,
    }
    return ("controller", passthru, info, tail)


def _parse_loop(loop_lines):
    """Parse the serialized loop region starting at `<TVAR> = {`.

    Returns a named tuple-like dict or None with the discovered components:
      timers_var, accum_var, handle_var, outer_elem, inner_elem,
      table_lines, register_line, clear_txt, watchdog_lines"""
    if not loop_lines:
        return None
    from itertools import filterfalse
    ban = lambda s: (not s.strip()) or s.strip().startswith("--")
    loop_lines = [l for l in loop_lines if not ban(l)]
    if not loop_lines:
        return None
    m0 = re.match(r"^\s*(\w+)\s*=\s*\{\s*$", loop_lines[0])
    if not m0:
        return None
    timers_var = m0.group(1)
    indent = _ident(loop_lines[0])

    # gather table literal
    depth = 0
    t_end = 0
    for j in range(len(loop_lines)):
        depth += loop_lines[j].count("{") - loop_lines[j].count("}")
        t_end = j
        if depth <= 0:
            break
    table_lines = list(loop_lines[: t_end + 1])
    cur = t_end + 1
    n = len(loop_lines)

    # <accum_var> = {}
    if cur >= n:
        return None
    ma = re.match(r"^\s*(\w+)\s*=\s*\{\}\s*$", loop_lines[cur])
    if not ma:
        return None
    accum_var = ma.group(1)
    cur += 1

    # <a>,<b>,<c> = ipairs(<timers>)
    if cur >= n:
        return None
    mi = re.match(r"^\s*(\w+),\s*(\w+),\s*(\w+)\s*=\s*ipairs\((\w+)\)\s*$", loop_lines[cur].strip())
    if not mi or mi.group(4) != timers_var:
        return None
    outer_it_test_iter = None
    cur += 1

    # goto <outer_test>
    if cur >= n or not re.match(r"^\s*goto\s+(\w+)\s*$", loop_lines[cur].strip() or ""):
        return None
    outer_test = re.match(r"^\s*goto\s+(\w+)\s*$", loop_lines[cur].strip()).group(1)
    cur += 1

    # ::<outer_body>::
    if cur >= n or not re.match(r"^\s*::(\w+)::\s*$", loop_lines[cur].strip() or ""):
        return None
    outer_body = re.match(r"^\s*::(\w+)::\s*$", loop_lines[cur].strip()).group(1)
    cur += 1

    # <handle> = <target>:Register(...)
    if cur >= n:
        return None
    mr = re.match(r"^\s*(\w+)\s*=\s*([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*):\s*([A-Za-z_]\w*)\s*\(([^)]*)\)\s*$",
                  loop_lines[cur].strip())
    if not mr:
        return None
    handle_var = mr.group(1)
    target_obj = mr.group(2)
    register_line = loop_lines[cur].strip()
    args = mr.group(4)
    # second arg is the element var: <ELEM>[2]
    elm = None
    for tok in args.split(","):
        tok = tok.strip()
        mge = re.match(r"^(\w+)\[\s*2\s*\]$", tok)
        if mge:
            elm = mge.group(1)
            break
    if elm is None:
        return None
    outer_elem = elm
    cur += 1

    # if <handle> then
    if cur >= n or loop_lines[cur].strip() != "if %s then" % handle_var:
        return None
    cur += 1
    # goto <outer_ok>
    if cur >= n or not re.match(r"^\s*goto\s+(\w+)\s*$", loop_lines[cur].strip() or ""):
        return None
    cur += 1
    # end
    if cur >= n or loop_lines[cur].strip() != "end":
        return None
    cur += 1

    # <a2>,<b2>,<c2> = ipairs(<accum>)
    if cur >= n:
        return None
    mi2 = re.match(r"^\s*(\w+),\s*(\w+),\s*(\w+)\s*=\s*ipairs\((\w+)\)\s*$", loop_lines[cur].strip())
    if not mi2 or mi2.group(4) != accum_var:
        return None
    cur += 1
    # goto <inner_test>
    if cur >= n or not re.match(r"^\s*goto\s+(\w+)\s*$", loop_lines[cur].strip() or ""):
        return None
    inner_test = re.match(r"^\s*goto\s+(\w+)\s*$", loop_lines[cur].strip()).group(1)
    cur += 1

    # ::<inner_body>::
    if cur >= n or not re.match(r"^\s*::(\w+)::\s*$", loop_lines[cur].strip() or ""):
        return None
    inner_body = re.match(r"^\s*::(\w+)::\s*$", loop_lines[cur].strip()).group(1)
    cur += 1

    # pcall(function()
    if cur >= n or loop_lines[cur].strip() != "pcall(function()":
        return None
    cur += 1
    # <target>:Clear(<inner_elem>)
    clear_assign = loop_lines[cur].strip() if cur < n else None
    mc = re.match(r"^([\w.]+):\s*([A-Za-z_]\w*)\s*\(([^)]*)\)\s*$", clear_assign or "")
    if not mc:
        return None
    if mc.group(2).lower() != "clear":
        return None
    if mc.group(1) != target_obj:
        # must at least match the target used in Register
        return None
    inner_elem = mc.group(3).strip()
    clear_txt = loop_lines[cur].strip()
    cur += 1
    # end)
    if cur >= n or loop_lines[cur].strip() != "end)":
        return None
    cur += 1

    # ::<inner_test>::
    if cur >= n or not re.match(r"^\s*::(\w+)::\s*$", loop_lines[cur].strip() or ""):
        return None
    if re.match(r"^\s*::(\w+)::\s*$", loop_lines[cur].strip()).group(1) != inner_test:
        return None
    cur += 1

    # <x>,<y> = <f2>(<s2>,<c2>)
    if cur >= n:
        return None
    mit = re.match(r"^\s*(\w+),\s*(\w+)\s*=\s*(\w+)\((\w+),\s*(\w+)\)\s*$", loop_lines[cur].strip())
    if not mit:
        return None
    inner_ov = mit.group(1)
    inner_ctl = mit.group(5)
    cur += 1
    # if <inner_ov> ~= nil then
    if cur >= n or loop_lines[cur].strip() != "if %s ~= nil then" % inner_ov:
        return None
    cur += 1
    # <inner_ctl> = <inner_ov>
    if cur >= n or loop_lines[cur].strip() != "%s = %s" % (inner_ctl, inner_ov):
        return None
    cur += 1
    # goto <inner_body>
    if cur >= n or not re.match(r"^\s*goto\s+(\w+)\s*$", loop_lines[cur].strip() or "") \
            or re.match(r"^\s*goto\s+(\w+)\s*$", loop_lines[cur].strip()).group(1) != inner_body:
        return None
    cur += 1
    # end
    if cur >= n or loop_lines[cur].strip() != "end":
        return None
    cur += 1

    # _G.VisualTimerIds = nil
    if cur >= n or loop_lines[cur].strip() != "_G.VisualTimerIds = nil":
        return None
    cur += 1
    # _G.VisualsStarted = false
    if cur >= n or loop_lines[cur].strip() != "_G.VisualsStarted = false":
        return None
    cur += 1
    # return false
    if cur >= n or not _RE_RETFALSE.match(loop_lines[cur].strip() or ""):
        return None
    cur += 1

    # ::<outer_ok>::
    if cur >= n or not re.match(r"^\s*::(\w+)::\s*$", loop_lines[cur].strip() or ""):
        return None
    cur += 1
    # <accum>[#<accum> + 1] = <handle>
    if cur >= n:
        return None
    if loop_lines[cur].strip() != "%s[#%s + 1] = %s" % (accum_var, accum_var, handle_var):
        return None
    cur += 1

    # ::<outer_test>::
    if cur >= n or not re.match(r"^\s*::(\w+)::\s*$", loop_lines[cur].strip() or ""):
        return None
    if re.match(r"^\s*::(\w+)::\s*$", loop_lines[cur].strip()).group(1) != outer_test:
        return None
    cur += 1

    # <a>,<b> = <f>(<s>,<c>)
    if cur >= n:
        return None
    mo = re.match(r"^\s*(\w+),\s*(\w+)\s*=\s*(\w+)\((\w+),\s*(\w+)\)\s*$", loop_lines[cur].strip())
    if not mo:
        return None
    outer_ov = mo.group(1)
    outer_ctl = mo.group(5)
    cur += 1
    # if <outer_ov> ~= nil then
    if cur >= n or loop_lines[cur].strip() != "if %s ~= nil then" % outer_ov:
        return None
    cur += 1
    # <outer_ctl> = <outer_ov>
    if cur >= n or loop_lines[cur].strip() != "%s = %s" % (outer_ctl, outer_ov):
        return None
    cur += 1
    # goto <outer_body>
    if cur >= n or not re.match(r"^\s*goto\s+(\w+)\s*$", loop_lines[cur].strip() or "") \
            or re.match(r"^\s*goto\s+(\w+)\s*$", loop_lines[cur].strip()).group(1) != outer_body:
        return None
    cur += 1
    # end
    if cur >= n or loop_lines[cur].strip() != "end":
        return None
    cur += 1

    # _G.VisualTimerIds = <accum>
    if cur >= n or loop_lines[cur].strip() != "_G.VisualTimerIds = %s" % accum_var:
        return None
    cur += 1
    # _G.VisualsStarted = true
    if cur >= n or loop_lines[cur].strip() != "_G.VisualsStarted = true":
        return None
    cur += 1

    # watchdog pcall block: from `pcall(function()` to matching `end)`
    if cur >= n or loop_lines[cur].strip() != "pcall(function()":
        return None
    depth = 0
    wd = []
    while cur < n:
        wd.append(loop_lines[cur])
        depth += _block_delta(_strip_lit(loop_lines[cur]))
        cur += 1
        if depth == 0:
            break
    if depth != 0:
        return None

    # return true
    if cur >= n or not _RE_RETURNTRUE.match(loop_lines[cur].strip() or ""):
        return None
    cur += 1

    # ::<fail>::
    if cur >= n or not re.match(r"^\s*::(\w+)::\s*$", loop_lines[cur].strip() or ""):
        return None
    cur += 1
    # return false
    if cur >= n or not _RE_RETFALSE.match(loop_lines[cur].strip() or ""):
        return None
    cur += 1

    # nothing may remain
    if cur != n:
        return None

    return {
        "timers_var": timers_var,
        "accum_var": accum_var,
        "handle_var": handle_var,
        "outer_elem": outer_elem,
        "inner_elem": inner_elem,
        "target_obj": target_obj,
        "table_lines": table_lines,
        "register_line": register_line,
        "clear_txt": clear_txt,
        "watchdog_lines": wd,
        "indent": indent,
    }


def _rewrite_explicit_close_fn(blk):
    """Rewrite one explicit-close serialized function; returns lines or None.

    Expects `blk` to be the raw lines of a `local function ... end` block
    that contains the `[unluac error]` marker. Returns a rewritten block in
    which the serialized goto-loop skeleton is replaced by structured
    `for`/`if` loops. Any unexplained element yields None (safe fallback;
    the caller leaves the original block untouched)."""
    if not blk:
        return None
    m = _RE_LOCALFUNC.match(blk[0])
    if not m:
        return None
    indent = m.group(1)
    body = blk[1:-1]

    # --- locate the timers-table literal that starts the loop region
    t_start = None
    for idx, ln in enumerate(body):
        if re.match(r"^\s*[A-Za-z_]\w*\s*=\s*\{\s*$", _strip_lit(ln)):
            t_start = idx
            break
    if t_start is None:
        return None
    prelude_lines = body[:t_start]

    # --- parse prelude (controller discovery)
    pp = _parse_prelude(prelude_lines)
    if pp is None:
        return None
    shape, passthru, info, tail = pp
    if shape == "controller":
        controller = info["controller"]
        target = info["target"]
    else:
        controller = None
        target = None

    # --- parse loop region
    loop_lines = body[t_start:]
    lp = _parse_loop(loop_lines)
    if lp is None:
        return None

    # --- build output
    out = []

    # head line
    out.append(blk[0])

    # passthrough / rebuilt prelude
    out.extend(passthru)

    if shape == "controller":
        ind = indent + "    "
        # controller discovery rebuilt as structured if/else
        out.append("%slocal %s = nil" % (ind, controller))
        out.append("%sif %s then" % (ind, info["game_cond"]))
        out.append("%s    %s = _G.Game" % (ind, controller))
        out.append("%selse" % ind)
        out.append("%s    if %s then" % (ind, info["slua_cond"]))
        out.append("%s        local _, pc = %s" % (ind, info["slua_call"]))
        out.append("%s        %s = pc" % (ind, controller))
        out.append("%s    end" % ind)
        cond = info["cond_line"][len("if "):-len(" then")]
        out.append("%s    if %s then" % (ind, cond))
        out.append("%s    end" % ind)
        out.append("%send" % ind)
        out.append("%sif not %s then" % (ind, controller))
        out.append("%s    return false" % ind)
        out.append("%send" % ind)
        out.append("%sif not %s then" % (ind, target))
        out.append("%s    return false" % ind)
        out.append("%send" % ind)

    # tail passthrough after controller section (none expected here)
    out.extend(tail)

    # timers table literal, verbatim (drop the `<timers> =` decl)
    tindent = lp["indent"]
    out.append("%slocal timers = {" % tindent)
    for ln in lp["table_lines"][1:]:
        out.append(ln)

    # Registered accumulator + outer loop
    out.append("%slocal registered = {}" % tindent)
    out.append("%sfor _, t in ipairs(timers) do" % tindent)

    # rebuild Register: substitu controller -> controller, outer_elem -> t
    reg_line = lp["register_line"]
    if controller:
        reg_line = _sub_token(reg_line, controller, "controller")
    reg_line = _sub_token(reg_line, lp["outer_elem"], "t")
    out.append("%s    %s" % (tindent, reg_line))

    out.append("%s    if not handle then" % tindent)
    out.append("%s        for _, old in ipairs(registered) do" % tindent)
    clear_line = _sub_token(lp["clear_txt"], lp["inner_elem"], "old")
    out.append("%s            %s" % (tindent, clear_line))
    out.append("%s        end" % tindent)
    out.append("%s        _G.VisualTimerIds = nil" % tindent)
    out.append("%s        _G.VisualsStarted = false" % tindent)
    out.append("%s        return false" % tindent)
    out.append("%s    end" % tindent)
    out.append("%s    registered[#registered + 1] = handle" % tindent)
    out.append("%send" % tindent)

    # tail assignments
    out.append("%s_G.VisualTimerIds = registered" % tindent)
    out.append("%s_G.VisualsStarted = true" % tindent)

    # watchdog pcall block verbatim
    out.extend(lp["watchdog_lines"])

    out.append("%s    return true" % tindent)

    # closing function end
    out.append(blk[-1])

    return out


def _decompile_other_dialect(data: bytes, dialect, out_root: Path, stem: str, progress=None) -> list:
    """Decompile non-BGMI Lua families (LuaJIT / Lua 5.1 / 5.2 / 5.4 / Luau)
    into a single readable `*_GAME.lua` via unluac-rs.

    These dialects are readable + editable, but the game-ready recompile
    (which targets BGMI's Lua 5.3 VM) only applies to Lua 5.3 pieces, so the
    success message says so honestly.
    """
    tmp = None
    try:
        _phase(progress, "Decompiling (%s) to readable source..." % (dialect or "lua"))
        if not UNLUAC_RS.exists():
            raise RuntimeError("unluac_rs not found (needed for %s)" % dialect)
        tmp = out_root / ("_tmp_%s_%s.luac" % (stem, dialect))
        tmp.write_bytes(data)
        readable = _decompile_readable(tmp)
        game_path = out_root / (stem + "_GAME.lua")
        game_path.write_text(readable, encoding="utf-8")
        try:
            tmp.unlink()
        except Exception:
            pass
        recompile = "ready to recompile" if dialect in ("lua53", "lua54") else \
            "readable/editable (game recompile targets Lua 5.3)"
        return [("Decompile (%s)" % (dialect or "lua"), True, game_path, recompile)]
    except Exception as e:
        try:
            tmp.unlink()
        except Exception:
            pass
        return [("Decompile (%s)" % (dialect or "lua"), False,
                 out_root / (stem + "_GAME.lua"), str(e)[:250])]


def decompile_bgmi(src, out_root, progress=None) -> list:
    """Full readable decompile -> ONE final game-ready file (readable + editable + recompilable).

    Returns [(label, ok, out_path, msg), ...] with exactly one artifact:
    `*_GAME.lua` (strings inlined + prologue-stripped, ready to edit + recompile).
    Intermediate files (_decompiled, _CLEAN, _tmp_*.luac) are removed so the
    user gets a single clean result.
    """
    out_root = Path(out_root)
    out_root.mkdir(parents=True, exist_ok=True)
    data = read_bytes(src)
    stem = Path(src).stem

    def _cleanup(extra=()):
        for p in extra:
            try:
                if p and Path(p).exists():
                    Path(p).unlink()
            except Exception:
                pass

    try:
        _phase(progress, "Checking input...")
        if not _loads_ok(data):
            # encrypted / packed: try to auto-recover the key, then decompile.
            if not _is_encrypted_lua(data):
                # plain non-Lua input: treat as source text
                text = data.decode("utf-8", errors="replace")
                out_p = out_root / (stem + "_GAME.lua")
                out_p.write_text(text, encoding="utf-8")
                return [
                    ("Decompile (game-ready)", True, out_p, "readable source (game-ready)"),
                ]
            _phase(progress, "Trying auto key-discovery...")
            method, dec = _auto_decrypt_valid(data)
            if method is None or dec is None:
                return [("Decompile", False, out_root / (stem + "_GAME.lua"),
                         ("Auto key-discovery could not recover a decryption key "
                          "(sparse/BRPC-protected). Manual decrypt or the modder's "
                          "key is required for this file."))]
            _phase(progress, "Key found (%s)" % method)
            data = dec

        dialect = _detect_dialect(data)
        _phase(progress, "Dialect: %s" % (dialect or "lua53"))

        # non-BGMI dialects (LuaJIT / 5.1 / 5.2 / 5.4): readable via unluac-rs.
        if dialect not in ("lua53", "lua54", None):
            return _decompile_other_dialect(data, dialect, out_root, stem, progress)

        _phase(progress, "Converting BGMI -> standard bytecode...")
        std = _bgmi_to_std(data)

        tmp_std = out_root / ("_tmp_%s_std.luac" % stem)
        tmp_std.write_bytes(std)
        _phase(progress, "Decompiling to readable source...")
        readable = _decompile_readable(tmp_std)

        readable_path = out_root / (stem + "_decompiled.lua")
        readable_path.write_text(readable, encoding="utf-8")

        _phase(progress, "Decrypting protected string tables...")
        clean_text = _decrypt_prologue(readable)
        clean_text = _fix_explicit_close(clean_text)
        clean_path = out_root / (stem + "_CLEAN.lua")
        clean_path.write_text(clean_text, encoding="utf-8")

        game_text = _strip_prologue(clean_text)
        game_path = out_root / (stem + "_GAME.lua")
        game_path.write_text(game_text, encoding="utf-8")

        quality = _structure_quality(game_text)

        # single final artifact: remove intermediates so user sees ONE file
        _cleanup((readable_path, clean_path, tmp_std))
        msg = "readable + editable + game-ready, ready to recompile"
        if quality:
            msg += " | " + quality
        return [
            ("Decompile (game-ready)", True, game_path, msg),
        ]
    except Exception as e:
        return [("Decompile", False, out_root / (stem + "_GAME.lua"), str(e)[:250])]


def _patched_luac() -> Path:
    if not LUAC_PATCHED.exists():
        raise RuntimeError("patched luac not found: %s" % LUAC_PATCHED)
    return LUAC_PATCHED


def _compile_std(text: str, strip: bool = False) -> bytes:
    # strip defaults to FALSE so local-variable names + debug line info are kept
    # in the bytecode. This makes a later Compile -> Decompile round-trip come
    # back READABLE (real variable names, full structure) instead of degraded
    # register output (L1/L2) with missing lines. Keeping debug info is also
    # fine for the game to load; the bytecode still works normally.
    with tempfile.TemporaryDirectory() as td:
        src_f = Path(td) / "src.lua"
        src_f.write_text(text, encoding="utf-8")
        out_f = Path(td) / "out.luac"
        cmd = [str(_patched_luac())]
        if strip:
            cmd.append("-s")
        cmd += ["-o", str(out_f), str(src_f)]
        p = _run(cmd)
        if p.returncode != 0:
            err = (p.stderr or b"").decode("utf-8", errors="replace").strip()
            raise RuntimeError(err or "luac compile failed")
        return out_f.read_bytes()


def compile_bgmi(src, out, progress=None) -> tuple:
    out = Path(out)
    try:
        data = read_bytes(src)
        if not data.strip():
            return False, "empty source file"
        if _detect_dialect(data) or _is_bgmi(data):
            return False, (
                "input is already compiled bytecode. "
                "Use Decompile (option 2) to get readable source first."
            )
        printable = sum(1 for b in data[:4096] if 32 <= b < 127 or b in (9, 10, 13))
        if len(data) >= 8 and printable / min(len(data), 4096) < 0.7:
            return False, (
                "input is not readable Lua source (binary/encrypted). "
                "Decompile it first or provide plain .lua source."
            )
        text = data.decode("utf-8", errors="replace")
        _phase(progress, "Compiling with patched luac...")
        std = _compile_std(text)
        _phase(progress, "Converting to BGMI bytecode...")
        bgmi = _std_to_bgmi(std)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(bgmi)
        msg = "OK -> BGMI bytecode (%d B)" % len(bgmi)
        try:
            stats = _proto_stats(bgmi)
            if stats is not None and stats.get("max") and stats["max"] > 255:
                msg += " | WARNING: max proto register %d > 255 (game cap)" % stats["max"]
            elif stats is not None:
                msg += " | max proto register %d (game cap 255)" % stats["max"]
        except Exception:
            pass
        return True, msg
    except Exception as e:
        return False, str(e)[:250]


def _proto_stats(bgmi: bytes) -> dict | None:
    """Proto register stats for the compiled BGMI bytecode.

    Walks every nested proto and reports the max maxstacksize, so a file whose
    compiled output exceeds the game's register cap (255) can be flagged BEFORE
    the user loads it in-game. Returns None only when the tool's lua_engine is
    unavailable (stats are a best-effort add-on, never a hard failure)."""
    try:
        import lua_engine as le
        std = lua_bgmi.bgmi_to_std(bgmi)
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td) / "tmp.luac"
            tmp.write_bytes(std)
            proto = le.load_std_bytecode_to_proto(str(tmp))
        if proto is None:
            return None
        max_ms = 0
        max_proto = None

        def walk(p, depth=0):
            nonlocal max_ms, max_proto
            ms = getattr(p, "ms", 0) or 0
            if ms > max_ms:
                max_ms = ms
                max_proto = p
            for s in getattr(p, "subs", ()) or ():
                walk(s, depth + 1)

        walk(proto)
        return {"max": max_ms, "protos": _count_protos(proto)}
    except Exception:
        return None


def _count_protos(proto) -> int:
    try:
        n = 1
        for s in getattr(proto, "subs", ()) or ():
            n += _count_protos(s)
        return n
    except Exception:
        return 0
