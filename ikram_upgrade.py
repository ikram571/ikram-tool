# ikram_upgrade.py - Ikram Tool V114 compile-pipeline protection (backend only)
#
# Pipeline contract (locked with spec v2 / QX-CYBER-404 review):
#   luac_patched -> register check (on ORIGINAL std, pre-inflation)
#                 -> STAGE 1: junk-proto inflation (top-level protos[] only)
#                 -> lua_bgmi  (UNCHANGED format converter)
#                 -> STAGE 3: IKRM wrapper (HKDF-SHA256 rotating XOR + checksum)
#
# lua_bgmi is a FORMAT CONVERTER (parses bytecode, re-emits game format).
# Encryption therefore runs AFTER conversion; the game-side loader strips the
# IKRM wrapper before feeding the plaintext BGMI to its existing loader path.
#
# Target format (Lua 5.1 dump, what luac_patched emits): exact parser below.
# Runtime: Termux (aarch64 Android), CPython 3.11. Stdlib only.

import hashlib
import hmac
import importlib.util
import os
import random
import struct
import subprocess
import tempfile
from pathlib import Path

TOOL_DIR = Path(__file__).resolve().parent
LUAC = TOOL_DIR / "luac_patched"
BGMI_PYC = TOOL_DIR / "lua_bgmi.pyc"
LUA_ENGINE = TOOL_DIR / "lua_engine.py"

MAGIC = b"IKRM"
VERSION = 0x01
HEADER_SIZE = 4 + 1 + 4 + 32          # MAGIC + VERSION + ORIG_SIZE + KEY_SEED
MIN_BYTES = 2_000_000                 # spec v2: 2-4MB (mobile load-time friendly)
MAX_BYTES = 4_000_000
HKDF_INFO = b"IKRM-v1"
HKDF_LEN = 64
ENV_OFF = "IKRM_PROTECT"

# ---- Lua 5.1 dump primitives ------------------------------------------------

def _luac_compile(text: str, strip: bool = True) -> bytes:
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        src = d / "src.lua"
        out = d / "out.luac"
        src.write_text(text, encoding="utf-8")
        args = [str(LUAC)]
        if strip:
            args.append("-s")
        args += ["-o", str(out), str(src)]
        timeout = 60 + len(text) // 300_000
        try:
            p = subprocess.run(args, capture_output=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            raise RuntimeError("junk compile timed out")
        if p.returncode != 0:
            err = (p.stderr or b"").decode("utf-8", errors="replace").strip()
            raise RuntimeError("junk compile failed: %s" % err)
        return out.read_bytes()


def _rd_str(b: bytes, o: int, sizet: int) -> tuple:
    """Lua 5.1 dump string: 1-byte length (content+1), 0=null, 255=escape."""
    first = b[o]
    o += 1
    if first == 0:
        return None, o
    if first == 255:
        sz = struct.unpack_from("<Q" if sizet == 8 else "<I", b, o)[0]
        o += sizet
    else:
        sz = first
    if sz == 0:
        return None, o
    return b[o : o + sz - 1], o + sz - 1


def _skip_const(b: bytes, o: int, sizet: int) -> int:
    tag = b[o]
    o += 1
    if tag == 1:
        o += 1
    elif tag in (3, 19):
        o += 8
    elif tag in (4, 20):
        _, o = _rd_str(b, o, sizet)
    return o


def _parse_func(b: bytes, o: int, end: int, sizet: int) -> int:
    """Parse one proto, return offset just past its debug section."""
    _, o = _rd_str(b, o, sizet)
    o += 8                                    # linedefined, lastlinedefined
    o += 3                                    # numparams, is_vararg, maxstacksize
    csz = struct.unpack_from("<I", b, o)[0]
    o += 4 + csz * 4                          # sizecode + code[]
    nk = struct.unpack_from("<I", b, o)[0]
    o += 4
    for _ in range(nk):
        o = _skip_const(b, o, sizet)
    nups = struct.unpack_from("<I", b, o)[0]
    o += 4 + nups * 2
    npts = struct.unpack_from("<I", b, o)[0]
    o += 4
    for _ in range(npts):
        o = _parse_func(b, o, end, sizet)
    nln = struct.unpack_from("<I", b, o)[0]
    o += 4 + nln * 4
    nloc = struct.unpack_from("<I", b, o)[0]
    o += 4
    for _ in range(nloc):
        _, o = _rd_str(b, o, sizet)
        o += 8
    nupn = struct.unpack_from("<I", b, o)[0]
    o += 4
    for _ in range(nupn):
        _, o = _rd_str(b, o, sizet)
    return o


def _child_regions(data: bytes, sizet: int) -> tuple:
    """Top-level proto's code header + child (protos[]) regions."""
    o = 34                                    # HEADER(33) + signature byte
    _, o = _rd_str(data, o, sizet)
    o += 8
    o += 3
    csz = struct.unpack_from("<I", data, o)[0]
    o += 4 + csz * 4
    nk = struct.unpack_from("<I", data, o)[0]
    o += 4
    for _ in range(nk):
        o = _skip_const(data, o, sizet)
    nups = struct.unpack_from("<I", data, o)[0]
    o += 4 + nups * 2
    npts_off = o
    npts = struct.unpack_from("<I", data, o)[0]
    off = o + 4
    regions = []
    for _ in range(npts):
        s = off
        off = _parse_func(data, off, len(data), sizet)
        regions.append((s, off))
    return npts_off, npts, regions


# ---- Junk proto generation (compiler-produced = guaranteed valid 5.1) -------

def _make_lit(parts) -> str:
    out = []
    for p in parts:
        cur = []
        for x in p:
            if 0x20 <= x < 0x7F and x not in (34, 92):
                cur.append(chr(x))
            elif x in (34, 92):
                cur.append("\\%c" % x)
            else:
                cur.append("\\%03d" % x)
        out.append('"%s"' % "".join(cur))
    return " .. ".join(out) or '""'


def _gen_junk_source(names: list, cover_bytes: int) -> str:
    rng = random.Random(os.urandom(16))
    cover = os.urandom(max(1, cover_bytes))
    parts = [cover[i : i + 8192] for i in range(0, len(cover), 8192)]
    src = ["-- ikram dead proto block %s" % rng.randbytes(4).hex()]
    for idx, name in enumerate(names):
        lit = _make_lit(parts[idx:: len(names)]) if parts else '""'
        src.append(
            "local function %s()\n"
            "  local _a = %d\n"
            "  local _b = %.17g\n"
            "  local _s = %s\n"
            "  if false and _s then\n"
            "    _a = #_s\n"
            "  end\n"
            "  return _a + _b\n"
            "end\n" % (name, idx + 1, (idx + 1) * 1.25, lit)
        )
    return "\n".join(src)


def _junk_blobs(target_bytes: int, rng: random.Random) -> list:
    """Compile dead top-level children in ≤800-func batches (5.1 cap: 1000
    locals in one main proto) and collect every child function blob."""
    n = max(8, min(2000, target_bytes // 1500))
    per_batch = 800
    blobs = []
    made = 0
    while made < n:
        batch_n = min(per_batch, n - made)
        names = ["ikr%d_%s" % (made + i, rng.randbytes(4).hex())
                 for i in range(batch_n)]
        share = max(1, target_bytes // max(1, (n + per_batch - 1) // per_batch))
        src = _gen_junk_source(names, share)
        chunk = _luac_compile(src, strip=True)
        sizet = chunk[13] if chunk[13] in (4, 8) else 4
        _, _, regions = _child_regions(chunk, sizet)
        blobs.extend(chunk[s:e] for s, e in regions)
        made += batch_n
    return blobs


def _splice_children(std: bytes, blobs: list, sizet: int) -> bytes:
    """Append junk blobs into the TOP-LEVEL protos[] array only.

    Top-level sizecode / code[] / constant table are byte-identical; only the
    protos[] count and the child region grow. Core logic executes first,
    untouched.
    """
    npts_off, npts, regions = _child_regions(std, sizet)
    orig_start = regions[0][0] if regions else npts_off + 4
    debug_off = regions[-1][1] if regions else orig_start
    head = std[:npts_off]
    tail = std[debug_off:]
    return (
        head
        + struct.pack("<I", npts + len(blobs))
        + std[orig_start:debug_off]
        + b"".join(blobs)
        + tail
    )


# ---- STAGE 1: inflation ------------------------------------------------------

def stage1_inflate(std: bytes, min_bytes: int = MIN_BYTES,
                   max_bytes: int = MAX_BYTES) -> bytes:
    """Append randomized dead protos to the top-level protos[] array."""
    if max_bytes <= len(std):
        return std
    sizet = std[13] if std[13] in (4, 8) else 4
    if std[:4] != b"\x1bLua":
        raise ValueError("stage1: not a luac_patched (5.1) chunk")
    rng = random.Random(os.urandom(16))
    target = min(
        max_bytes,
        max(min_bytes, len(std) + (max_bytes - len(std)) // 2),
    )
    blobs = _junk_blobs(target - len(std), rng)
    return _splice_children(std, blobs, sizet)


# ---- STAGE 3: IKRM wrapper --------------------------------------------------

def _hkdf(key: bytes, info: bytes, length: int) -> bytes:
    """HKDF-SHA256 (extract+expand, RFC 5869), stdlib hmac/hashlib only."""
    hlen = hashlib.sha256().digest_size
    prk = hmac.new(b"\x00" * hlen, key, hashlib.sha256).digest()
    t = b""
    okm = b""
    counter = 1
    while len(okm) < length:
        t = hmac.new(prk, t + info + bytes([counter]), hashlib.sha256).digest()
        okm += t
        counter += 1
    return okm[:length]


def _xor_rotating(key_material: bytes, payload: bytes) -> bytes:
    k = key_material
    return bytes(p ^ k[i % len(k)] for i, p in enumerate(payload))


def stage3_wrap(bgmi: bytes) -> bytes:
    """Final file: [MAGIC][VERSION][ORIG_SIZE][KEY_SEED][XOR payload][SHA256]."""
    seed = os.urandom(32)
    key_material = _hkdf(seed, HKDF_INFO, HKDF_LEN)
    enc = _xor_rotating(key_material, bgmi)
    checksum = hashlib.sha256(bgmi).digest()
    return MAGIC + bytes([VERSION]) + struct.pack("<I", len(bgmi)) + seed + enc + checksum


def is_protected(data: bytes) -> bool:
    """True when `data` carries a valid IKRM wrapper header."""
    return len(data) >= HEADER_SIZE + 32 and data[:4] == MAGIC and data[4] == VERSION


def try_unwrap(data: bytes, hkdf_length: int = HKDF_LEN):
    """Decrypt an IKRM-wrapped blob, or return None when not IKRM/corrupt.

    Safe entry point for the tool's own loaders (Decompile, pipeline,
    detect): never raises on foreign input.
    """
    if not is_protected(data):
        return None
    try:
        return stage3_unwrap(data, hkdf_length)
    except Exception:
        return None


def stage3_unwrap(data: bytes, hkdf_length: int = HKDF_LEN) -> bytes:
    """Reference decryptor (game-side loader uses this exact logic)."""
    if data[:4] != MAGIC:
        raise ValueError("not an IKRM file")
    version = data[4]
    if version != VERSION:
        raise ValueError("unsupported IKRM version %d" % version)
    orig_size = struct.unpack_from("<I", data, 5)[0]
    seed = data[9:41]
    body = data[41:]
    enc = body[:-32]
    checksum = body[-32:]
    key_material = _hkdf(seed, HKDF_INFO, hkdf_length)
    plain = _xor_rotating(key_material, enc)
    if len(plain) != orig_size:
        raise ValueError("IKRM size mismatch")
    if hashlib.sha256(plain).digest() != checksum:
        raise ValueError("IKRM checksum mismatch")
    return plain


# ---- lua_bgmi / lua_engine loads ---------------------------------------------

def _load_bgmi():
    if not BGMI_PYC.exists():
        raise RuntimeError("lua_bgmi.pyc not found")
    spec = importlib.util.spec_from_file_location("_ikram_lua_bgmi", BGMI_PYC)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def std_to_bgmi(std: bytes) -> bytes:
    return _load_bgmi().std_to_bgmi(std)


def bgmi_to_std(bgmi: bytes) -> bytes:
    return _load_bgmi().bgmi_to_std(bgmi)


# ---- register check on ORIGINAL std (spec Definition E) ----------------------

def register_stats(std: bytes) -> dict | None:
    """Max maxstacksize over every proto in the raw luac_patched output.

    Runs BEFORE inflation/encryption; junk protos never influence the check.
    Returns None when lua_engine is unavailable (best-effort, never fatal).
    """
    try:
        import lua_engine as le
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td) / "tmp.luac"
            tmp.write_bytes(std)
            proto = le.load_std_bytecode_to_proto(str(tmp))
        if proto is None:
            return None
    except Exception:
        return None

    max_ms = 0
    max_proto = None
    n_protos = 1

    def walk(p):
        nonlocal max_ms, max_proto, n_protos
        ms = getattr(p, "ms", 0) or 0
        if ms > max_ms:
            max_ms = ms
            max_proto = p
        for s in getattr(p, "subs", ()) or ():
            n_protos += 1
            walk(s)

    walk(proto)
    return {"max": max_ms, "max_proto": max_proto, "protos": n_protos}


# ---- gate ---------------------------------------------------------------------

def enabled() -> bool:
    return not (ENV_OFF in os.environ and os.environ[ENV_OFF] == "0")


# ---- standalone entry point ---------------------------------------------------

def compile_upgraded(source_path: str, output_path: str) -> None:
    """Full protected pipeline: luac -> register check -> inflate -> convert
    -> wrap. The tool's UI path calls stage1_inflate/stage3_wrap directly;
    this entry point is for standalone runs (spec deliverable #1)."""
    src = Path(source_path)
    if not src.exists():
        raise FileNotFoundError(source_path)
    text = src.read_text(encoding="utf-8", errors="replace")
    std = _luac_compile(text, strip=False)
    register_stats(std)                       # Definition E
    inflated = stage1_inflate(std)
    bgmi = std_to_bgmi(inflated)
    final = stage3_wrap(bgmi)
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_bytes(final)


def decrypt_reference(data: bytes) -> bytes:
    return stage3_unwrap(data)