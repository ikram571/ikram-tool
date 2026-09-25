import hashlib
import os
import random
import struct
import subprocess
import tempfile
from pathlib import Path

_TOOL_DIR = Path(__file__).resolve().parent
_LUAC = _TOOL_DIR / "luac_patched"

HEADER_SIZE = 33
MAGIC = b"IKRM"
VERSION = 1
XOR_BLOCK = 64
MIN_BYTES = 10_000_000
MAX_BYTES = 20_000_000
HEAD_BYTES = 4 + 1 + 4 + 32

ENV_OFF = "IKRM_PROTECT"


def _luac(text: str) -> bytes:
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        src = d / "src.lua"
        out = d / "out.luac"
        src.write_text(text, encoding="utf-8")
        timeout = 60 + len(text) // 300_000
        try:
            p = subprocess.run(
                [str(_LUAC), "-o", str(out), str(src)],
                capture_output=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError("junk compile timed out")
        if p.returncode != 0:
            err = (p.stderr or b"").decode("utf-8", errors="replace").strip()
            raise RuntimeError("junk compile failed: %s" % err)
        return out.read_bytes()


def _rd_str(b: bytes, o: int, sizet: int):
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
    _, o = _rd_str(b, o, sizet)
    if o + 8 + 3 > len(b):
        raise ValueError("bad std func")
    _, o = struct.unpack_from("<i", b, o)[0], o + 4
    _, o = struct.unpack_from("<i", b, o)[0], o + 4
    o += 3
    csz = struct.unpack_from("<I", b, o)[0]
    o += 4 + csz * 4
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


def _rot_key(seed: bytes, i: int) -> bytes:
    return hashlib.sha256(seed + struct.pack("<Q", i)).digest()


def _block_key(seed: bytes, i: int, length: int) -> bytes:
    k = _rot_key(seed, i)
    return (k * (length // len(k) + 1))[:length]


def _xor_stream(seed: bytes, payload: bytes, block: int = XOR_BLOCK) -> bytes:
    out = []
    for off in range(0, len(payload), block):
        chunk = payload[off : off + block]
        key = _block_key(seed, off // block, len(chunk))
        out.append(bytes(a ^ b for a, b in zip(chunk, key)))
    return b"".join(out)


def _make_lit(parts) -> str:
    out = []
    for p in parts:
        cur = []
        for x in p:
            if 0x20 <= x < 0x7F and x not in (34, 92):
                cur.append(chr(x))
            elif x in (34, 92):
                cur.append("\\%c" % x)
            elif x in (9, 10, 13):
                cur.append("\\%03d" % x)
            else:
                cur.append("\\%03d" % x)
        out.append('"%s"' % "".join(cur))
    return " .. ".join(out) or '""'


def _gen_junk_source(seed: bytes, orig_size: int, total: int, names: list) -> str:
    rng = random.Random(os.urandom(16))
    header = MAGIC + bytes([VERSION]) + struct.pack("<I", orig_size) + seed
    body = bytearray()
    while len(body) < total:
        body += os.urandom(min(1 << 20, total - len(body)))
    enc = _xor_stream(seed, bytes(body))
    if len(enc) < HEAD_BYTES:
        enc += b"\x00" * (HEAD_BYTES - len(enc))
    blocks = [enc[i : i + 8192] for i in range(0, len(enc), 8192)]
    blocks[0] = header + blocks[0][HEAD_BYTES:]
    src = ["-- ikram protect %s" % rng.randbytes(4).hex()]
    for idx, name in enumerate(names):
        parts = blocks[idx:: len(names)]
        lit = _make_lit(parts)
        src.append(
            "local function %s()\n"
            "  local _t0 = %d\n"
            "  local _t1 = %.17g\n"
            "  local _t2 = %s\n"
            "  local _t3 = (_t0 + _t1) * 0.5\n"
            "  if false and _t2 then\n"
            "    _t0 = #_t2\n"
            "  end\n"
            "  return _t3\n"
            "end\n" % (name, idx + 1, (idx + 1) * 1.1, lit)
        )
    return "\n".join(src)


def _junk_funcs(seed: bytes, orig_size: int, target: int) -> list:
    rng = random.Random(os.urandom(16))
    n = max(3, min(64, target // 250_000))
    names = ["ikr%d_%s" % (i, rng.randbytes(4).hex()) for i in range(n)]
    src = _gen_junk_source(seed, orig_size, target, names)
    chunk = _luac(src)
    sizet = chunk[13] if chunk[13] in (4, 8) else 4
    o = HEADER_SIZE + 1
    _, o = _rd_str(chunk, o, sizet)
    _, o = struct.unpack_from("<i", chunk, o)[0], o + 4
    _, o = struct.unpack_from("<i", chunk, o)[0], o + 4
    o += 3
    csz = struct.unpack_from("<I", chunk, o)[0]
    o += 4 + csz * 4
    nk = struct.unpack_from("<I", chunk, o)[0]
    o += 4
    for _ in range(nk):
        o = _skip_const(chunk, o, sizet)
    nups = struct.unpack_from("<I", chunk, o)[0]
    o += 4 + nups * 2
    npts = struct.unpack_from("<I", chunk, o)[0]
    off = o + 4
    blobs = []
    for _ in range(npts):
        s = off
        off = _parse_func(chunk, off, len(chunk), sizet)
        blobs.append(chunk[s:off])
    return blobs


def _child_regions(data: bytes, sizet: int) -> list:
    o = HEADER_SIZE + 1
    _, o = _rd_str(data, o, sizet)
    _, o = struct.unpack_from("<i", data, o)[0], o + 4
    _, o = struct.unpack_from("<i", data, o)[0], o + 4
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


def _splice(std: bytes, blobs: list, sizet: int) -> bytes:
    npts_off, npts, regions = _child_regions(std, sizet)
    orig_start = regions[0][0] if regions else npts_off + 4
    debug_off = regions[-1][1] if regions else orig_start
    head = std[:npts_off]
    tail = std[debug_off:]
    return head + struct.pack("<I", npts + len(blobs)) + std[orig_start:debug_off] + b"".join(blobs) + tail


def _final_size(prot: bytes) -> int:
    try:
        import lua_bgmi

        return len(lua_bgmi.std_to_bgmi(prot))
    except Exception:
        return int(len(prot) * 1.1)


def protect(std: bytes, min_bytes: int = MIN_BYTES, max_bytes: int = MAX_BYTES):
    if ENV_OFF in os.environ and os.environ[ENV_OFF] == "0":
        return std
    if len(std) < HEADER_SIZE or std[:4] != b"\x1bLua":
        raise ValueError("protect: not a patched lua chunk")
    sizet = std[13] if std[13] in (4, 8) else 4
    base = len(std)
    seed = hashlib.sha256(std).digest()
    need = max(1_000_000, min_bytes - base)
    prot = _splice(std, _junk_funcs(seed, base, need), sizet)
    for _ in range(4):
        current = _final_size(prot)
        if min_bytes <= current <= max_bytes:
            break
        if current < min_bytes:
            prot = _splice(prot, _junk_funcs(seed, base, min_bytes - current), sizet)
            continue
        npts_off, npts, regions = _child_regions(prot, sizet)
        _, base_npts, _ = _child_regions(std, sizet)
        removable = npts - base_npts
        if removable <= 1:
            break
        frac = min(1.0, max_bytes / max(current, 1))
        k = max(1, int(removable * (1 - frac)))
        k = min(k, removable - 1)
        orig_children = prot[npts_off + 4 : regions[base_npts][0]]
        kept = [prot[s:e] for s, e in regions[base_npts : base_npts + removable - k]]
        tail = prot[regions[-1][1] :]
        prot = (
            prot[:npts_off]
            + struct.pack("<I", npts - k)
            + orig_children
            + b"".join(kept)
            + tail
        )
    return prot


def harden_compile(std: bytes) -> bytes:
    return protect(std)