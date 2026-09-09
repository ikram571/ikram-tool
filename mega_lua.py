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
import zlib
from pathlib import Path

_has_lua_protect = os.path.exists(str(Path(__file__).resolve().parent / "lua_protect.pyc"))

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


# ---------------------------------------------------------------------------
# Multi-section zlib container.  Some BGMI builds ship the bytecode as a pack
# of 64KiB raw-deflate sections (mostly the game's own archive format), not as
# a single flat .luac. Anything downstream that wants the real chunk must pull
# them through here first.
# ---------------------------------------------------------------------------
_ZLIB_SECTION_MAGIC2 = (0xDA, 0x9C, 0x01, 0x5E)


def _zlib_section_at(data: bytes, i: int):
    """Inflate one raw-deflate ('deflate', wbits=-15) section at offset `i`.

    Returns (next_offset_after_cargo, inflated_bytes) on success, else None.
    `next_offset` is computed from `unused_data`/`unconsumed_tail` so the
    caller can keep walking past trailing bytes/two-byte sync headers between
    sections.
    """
    if i + 2 > len(data):
        return None
    try:
        do = zlib.decompressobj(-15)
        rest = data[i + 2:]
        chunk = do.decompress(rest) + do.flush()
    except Exception:
        return None
    if len(chunk) < 4096:
        return None
    used = i + 2 + (len(rest) - len(do.unused_data) - len(do.unconsumed_tail))
    return used, chunk


def _reconstruct_zlib_sections(data: bytes):
    """Greedily concatenate every consecutive raw-deflate section.

    Walks 78xx magics (78 da / 78 9c / 78 01 / 78 5e), drops false positives,
    skips inter-section padding (0e / 00s / CLMM markers). Returns the joined
    reflate as bytes, or None when nothing section-like is present.
    """
    n = len(data)
    if n < 4096:
        return None
    parts = []
    i = 0
    guard = 0
    while i < n - 1:
        guard += 1
        if guard > len(data):
            break
        # find next plausible section magic within a window
        start = i
        while start < n - 1 and (
            data[start] != 0x78 or data[start + 1] not in _ZLIB_SECTION_MAGIC2
        ):
            start += 1
        if start >= n - 1:
            break
        r = _zlib_section_at(data, start)
        if r is None:
            i = start + 2
            continue
        next_off, chunk = r
        parts.append(chunk)
        i = next_off
    if not parts:
        return None
    total = b"".join(parts)
    if len(total) < 4096:
        return None
    return total


def _looks_like_zlib_container(data: bytes) -> bool:
    """Cheap pre-check: the file is NOT a plain Lua header and shows dense
    raw-deflate traffic (starts with a 78xx magic or heavy 0e padding).

    Deliberately skips anything that already carries a Lua-family header, so
    normal BGMI chunks (whose instruction streams can contain 0x78/0x0e bytes)
    are never fed to the section walker.
    """
    if len(data) < 4096:
        return False
    if data[:4] in (b"\x1bLua", b"\x1bLJ", b"\x1bul"):
        return False
    n = len(data)
    if data[0] == 0x78 and data[1] in _ZLIB_SECTION_MAGIC2:
        return True
    zero_run = 0
    for b in data[: max(4096, n // 64)]:
        if b == 0x0E:
            zero_run += 1
            if zero_run > 16:
                return True
        else:
            zero_run = 0
    return False


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
    # multi-section zlib container (BGMI archive form): reconstruct first
    if _looks_like_zlib_container(data):
        recon = _reconstruct_zlib_sections(data)
        if recon is not None:
            dia = _detect_dialect(recon)
            if dia in ("lua53", "lua54") or _is_bgmi(recon):
                return "Lua 5.3"
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
        if ver in (0x50, 0x51, 0x52, 0x53, 0x54):
            # Lua 5.1/5.2 have no LUAC_DATA magic tail (version byte + format
            # byte identify them); 5.3/5.4 require the \x19\x93\r\n\x1a\n tail.
            if ver in (0x50, 0x51, 0x52):
                if len(data) < 6 or data[5] != 0x00:
                    return None
                return "lua%d%d" % ((ver >> 4) & 0x0F, ver & 0x0F)
            if data[6:12] == LUA_MAGIC_TAIL:
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


def _add_key_recover(data: bytes, plain: bytes, key_len: int):
    """Repeating additive (mod-256) key from a known plaintext prefix:
    cipher = plain - key.  Same consistency contract as _xor_key_recover."""
    n = min(len(data), len(plain))
    if n < key_len:
        return None
    key = bytearray(key_len)
    for i in range(n):
        p = plain[i]
        c = data[i]
        slot = i % key_len
        k = (c - p) & 0xFF
        if i < key_len:
            key[slot] = k
        elif key[slot] != k:
            return None
    return bytes(key)


def _outer_variants(data: bytes):
    """Yield (label, candidate) slices that strip common wrapper junk:
    trailing zero-padding and a leading byte-prefix before the real Lua blob.

    Many protected game files carry the bytecode after a small header (an
    encryption key-string, a file version, offsets) or padded with zeros to
    block size.  Both are cheap to strip and are tried before any key search.
    """
    yield ("identity", data)
    end = len(data)
    while end > 0 and data[end - 1] == 0:
        end -= 1
    if end < len(data):
        yield ("trailing-zero-trim", data[:end])
    for i in range(min(512, len(data) - 3)):
        if data[i:i + 4] in (b"\x1bLua", b"\x1bLJ", b"\x1bul", b"LuaS"):
            if i > 0:
                yield ("prefix-%d-trim" % i, data[i:])
                if end < len(data):
                    yield ("prefix-%d+trailing-trim" % i, data[i:end])
            break


def _scramble_variants(data: bytes):
    """Yield (label, candidate) one-pass obfuscations that carry no key.

    Headerless scrambles used by lazy "encryptors": bit-invert, nibble-swap,
    even/odd byte-swap, add/subtract by position, and rolling (cumulative) XOR.
    The identity case is skipped by the caller (already tried first).
    """
    n = len(data)
    yield ("invert", bytes((~b) & 0xFF for b in data))
    yield ("nibble-swap", bytes((((b >> 4) | (b << 4)) & 0xFF) for b in data))
    sw = bytearray(n)
    m = n - (n & 1)
    sw[0:m:2] = data[1:m:2]
    sw[1:m:2] = data[0:m:2]
    if n & 1:
        sw[n - 1] = data[n - 1]
    yield ("byte-swap", bytes(sw))
    yield ("pos-add", bytes((b - i) & 0xFF for i, b in enumerate(data)))
    yield ("pos-sub", bytes((b + i) & 0xFF for i, b in enumerate(data)))
    diff = bytearray(n)
    prev = 0
    for i in range(n):
        diff[i] = data[i] ^ prev
        prev = data[i]
    yield ("rolling-xor", bytes(diff))


def _legacy_crypto():
    """Lazy handle to the legacy engine's cipher helpers (univ.pyc blob)."""
    global _LEGACY_CACHE
    if _LEGACY_CACHE is not None:
        return _LEGACY_CACHE
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "univ", str(Path(__file__).resolve().parent / "univ.py"))
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        _LEGACY_CACHE = getattr(m, "_legacy", None)
    except Exception:
        _LEGACY_CACHE = None
    return _LEGACY_CACHE


def _luajit_probe_header():
    """Header the local LuaJIT toolchain actually writes (cached).

    `luajit -b` emits a target-specific header (flags/size bytes differ
    between builds), so the key-sweep also tries exactly what THIS machine's
    compiler produces.  Covers files compiled by the tool/its users even when
    they diverge from the fixed LuaJIT templates above."""
    global _LJ_PROBE
    if _LJ_PROBE is not None:
        return _LJ_PROBE or None
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "_u", str(Path(__file__).resolve().parent / "univ.py"))
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        with tempfile.NamedTemporaryFile("w", suffix=".lua", delete=False) as f:
            f.write("_G._p = 1\n")
            srcp = f.name
        out = tempfile.mktemp(suffix=".ljprobe")
        try:
            r = m._compile_luajit(srcp, out)
            if r is None:
                head = Path(out).read_bytes()[:12]
                _LJ_PROBE = head if head[:3] == b"\x1bLJ" else False
        finally:
            for p in (srcp, out):
                try:
                    Path(p).unlink()
                except Exception:
                    pass
    except Exception:
        _LJ_PROBE = False
    return _LJ_PROBE or None


def _probe_headers(data: bytes) -> "_HEAD_TEMPLATES-like":
    """Base templates plus (cached) engine-specific LuaJIT header."""
    h = list(_HEAD_TEMPLATES)
    lj = _luajit_probe_header()
    if lj is not None and lj not in h:
        h.append(lj)
    return tuple(h)


def _auto_decrypt_valid(data: bytes):
    """Attempt to recover a key that turns `data` into valid Lua-family
    bytecode the pipeline can actually decompile.

    Returns (method_label, decrypted_bytes) on success, else (None, None).
    Tries, cheapest first:
      * already-valid Lua already present
      * the tool's own v3 loader (`-- IKRAMPROT`, recoverable only here)
      * outer wrapper slices (leading prefix, trailing zero padding)
      * keyless one-pass scrambles (invert, nibble, swap, positional, rolling)
      * repeating-key XOR / additive mod-256 across every Lua dialect for key
        lengths 1..64 (validated through the real converter / decompiler)
      * single-byte XOR brute (256)
      * legacy cipher sweeps: XXTEA over known candidate keys, wide fixed
        XOR keys

    Every candidate must pass _loads_ok, which for Lua 5.3/5.4 runs the real
    bytes->std converter and for other dialects an actual unluac-rs
    decompile.  A 13-byte header pasted onto a garbage body can therefore
    never be reported as a successful decryption.

    NOTE: for dialects other than 5.3/5.4 the key length equal to the header
    length is skipped: there the key is fully derived FROM the header itself
    and would "decrypt" any file into that dialect's magic with a garbage
    body (a guaranteed-but-meaningless match that the converter would not
    catch — Lua 5.3/5.4 are validated too strongly for this to matter).
    """
    if data is None or len(data) < 16:
        return (None, None)

    prot = _lua_protect_decrypt(data)
    if prot is not None:
        return prot

    if _loads_ok(data):
        return ("none (already valid)", data)

    for label, cand in _outer_variants(data):
        if cand is data:
            continue
        if _loads_ok(cand):
            return (label, cand)

    for label, cand in _scramble_variants(data):
        if _loads_ok(cand):
            return (label, cand)

    for header in _HEAD_TEMPLATES:
        plain_len = len(header)
        for L in range(1, 65):
            if L == plain_len and header is not LUA53_HEAD and header is not LUA54_HEAD:
                continue  # fully header-derived key => meaningless match
            key = _xor_key_recover(data, header, L)
            if key is not None:
                dec = bytes(data[i] ^ key[i % L] for i in range(len(data)))
                if _loads_ok(dec):
                    return ("XOR key len=%d %s" % (L, key.hex()), dec)
            key = _add_key_recover(data, header, L)
            if key is not None:
                dec = bytes((data[i] - key[i % L]) & 0xFF for i in range(len(data)))
                if _loads_ok(dec):
                    return ("ADD key len=%d %s" % (L, key.hex()), dec)

    for k in range(1, 256):
        dec = bytes(b ^ k for b in data)
        if _loads_ok(dec):
            return ("XOR single-byte 0x%02x" % k, dec)

    leg = _legacy_crypto()
    if leg is not None:
        for cand in getattr(leg, "_xor_decrypt_candidates")(data):
            if _loads_ok(cand):
                return ("legacy XOR sweep", cand)
        for tag, dec in getattr(leg, "_xxtea_key_candidates")(data, limit=8):
            if dec and _loads_ok(dec):
                return ("XXTEA %s" % tag, dec)
    return (None, None)


def _lua_protect_decrypt(data: bytes):
    """Decrypt a `.lua_protect` v3 loader if `data` is one.

    The loader is a text chunk starting `-- IKRAMPROT v3 protected chunk` with
    the bytecode stored as base64-encoded LCG-XOR blobs keyed by the bytecode
    hash.  Only the tool's own lua_protect module knows the key derivation, so
    this is the single recovery path for that format.

    Returns (method_label, decrypted_bytes) or None when not a loader / decrypt
    does not yield valid bytecode."""
    if not _has_lua_protect:
        return None
    if b"IKRAMPROT" not in data[:512] and b"-- IKRAMPROT" not in data[:512]:
        return None
    try:
        import importlib.util
        lp_spec = importlib.util.spec_from_file_location(
            "_lp", str(Path(__file__).resolve().parent / "lua_protect.pyc"))
        lp = importlib.util.module_from_spec(lp_spec)
        lp_spec.loader.exec_module(lp)
        with tempfile.NamedTemporaryFile(suffix=".lua", delete=False) as tf:
            tf.write(data)
            tmp_path = tf.name
        try:
            if not getattr(lp, "is_protected")(tmp_path):
                return None
            blobs = getattr(lp, "unprotect_blob")(tmp_path)
        finally:
            try:
                Path(tmp_path).unlink()
            except Exception:
                pass
        if not isinstance(blobs, dict):
            return None
        for version, blob in blobs.items():
            if isinstance(blob, (bytes, bytearray)) and _loads_ok(bytes(blob)):
                return ("lua_protect v3 (key %s)" % version, bytes(blob))
    except Exception:
        return None
    return None


LUA53_HEAD = b"\x1bLua\x53\x00" + LUA_MAGIC_TAIL + b"\x04\x04\x04\x08"
LUA53_STD_HEAD = b"\x1bLua\x53\x00" + LUA_MAGIC_TAIL + b"\x04\x08\x04\x08"
LUA54_HEAD = b"\x1bLua\x54\x00" + LUA_MAGIC_TAIL + b"\x04\x04\x04\x08"
LUALJ_HEAD = b"\x1bLJ\x02\x0a\x40\x02\x00\x07\x00\x03\x00\x08"
LUALJ1_HEAD = b"\x1bLJ\x01\x0a\x40\x02\x00\x07\x00\x03\x00\x08"
LUALJ3_HEAD = b"\x1bLJ\x03\x0a\x40\x02\x00\x07\x00\x03\x00\x08"
LUALJ_FR2_HEAD = b"\x1bLJ\x02\x0a\x20\x02\x00\x07\x00\x03\x00\x08"
LUA50_HEAD = b"\x1bLua\x50\x00\x01\x04\x08\x04\x08\x00"
LUA51_HEAD = b"\x1bLua\x51\x00\x01\x04\x08\x04\x08\x00"
LUA52_HEAD = b"\x1bLua\x52\x00\x01\x04\x08\x04\x08\x00"
LUAU_HEAD = b"\x1bulu\x41\x00\x01\x00\x02\x02\x00\x00\x01\x00\x00\x00\x01\x00\x00\x00"
_HEAD_TEMPLATES = (
    LUA53_HEAD, LUA53_STD_HEAD, LUA54_HEAD, LUA51_HEAD, LUA52_HEAD, LUA50_HEAD,
    LUALJ_HEAD, LUALJ1_HEAD, LUALJ3_HEAD, LUALJ_FR2_HEAD, LUAU_HEAD,
)
_LEGACY_CACHE = None


def _std_has_payload(std: bytes) -> bool:
    """True when a standard-chunk `std` parses to a proto tree with at least
    one real code instruction. A Lua header pasted onto a garbage body
    converts to a length-nonzero lump with zero instructions; real BGMI
    converts to a tree with >0 instructions even when the chunk is too large
    for unluac-rs to fully decompile."""
    try:
        import lua_engine as _le
        tmp = None
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td) / "payload_check.luac"
            tmp.write_bytes(std)
            p = _le.load_std_bytecode_to_proto(str(tmp))
            total = 0
            stack = [p]
            while stack:
                cur = stack.pop()
                ins = getattr(cur, "ins", None)
                if ins:
                    total += len(ins)
                subs = getattr(cur, "subs", None)
                if subs:
                    stack.extend(subs)
        return total > 0
    except Exception:
        return False


def _loads_ok(data: bytes) -> bool:
    """True only if `data` is genuine, decompilable Lua-family bytecode.

    Strict: Lua 5.3/5.4 (BGMI) is validated through the real bytes->std
    converter; other dialects (Lua 5.0/5.1/5.2, LuaJIT) are validated by
    actually decompiling them with unluac-rs, so a coincidental LuaJIT header
    pasted onto a garbage body (a false positive from key search) is rejected
    instead of being reported as a successful decryption.

    A standard-headered (non-BGMI) Lua 5.3 chunk is NOT game format, so it
    falls through to the same real-decompile check as the other dialects.
    """
    if not data or len(data) < 16:
        return False
    if _looks_like_zlib_container(data):
        recon = _reconstruct_zlib_sections(data)
        if recon is not None:
            data = recon
    dia = _detect_dialect(data)
    if dia in ("lua50", "lua51", "lua52", "luajit"):
        return _unluac_probe(data)
    if dia in ("lua53", "lua54"):
        try:
            std = _bgmi_to_std(data)
        except Exception:
            std = b""
        if len(std) > 0 and _std_has_payload(std):
            return True
        if len(std) > 0:
            # converted lump has no real code: header-pasted garbage. Reject
            # unless a real decompile still succeeds on the source chunk.
            return _unluac_probe(data)
        return _unluac_probe(data)
    return False


def _unluac_probe(data: bytes) -> bool:
    """Validate a (non-BGMI) chunk by an actual unluac-rs decompile."""
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


def _is_flat_lvar(text: str) -> bool:
    """True when `text` is the broken flat `L0_1/L1_1` register decompile.

    unluac.jar has no source names for name-stripped bytecode and falls back
    to a dense flat register dump (`L0_1 = type`, `L0_1 = L0_1(L1_1)`,
    `goto lbl_11`). That output keeps NO real structure/tables and is not
    editable or game-ready. unluac-rs handles the same bytecode as clean
    structured `r0_0` code. We detect the flat signature so the jar result
    can be rejected in favor of the structured engine.
    """
    if not text.strip():
        return False
    luadec = len(_LUADEC_LOCAL_RE.findall(text))
    unluac = len(_UNLUAC_LOCAL_RE.findall(text))
    # Dense L-vars with no readable register (r) locals => flat junk.
    if luadec >= 50 and unluac == 0:
        return True
    builder_tail = bool(re.search(r"return\s+L\d+_\d+\s*\(", text))
    if luadec > 8 and builder_tail:
        return True
    return False


def _decompile_readable(std_path: Path) -> str:
    """Choose the best readable decompile for `std_path`.

    Order of preference:
      1. unluac.jar ONLY when it keeps source names (not a flat L-var dump).
      2. unluac-rs (fast, structured register-style r0_0 names, keeps game
         tables/.RPC bindings -> editable + game-ready).
      3. lua_engine internal decompiler (guaranteed readable).

    For name-stripped bytecode unluac.jar degrades to a flat `L0_1/L1_1`
    register dump (dense L-vars, no structure) where unluac-rs produces clean
    structured code, so a flat jar result is rejected in favor of unluac-rs.
    The lua_engine fallback runs even when java/jar are missing so a BGMI
    file can NEVER end up as a hard "decompile failed".
    """
    jar_out = None
    rs_out = None
    if UNLUAC_JAR.exists():
        p = _run(["java", "-jar", str(UNLUAC_JAR), str(std_path)])
        if p.returncode == 0 and p.stdout.strip():
            jar_out = p.stdout.decode("utf-8", errors="replace")
    if UNLUAC_RS.exists():
        p = _run([str(UNLUAC_RS), "-i", str(std_path)])
        if p.returncode == 0 and p.stdout.strip():
            rs_out = p.stdout.decode("utf-8", errors="replace")
        rs_err = (p.stderr or b"").decode("utf-8", errors="replace")
    else:
        rs_err = "unluac_rs not found"

    # unluac.jar only wins when it is NOT a flat L-var dump (it keeps names).
    if jar_out and jar_out.strip() and not _is_flat_lvar(jar_out):
        return jar_out
    # otherwise prefer the structured unluac-rs output when available.
    if rs_out and rs_out.strip():
        return rs_out
    if jar_out and jar_out.strip():
        return jar_out

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


# ---- readable-promotion pass --------------------------------------------
# Name-stripped BGMI bytecode decompiles to unique-per-proto register names
# (`r0_52`, `p2_0`).  The values are correct and game-ready, but dense.  This
# pass re-introduces real identifiers where the structure guarantees them:
#   * import("GameApi") aliases  -> the import string IS the API name
#   * `_ENV._G.MyGlobal = r0_60` + `local function r0_60` -> name the function
#   * single-use `local r0_N = _G.Foo` / `_ENV.X` aliases -> inline the use
# Every rename is re-verified by a luac syntax pass; if anything fails the
# original text is returned untouched (decompile never regresses).

_IMPORT_RE = re.compile(r'^\s*local\s+(r\d+_\d+)\s*=\s*(_ENV\.)?(slua_)?(import)\("([A-Za-z_][A-Za-z0-9_]*)"\)')
_GLOBAL_FN_RE = re.compile(r"^\s*_ENV\._G\.([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(r\d+_\d+)")
_LOCAL_FN_RE = re.compile(r"^\s*local\s+function\s+(r\d+_\d+)\b")
_ANY_IDENT_RE = re.compile(r"\b([A-Za-z_]\w*)\b")


def _code_mask(text: str) -> str:
    """Blank out string literals + comments so identifier searches don't
    match inside strings/import names."""
    s = re.sub(r"--[^\n]*", "", text)
    s = re.sub(r'"(?:\\.|[^"\\])*"', '""', s, flags=re.S)
    s = re.sub(r"'(?:\\.|[^'\\])*'", "''", s, flags=re.S)
    return s


def _is_lvalue_use(line: str, reg: str) -> bool:
    """True when `reg` is used as an assignment TARGET on `line`.

    Parenthesized lvalue bases trip the game's patched luac parser
    (`(a.b)[k] = v` after certain locals is refused), so a single-use alias
    must not be inlined when its one use is an lvalue."""
    i = re.search(r"\b%s\b" % re.escape(reg), line)
    if not i:
        return False
    rest = line[i.end():]
    # consume a `.name` / `['str']` / `[expr]` indexing chain if present
    while True:
        m = re.match(r"\.\s*[A-Za-z_]\w*", rest)
        if m:
            rest = rest[m.end():]
            continue
        m = re.match(r"\[", rest)
        if not m:
            break
        depth = 1
        j = 1
        while j < len(rest) and depth:
            if rest[j] == "[": depth += 1
            elif rest[j] == "]": depth -= 1
            j += 1
        rest = rest[j:]
        continue
    return rest.lstrip()[:1] in ("=", "")


def _clean_output(text: str) -> str:
    """Minimise decompiler junk without changing program meaning.

    * drops `local rN_M = <expr>` declarations that are never referenced
      again (spilled-but-unused registers are pure noise)
    * collapses blank-line runs and trims leading/trailing blank lines
    Returns the original text when the result does not re-verify cleanly.
    """
    lines = text.splitlines()
    if not lines:
        return text
    masked = [_code_mask(l) for l in lines]
    decl_re = re.compile(r"^\s*local\s+(r\d+_\d+)\s*=\s*(.+?)\s*$")
    regs = {}
    for i, ln in enumerate(lines):
        m = decl_re.match(ln)
        if m:
            regs[m.group(1)] = i
    if regs:
        scan = re.compile(r"\b(%s)\b" % "|".join(sorted(
            (re.escape(r) for r in regs), key=len, reverse=True)))
        occs = {}
        for j, ml in enumerate(masked):
            for r in scan.findall(ml):
                occs.setdefault(r, []).append(j)
        dead = {i for r, i in regs.items() if len(occs.get(r, ())) == 1}
        if dead:
            lines = [l for i, l in enumerate(lines) if i not in dead]
    out = []
    prev_blank = False
    for l in lines:
        blank = not l.strip()
        if blank and prev_blank:
            continue
        out.append(l)
        prev_blank = blank
    while out and not out[0].strip():
        out.pop(0)
    while out and not out[-1].strip():
        out.pop()
    cleaned = "\n".join(out)
    if text.endswith("\n") and not cleaned.endswith("\n"):
        cleaned += "\n"
    if cleaned == text:
        return text
    try:
        _compile_std(cleaned)
        return cleaned
    except Exception:
        return text


def _promote_readable(text: str) -> str:
    """Post-process register-style decompiled text into readable names."""
    if not _UNLUAC_LOCAL_RE.search(text):
        return text
    masked = _code_mask(text)
    existing = set(_ANY_IDENT_RE.findall(masked))
    lines = text.splitlines()
    renames = {}          # register -> readable name
    inline_targets = []   # (register, rhs) to inline single-use aliases

    for i, ln in enumerate(lines):
        m = _IMPORT_RE.match(ln)
        if m:
            reg, name = m.group(1), m.group(5)
            if name not in existing:          # API name not already in scope
                renames[reg] = name
                existing.add(name)
            continue
        m = _GLOBAL_FN_RE.match(ln)
        if m:
            gname, reg = m.group(1), m.group(2)
            # `_ENV._G.Valid` IS the intended name; it is safe to reuse.
            # The register must be a `local function` declared before it and
            # must not be re-assigned anywhere after declaration.
            has_fn = re.search(r"^\s*local\s+function\s+%s\b" % re.escape(reg),
                               text, re.M)
            if has_fn and not re.search(
                    r"^\s*%s\s*=\s*(?!local\s+function)" % re.escape(reg),
                    text, re.M):
                renames[reg] = gname
                existing.add(gname)

    # single-use alias inlining for _G / _ENV field aliases and enums:
    # `local rN_M = <simple expr>` used exactly once after its declaration.
    masked_lines = [_code_mask(l) for l in lines]
    occs: dict = {}
    regs = {m.group(1) for i, ln in enumerate(lines) if
            (m := re.match(r"^\s*local\s+(r\d+_\d+)\s*=\s*(.+)$", ln))}
    if regs:
        scan = re.compile(r"\b(%s)\b" % "|".join(sorted(
            (re.escape(r) for r in regs), key=len, reverse=True)))
        for j, ml in enumerate(masked_lines):
            for r in scan.findall(ml):
                occs.setdefault(r, []).append(j)
    for i, ln in enumerate(lines):
        m = re.match(r"^\s*local\s+(r\d+_\d+)\s*=\s*(.+)$", ln)
        if not m:
            continue
        reg = m.group(1)
        if reg in renames:
            continue
        occ = occs.get(reg, [])
        if len(occ) != 2:                    # decl line + exactly one use
            continue
        rhs = m.group(2).rstrip()
        # only inline simple field / _G / _ENV / literal access (no calls)
        if not re.match(r"^(?:\(.*\)|[A-Za-z_]\w*(?:\.\w+)*)$", rhs) \
                and not rhs.lstrip("(").rstrip(")").isdecimal():
            continue
        # the single use is the other occurrence (the decl is `i`).
        use_line = next(j for j in occ if j != i)
        # safe: a dotted path inlines into any position; a bare literal is
        # fine in rvalue position only (never as an assignment target).
        is_path = bool(re.match(r"^[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+$", rhs))
        if not is_path and _is_lvalue_use(lines[use_line], reg):
            continue
        inline_targets.append((reg, rhs, i, use_line))

    if not renames and not inline_targets:
        return text

    out_lines = list(lines)
    # apply imports / global-function renames (word-boundary, whole file)
    if renames:
        pat = re.compile(r"\b(%s)\b" % "|".join(map(re.escape, renames)))
        for i, ln in enumerate(out_lines):
            if i % 9 == 0:                    # cheap incremental mask is fine
                pass
            out_lines[i] = pat.sub(lambda m: renames[m.group(1)], ln)

    # inline single-use aliases: drop decl line, splice RHS at the one use.
    if inline_targets:
        masked_lines = [_code_mask(l) for l in out_lines]
        for reg, rhs, decl_i, use_line in inline_targets:
            if not (0 <= decl_i < len(out_lines)) or not (
                    0 <= use_line < len(out_lines)):
                continue
            if not re.search(r"\b%s\b" % re.escape(reg),
                             masked_lines[use_line]):
                continue
            out_lines[decl_i] = None
            out_lines[use_line] = re.sub(
                r"\b%s\b" % re.escape(reg), rhs,
                out_lines[use_line], count=1)
            masked_lines[use_line] = _code_mask(out_lines[use_line])
        out_lines = [l for l in out_lines if l is not None]

    promoted = "\n".join(out_lines)
    # verify the promotion preserves valid syntax; fall back on any doubt.
    try:
        _compile_std(promoted)
        return promoted
    except Exception:
        return text


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
# signature of the tool's own lua_engine pseudo-decompiler fallback
# (register-style `R0/R1`, `-- SETLIST A=..`, unresolvable `goto line_NNN`):
# such output is readable but not guaranteed recompilable on heavy files.
_PSEUDO_SIGN_RE = re.compile(r"^\s*local\s+R\d+\s*=\s*\{\s*\}$", re.M)


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

    if _looks_like_zlib_container(data):
        _phase(progress, "Multi-section container detected, reconstructing...")
        recon = _reconstruct_zlib_sections(data)
        if recon is not None and (_detect_dialect(recon) or _is_bgmi(recon)):
            data = recon

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
            # the tool's own v3 protected-loader (printable text) must be
            # decrypted BEFORE the "plain source text" fallback.
            prot = _lua_protect_decrypt(data)
            if prot is not None:
                method, data = prot
                _phase(progress, "Key found (%s)" % method)
            elif not _is_encrypted_lua(data):
                # Only genuinely text-only input is plain source. Lua-family
                # bytecode (recognised dialect) that fails the real decompile
                # must NOT be dumped raw as if it were readable source --
                # report it honestly instead of faking a success.
                dia = _detect_dialect(data)
                if dia is not None:
                    return [("Decompile", False, out_root / (stem + "_GAME.lua"),
                             ("This is %s Lua bytecode, but the decompiler "
                              "could not parse it (incomplete/truncated or "
                              "custom-protected format). No readable source "
                              "was produced.") % (dia.upper()))]
                # Plain unsignatured text (no Lua header): treat as source.
                text = data.decode("utf-8", errors="replace")
                out_p = out_root / (stem + "_GAME.lua")
                out_p.write_text(text, encoding="utf-8")
                return [
                    ("Decompile (game-ready)", True, out_p, "readable source (game-ready)"),
                ]
            else:
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

        # non-BGMI dialects (LuaJIT / 5.1 / 5.2 / 5.4) AND standard
        # size_t=8 chunks of otherwise-BGMI versions: readable via unluac-rs.
        if dialect not in ("lua53", "lua54", None):
            return _decompile_other_dialect(data, dialect, out_root, stem, progress)
        if dialect in ("lua53", "lua54") and not _is_bgmi(data):
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
        # name-stripped register output -> re-introduce readable identifiers
        if _UNLUAC_LOCAL_RE.search(game_text):
            _phase(progress, "Cleaning dead registers...")
            game_text = _clean_output(game_text)
            _phase(progress, "Promoting readable names...")
            game_text = _promote_readable(game_text)
        game_path = out_root / (stem + "_GAME.lua")
        game_path.write_text(game_text, encoding="utf-8")

        quality = _structure_quality(game_text)

        # single final artifact: remove intermediates so user sees ONE file
        _cleanup((readable_path, clean_path, tmp_std))
        if _PSEUDO_SIGN_RE.search(game_text):
            msg = ("readable register-style (engine fallback); may lose "
                   "structure / not recompile cleanly on heavy files")
            if quality:
                msg += " | " + quality
        else:
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
