"""File processors for the PAK TOOL UNPACK flow (any-file support).

Mirrors the paktoolproject/newproject.txt phase-3 pipeline:

  .uasset/.uexp/.umap -> JSON (package summary + names + strings)
  .locres             -> JSON + CSV (localization table)
  .locmeta            -> JSON (metadata strings)
  .ubulk/.uptnl       -> JSON (header + string extraction)
  .ushaderbytecode    -> JSON (SPIR-V / DXBC / string fallback)
  .ini/.json/.csv/.xml/.txt/.lua -> copied as-is (already readable)
  unknown             -> JSON (binary string extraction)

Runs on the shipped flat runtime with no extra deps. process_file() drives
a single standalone file; process_tree() drives a whole extracted pak tree
into a separate processed mirror (raw tree stays clean for REPACK).
"""
import json
import re
import shutil
import struct
from pathlib import Path

PROCESSORS = {}


def processor(exts):
    def deco(fn):
        for e in exts:
            PROCESSORS[e] = fn
        return fn
    return deco


def _strings(data, n=300, minlen=5):
    return [s.decode("ascii", "replace")
            for s in re.findall(rb"[\x20-\x7E]{%d,}" % minlen, data)[:n]]


def _strings_wide(data, n=300, minlen=5):
    return [s.decode("utf-16-le", "replace")
            for s in re.findall(rb"(?:[\x20-\x7E]\x00){%d,}" % minlen, data)[:n]]


def _read_str(d, o):
    ln = struct.unpack_from("<i", d, o)[0]
    o += 4
    if ln < 0:
        ln = -ln
        s = d[o:o + ln * 2].decode("utf-16-le", "replace").rstrip("\x00")
        o += ln * 2
    elif ln > 0:
        s = d[o:o + ln].decode("utf-8", "replace").rstrip("\x00")
        o += ln
    else:
        s = ""
        o += 0
    return s, o


# ---- INI / JSON / CSV / XML / TXT / LUA — seedha readable ----------------
@processor([".ini", ".json", ".csv", ".xml", ".txt", ".lua"])
def proc_text(src: Path, dst: Path):
    dst.write_bytes(src.read_bytes())
    return "copied (readable file)"


# ---- UASSET / UEXP / UMAP -------------------------------------------------
@processor([".uasset", ".uexp", ".umap"])
def proc_uasset(src: Path, dst: Path):
    data = src.read_bytes()
    result = {
        "file": str(src),
        "size": len(data),
        "header": data[:4].hex(),
        "format": "unknown",
        "strings": _strings(data),
    }
    if data[:4] == b"\xc1\x83\x2a\x9e":
        result["format"] = "uasset_v4"
        try:
            result.update(_parse_uasset_deep(data))
        except Exception as e:
            result["parse_error"] = str(e)
    _write_json(dst, ".json", result)
    return "uasset → {}.json".format(dst.name)


def _parse_uasset_deep(data: bytes) -> dict:
    off = 0
    r = {}
    if len(data) < 32:
        raise ValueError("too small for package summary")

    r["magic"] = hex(struct.unpack_from("<I", data, off)[0]); off += 4
    r["legacy_version"] = struct.unpack_from("<i", data, off)[0]; off += 4
    r["legacy_ue3_ver"] = struct.unpack_from("<i", data, off)[0]; off += 4
    r["file_version_ue4"] = struct.unpack_from("<i", data, off)[0]; off += 4
    r["licensee_version"] = struct.unpack_from("<i", data, off)[0]; off += 4

    custom_count = struct.unpack_from("<I", data, off)[0]; off += 4
    off += custom_count * 20  # skip custom version entries (guid + 5 x int)

    r["total_header_size"] = struct.unpack_from("<I", data, off)[0]; off += 4
    folder_len = struct.unpack_from("<i", data, off)[0]; off += 4
    if folder_len > 0:
        r["folder_name"] = data[off:off + folder_len].decode("utf-8", "replace").rstrip("\x00")
        off += folder_len
    r["package_flags"] = hex(struct.unpack_from("<I", data, off)[0]); off += 4

    name_count = struct.unpack_from("<I", data, off)[0]; off += 4
    off += 4  # name table offset
    export_count = struct.unpack_from("<I", data, off)[0]; off += 4
    off += 4  # export table offset
    import_count = struct.unpack_from("<I", data, off)[0]; off += 4
    off += 4  # import table offset

    r["name_count"] = name_count
    r["export_count"] = export_count
    r["import_count"] = import_count

    names = _parse_names(data, name_count)
    r["names"] = names[:100]
    r["exports"] = _parse_exports(data, export_count, names)
    r["imports"] = _parse_imports(data, import_count, names)
    return r


def _parse_names(data: bytes, name_count: int) -> list:
    names = []
    noff = 0
    for _ in range(min(name_count, 5000)):
        if noff >= len(data) - 4:
            break
        nlen = struct.unpack_from("<i", data, noff)[0]; noff += 4
        if nlen < 0:
            nlen = -nlen
            name = data[noff:noff + nlen * 2].decode("utf-16-le", "replace").rstrip("\x00")
            noff += nlen * 2
        elif nlen > 0:
            name = data[noff:noff + nlen].decode("utf-8", "replace").rstrip("\x00")
            noff += nlen
        else:
            name = ""
        noff += 4  # name hash
        names.append(name)
    return names


def _parse_exports(data: bytes, export_count: int, names: list) -> list:
    exports = []
    eoff = 0
    for _ in range(min(export_count, 1000)):
        if eoff >= len(data) - 72:
            break
        e = {
            "class_index": struct.unpack_from("<i", data, eoff)[0],
            "super_index": struct.unpack_from("<i", data, eoff + 4)[0],
            "template_index": struct.unpack_from("<i", data, eoff + 8)[0],
            "outer_index": struct.unpack_from("<i", data, eoff + 12)[0],
        }
        name_idx = struct.unpack_from("<i", data, eoff + 16)[0]
        if 0 <= name_idx < len(names):
            e["name"] = names[name_idx]
        e["serial_size"] = struct.unpack_from("<q", data, eoff + 40)[0]
        e["serial_offset"] = struct.unpack_from("<q", data, eoff + 48)[0]
        exports.append(e)
        eoff += 72
    return exports


def _parse_imports(data: bytes, import_count: int, names: list) -> list:
    imports = []
    ioff = 0
    for _ in range(min(import_count, 1000)):
        if ioff >= len(data) - 28:
            break
        i = {}
        pkg_idx = struct.unpack_from("<i", data, ioff + 8)[0]
        name_idx = struct.unpack_from("<i", data, ioff + 20)[0]
        if 0 <= pkg_idx < len(names):
            i["package"] = names[pkg_idx]
        if 0 <= name_idx < len(names):
            i["name"] = names[name_idx]
        imports.append(i)
        ioff += 28
    return imports


# ---- UBULK / UPTNL — raw binary -------------------------------------------
@processor([".ubulk", ".uptnl"])
def proc_ubulk(src: Path, dst: Path):
    data = src.read_bytes()
    result = {
        "file": str(src),
        "size": len(data),
        "header_hex": data[:32].hex(),
        "strings": _strings(data, 200),
    }
    _write_json(dst, ".json", result)
    return "ubulk → {}.json".format(dst.name)


# ---- LOCRES — localization -------------------------------------------------
@processor([".locres"])
def proc_locres(src: Path, dst: Path):
    data = src.read_bytes()
    strings = {}
    try:
        off = 20  # skip GUID + version
        count = struct.unpack_from("<I", data, off)[0]; off += 4
        for _ in range(min(count, 50000)):
            if off >= len(data) - 8:
                break
            ns, off = _read_str(data, off)
            key, off = _read_str(data, off)
            off += 4  # hash
            val, off = _read_str(data, off)
            if key:
                strings["{}::{}".format(ns, key)] = val
    except Exception as e:
        strings["_error"] = str(e)
    if not strings or strings.get("_error"):
        # PUBG 4.6 locres is NOT the vanilla tlv layout — it is a stream of
        # length-prefixed utf16/utf8 strings (keys then values, hashes/small
        # ints interleaved). Loose structural scan == all localization strings.
        strings = {".str{}".format(i): s for i, s in enumerate(_locres_scan(data))}

    _write_json(dst, ".json", strings, ensure_ascii=False)

    lines = ["key,value"]
    for k, v in strings.items():
        lines.append('"{}","{}"'.format(k, str(v).replace('"', '""')))
    (dst.with_name(dst.name + ".csv")).write_text("\n".join(lines), encoding="utf-8")
    return "locres → {} strings, {}.json + {}.csv".format(len(strings), dst.name, dst.name)


def _locres_scan(data: bytes) -> list:
    """Walk length-prefixed string records anywhere in the blob (byte aligned):
    int32 len (+ => utf8, - => utf16, incl null terminator) — skip hashes/ints."""
    out = []
    o = 0
    size = len(data)
    while o + 8 <= size:
        ln = struct.unpack_from("<i", data, o)[0]
        advanced = False
        if ln < 0:
            n = -ln
            if 1 <= n <= 2000 and o + 4 + n * 2 <= size:
                end = o + 4 + n * 2
                if data[end - 2:end] == b"\x00\x00":
                    s = data[o + 4:end - 2].decode("utf-16-le", "replace")
                    if _locres_good(s):
                        out.append(s)
                        o = end
                        advanced = True
        elif ln > 0:
            if o + 4 + ln <= size:
                end = o + 4 + ln
                if data[end - 1] == 0 and ln <= 8000:
                    s = data[o + 4:end - 1].decode("utf-8", "replace")
                    if _locres_good(s):
                        out.append(s)
                        o = end
                        advanced = True
        if not advanced:
            o += 1
    return out


def _locres_good(s: str) -> bool:
    if not s or not s.strip("\x00"):
        return False
    n = len(s)
    good = sum(
        1 for c in s
        if 0x20 <= ord(c) <= 0x7E or 0x3000 <= ord(c) <= 0x9FFF
        or 0xFF00 <= ord(c) <= 0xFFEF or c in "\t\n"
    )
    return good * 100 >= n * 98


# ---- LOCMETA ---------------------------------------------------------------
@processor([".locmeta"])
def proc_locmeta(src: Path, dst: Path):
    data = src.read_bytes()
    result = {
        "file": str(src),
        "size": len(data),
        "header": data[:16].hex(),
        "strings": _strings(data, 300, 4),
    }
    _write_json(dst, ".json", result)
    return "locmeta → {}.json".format(dst.name)


# ---- SHADER BYTECODE -------------------------------------------------------
@processor([".ushaderbytecode", ".ushadercode"])
def proc_shader(src: Path, dst: Path):
    data = src.read_bytes()
    if data[:4] in (b"\x03\x02\x23\x07", b"\x07\x23\x02\x03"):
        return _proc_spirv(src, dst, data)
    if data[:4] == b"DXBC":
        return _proc_dxbc(src, dst, data)
    result = {
        "file": str(src),
        "format": "unknown_shader",
        "header": data[:16].hex(),
        "strings": _strings(data, 200, 4),
    }
    _write_json(dst, ".json", result)
    return "shader → {}.json".format(dst.name)


def _proc_spirv(src: Path, dst: Path, data: bytes):
    endian = "<" if data[:4] == b"\x03\x02\x23\x07" else ">"
    result = {
        "file": str(src),
        "format": "SPIR-V",
        "version": hex(struct.unpack_from("{}I".format(endian), data, 4)[0]),
        "bound": struct.unpack_from("{}I".format(endian), data, 12)[0],
        "strings": [],
        "instructions": [],
    }
    off = 20
    while off < len(data) - 4:
        try:
            w = struct.unpack_from("{}I".format(endian), data, off)[0]
            wc = (w >> 16) & 0xFFFF
            op = w & 0xFFFF
            if wc == 0:
                break
            if op == 7 and off + 8 <= len(data):  # OpString
                s = data[off + 8:off + wc * 4].decode("utf-8", "replace").rstrip("\x00")
                if s:
                    result["strings"].append(s)
            result["instructions"].append({"op": op, "wc": wc})
            off += wc * 4
        except Exception:
            break
    _write_json(dst, ".spirv.json", result)
    return "SPIR-V → {}.json".format(dst.name)


def _proc_dxbc(src: Path, dst: Path, data: bytes):
    result = {
        "file": str(src),
        "format": "DXBC",
        "header": data[:4].decode("ascii", "replace"),
        "size": struct.unpack_from("<I", data, 24)[0] if len(data) > 28 else 0,
        "strings": _strings(data, 200, 4),
    }
    _write_json(dst, ".dxbc.json", result)
    return "DXBC → {}.json".format(dst.name)


# ---- BINARY / UNKNOWN ------------------------------------------------------
def proc_binary(src: Path, dst: Path):
    data = src.read_bytes()
    result = {
        "file": str(src),
        "size": len(data),
        "header_hex": data[:32].hex(),
        "ascii_strings": _strings(data, 300),
        "utf16_strings": _strings_wide(data, 100),
    }
    _write_json(dst, ".json", result)
    return "binary → {}.json".format(dst.name)


def _write_json(dst: Path, suffix: str, obj, ensure_ascii=False):
    # append-style sidecar (M_3DUI_02.uasset.json) so .uasset/.uexp pair
    # sidecars never overwrite each other.
    target = dst.with_name(dst.name + suffix)
    target.write_text(json.dumps(obj, indent=2, ensure_ascii=ensure_ascii, default=str), encoding="utf-8")


def process_file(src, dst_dir, log=None):
    """Process one standalone file -> dst_dir. Returns summary message."""
    log = log or (lambda msg: None)
    src = Path(src)
    dst_dir = Path(dst_dir)
    dst_dir.mkdir(parents=True, exist_ok=True)
    fn = PROCESSORS.get(src.suffix.lower(), proc_binary)
    try:
        msg = fn(src, dst_dir / src.name)
        log(msg)
        return msg
    except Exception as e:
        msg = "process failed: {}".format(e)
        log(msg)
        return msg


def process_tree(src_dir, dst_dir, log=None, every=None):
    """Process every file under src_dir -> dst_dir mirror.

    Returns (count, stats, errors). Raw tree untouched — sidecars land in
    dst_dir so REPACK never picks them up.
    """
    log = log or (lambda msg: None)
    every = every or 100
    src_dir = Path(src_dir)
    dst_dir = Path(dst_dir)
    if dst_dir.exists():
        shutil.rmtree(dst_dir)
    dst_dir.mkdir(parents=True, exist_ok=True)

    files = [p for p in src_dir.rglob("*") if p.is_file() and not p.name.startswith(".")]
    errors = []
    stats = {}
    for i, src in enumerate(files, 1):
        ext = src.suffix.lower()
        dst = dst_dir / src.relative_to(src_dir)
        dst.parent.mkdir(parents=True, exist_ok=True)
        try:
            PROCESSORS.get(ext, proc_binary)(src, dst)
            stats[ext or "no_ext"] = stats.get(ext or "no_ext", 0) + 1
        except Exception as e:
            errors.append({"file": str(src.relative_to(src_dir)), "error": str(e)})
        if i % every == 0 or i == len(files):
            log("[{}/{}] {}".format(i, len(files), src.name))
    return len(files), stats, errors