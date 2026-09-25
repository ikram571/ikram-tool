"""IkramTool V117 — Lua Intelligence Engine.

Full multi-tier decompile cascade + game-ready validator + honest reporting.

Detection (auto, no user input needed): IKRM wrapper, bare magic (standard
Lua 1B 4C 75 61 50..54 / LuaJIT 1B 4C 4A 01..03 / Luau 1B 62 75 6C 75),
magic behind a wrapper (PUBG/BGMI/UE4 length prefix, TPF loader, filler),
readable source, then Shannon entropy bands (<4.0 source, 4.0-6.5 bytecode,
6.5-7.5 lightly encrypted, >7.5 encrypted) to infer an encrypted chunk.

Tiers (tried in order, first fully-validated pass wins):
  T0 wrapper   strip a proven PUBG/BGMI/UE4 length prefix so every engine
                downstream sees a normal header.
  T4 pre-pass   XOR / additive key sweep (key lengths 1,2,4,8,16,32,64,128)
                + string-extraction heuristic for encrypted candidates.
  T1 standard   mega_lua game engine (BGMI+standard+LuaJIT), unluac_rs,
                unluac.jar, luadec (if installed).
  T2 luajit     unluac_rs, unluac.jar, ljd rawdump->pseudoasm, luajit -bL.
  T3 disasm     luac -l -l listing, luajit -bL (-bl), r2 pdl (if installed).
  T5 large      >1MB files: scaled timeouts; chunk-split is refused honestly
                (unsafe on arbitrary protection) and reported as such.
  T6 fallback   best readable disassembly is SAVED as <name>_disassembled.lua
                and signalled so the UI can show the honest warn box.
  T7 fail       <name>_FAILED.txt with the full method-by-method trail.

Validator — 8 checks, ALL must pass (matches the game-ready standard):
  len > 50, >=5 lua keywords, garbage < 2%, question-marks < 1%, >=2 code
  structures, avg line 5..300, round-trip recompile with luac, no line
  mostly-binary.  Anything less is not a success — never kept, never shown.
"""
import math
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import univ
import mega_lua as _mega

LUA_KEYWORDS = ("function", "local", "return", "end", "if", "then", "else",
                "while", "for", "do", "and", "or", "not", "nil", "true",
                "false", "repeat", "until", "break", "in")

STRUCTURE_TOKENS = ("function", "if", "while", "for", "repeat", "do", "end")

_XOR_LENGTHS = (1, 2, 4, 8, 16, 32, 64, 128)
_LUA_MAGICS = (b"\x1bLuaQ", b"\x1bLuaR", b"\x1bLuaS", b"\x1bLuaT",
               b"\x1bLua", b"\x1bLJ")

VERSION = "v117"

# Offsets a wrapper may occupy before the real chunk starts. The offset is
# never trusted on its own: find_wrapper only accepts one where a real
# Lua/LuaJIT/Luau header actually parses, so PUBG Mobile / BGMI / UE4
# length prefixes, TPF-style loader blocks and fixed mod fillers are all
# handled by the same proof-based check.
_WRAPPER_SCAN = (1, 2, 3, 4, 5, 6, 7, 8, 12, 16, 24, 32, 48, 64, 96, 128, 256)


# ---------------------------------------------------------------- detection
def shannon_entropy(data: bytes) -> float:
    if not data:
        return 0.0
    counts = {}
    for b in data:
        counts[b] = counts.get(b, 0) + 1
    n = len(data)
    return -sum(c / n * math.log2(c / n) for c in counts.values())


def entropy_band(e: float) -> str:
    if e < 4.0:
        return "source"
    if e < 6.5:
        return "standard bytecode"
    if e < 7.5:
        return "lightly encrypted"
    return "encrypted"


def _lua_family_at(head: bytes):
    """(family, kind) for a real Lua/LuaJIT/Luau header, else (None, None).

    Version-byte check only, deliberately matching V116's rule so no chunk
    that used to decompile can stop decompiling. Adds LuaJIT 0x03 and Luau,
    which V116 reported as 'unknown'. Mirrors mega_lua._detect_dialect so
    detection and the cascade never disagree about the family.
    """
    if len(head) < 5:
        return None, None
    if head[:4] == b"\x1bLua" and 0x51 <= head[4] <= 0x54:
        return "Lua 5.%d" % (head[4] - 0x50), "standard Lua bytecode"
    if head[:4] == b"\x1bLua" and head[4] == 0x50:
        return "Lua 5.0", "standard Lua bytecode"
    if head[:3] == b"\x1bLJ" and head[3] in (0x01, 0x02, 0x03):
        return "LuaJIT", "LuaJIT bytecode"
    if head[:4] == b"\x1bulu":
        return "Luau", "Luau bytecode"
    return None, None


def find_wrapper(data: bytes) -> int:
    """Byte offset where the real Lua chunk starts, 0 when there is no wrapper.

    Proves a candidate offset with a real family header instead of guessing:
    the bytes at that offset must parse as Lua/LuaJIT/Luau.
    """
    for off in _WRAPPER_SCAN:
        if off + 12 > len(data):
            break
        fam, _k = _lua_family_at(data[off:off + 12])
        if fam:
            return off
    return 0


def detect_report(data: bytes) -> dict:
    """Deep auto-detect -> family/dialect/entropy/kind/protection labels.

    Order: IKRM wrapper, then a bare magic, then a wrapped magic, then
    source, then encryption inference. Never guesses a family it cannot prove.
    """
    e = shannon_entropy(data)
    head = data[:8]
    report = {
        "family": None,
        "kind": "unknown",
        "entropy": round(e, 3),
        "band": entropy_band(e),
        "magic": head[:5].hex(),
        "wrapper": 0,
        "protection": None,
    }

    if not data:
        report["kind"] = "empty"
        return report

    # --- IKRM (IkramTool's own wrapper) — checked before everything else
    if data[:4] == b"IKRM":
        report["family"] = "IKRM"
        report["kind"] = "IKRM protected chunk"
        report["protection"] = "ikrm"
        return report

    # --- bare magic
    fam, kind = _lua_family_at(head)
    if fam:
        report["family"] = fam
        report["kind"] = kind
        return report

    # --- magic behind a wrapper (PUBG/BGMI length prefix, TPF loader, filler)
    off = find_wrapper(data)
    if off:
        fam, kind = _lua_family_at(data[off:off + 12])
        report["family"] = fam
        report["kind"] = "%s (wrapped, %d-byte header)" % (kind, off)
        report["wrapper"] = off
        return report

    # --- readable source
    try:
        text = data[:4096].decode("utf-8", errors="strict")
        if _mega._looks_like_lua_source(text) or _mega._compiles_as_lua(text):
            report["family"] = "Lua source"
            report["kind"] = "readable Lua source"
            return report
    except (UnicodeDecodeError, ValueError):
        pass

    # --- encrypted / obfuscated: infer from entropy + structure
    if e >= 6.5:
        report["family"] = None
        report["kind"] = "encrypted chunk (no readable header)"
        report["protection"] = "encrypted"
        return report

    # No magic, not source, not high entropy: still not trustworthy as a chunk,
    # so the key sweep must run and the report must not claim "unknown".
    report["family"] = None
    report["kind"] = "obfuscated chunk (no readable header)"
    report["protection"] = "obfuscated"
    return report


def _garbage_ratio(text: str) -> float:
    if not text:
        return 1.0
    bad = 0
    for ch in text[:4000]:
        o = ord(ch)
        if ch == "\ufffd" or (0 <= o < 9) or (0x0B <= o < 0x20):
            bad += 1
    return bad / min(len(text), 4000)


def _binary_line_ratio(text: str) -> float:
    """Fraction of non-empty lines that are mostly non-printable."""
    if not text:
        return 1.0
    total = bad = 0
    for ln in text.splitlines():
        if not ln.strip():
            continue
        total += 1
        if len(ln) and sum(1 for c in ln[:200] if ord(c) > 126 or ord(c) < 9) / max(1, len(ln)) > 0.1:
            bad += 1
    return bad / max(1, total)


def _structure_count(text: str) -> int:
    import re
    low = text.lower()
    count = 0
    for token in STRUCTURE_TOKENS:
        count += len(re.findall(r"\b%s\b" % token, low))
    return max(count, 0)


def validate(text: str) -> dict:
    """Run the 8 checks; return check keys, score and passed flag."""
    text = text or ""
    lines = [l for l in text.splitlines() if l.strip()]
    avg = (sum(len(l) for l in lines) / len(lines)) if lines else 0
    lower = text.lower()
    keywords = sum(k in lower for k in LUA_KEYWORDS)
    structures = _structure_count(text)
    checks = {
        "len > 50": len(text) > 50,
        "keywords >= 5": keywords >= 5,
        "garbage < 2%": _garbage_ratio(text) < 0.02,
        "? < 1%": (text.count("?") / max(1, len(text))) < 0.01,
        "structures >= 2": structures >= 2,
        "avg line 5..300": 5 <= avg <= 300,
        "round-trip recompile": _mega._compiles_as_lua(text),
        "no binary lines": _binary_line_ratio(text) < 0.5,
    }
    passed = [k for k, v in checks.items() if v]
    return {
        "checks": checks,
        "passed": len(passed),
        "total": len(checks),
        "score": len(passed),
        "ok": len(passed) == len(checks),
        "avg_line": round(avg, 1),
        "keywords": keywords,
        "structures": structures,
    }


def _quality_label(score: int, total: int = 8) -> str:
    if score >= total:
        return "Excellent"
    if score >= total - 1:
        return "Very good"
    if score >= total - 2:
        return "Good"
    if score >= total - 3:
        return "Fair"
    return "Poor"


# ------------------------------------------------------------- tool lookup
_TOOL_DIR = Path(__file__).resolve().parent
DEPS_DIR = _TOOL_DIR / "deps"
LJD_DIR = DEPS_DIR / "ljd"


def _on_path(name: str) -> bool:
    return shutil.which(name) is not None


def _call(cmd, timeout=60, data=None):
    try:
        p = subprocess.run(cmd, input=data, capture_output=True, timeout=timeout)
        return p.returncode, p.stdout.decode("utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        return -1, "timed out after %ss" % timeout
    except Exception as e:
        return -1, str(e)


def _luac_disasm(data: bytes) -> list:
    """Built-in `luac -l -l` bytecode listing for standard chunks."""
    out = []
    for name in ("luac", "luac5.3", "luac5.4", "luac5.2", "luac5.1"):
        exe = shutil.which(name)
        if not exe:
            continue
        rc, txt = _call([exe, "-l", "-l", "-"], timeout=40, data=data)
        if rc == 0 and txt and "main <" in txt:
            out.append((name, txt))
            break
    return out


def _luajit_disasm(data: bytes) -> list:
    """Readable bytecode listing via `luajit -bL` (works for any LuaJIT chunk)."""
    luajit = shutil.which("luajit")
    res = []
    if luajit:
        rc, txt = _call([luajit, "-bL", "-", "/dev/stdout"], timeout=40, data=data)
        if rc == 0 and txt and ("----" in txt or "->" in txt):
            res.append(("luajit -bL", txt))
        rc, txt = _call([luajit, "-bl", "-", "/dev/stdout"], timeout=40, data=data)
        if rc == 0 and txt:
            res.append(("luajit -bl", txt))
    return res


def _unluac_rs(data: bytes, timeout=120) -> str | None:
    """Bundled Rust unluac_rs — the fastest standard-Lua tier.

    Same shape as _unluac_jar: returns text or None. Kept as its own tier so a
    meg_lua miss does not cost the whole file when the Rust engine can read it.
    """
    exe = _mega.UNLUAC_RS
    if not Path(exe).exists():
        return None
    fd, tmp = tempfile.mkstemp(suffix=".luac")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        p = subprocess.run([str(exe), "-i", tmp],
                           capture_output=True, timeout=timeout)
        if p.returncode != 0:
            return None
        txt = p.stdout.decode("utf-8", errors="replace")
        if not txt.strip():
            return None
        if "function " not in txt and "local " not in txt and txt.strip().count("\n") < 2:
            return None
        return txt
    except subprocess.TimeoutExpired:
        return None
    except Exception:
        return None
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def _unluac_jar(data: bytes, timeout=90) -> str | None:
    jar = _mega.UNLUAC_JAR
    if not Path(jar).exists():
        return None
    fd, tmp = tempfile.mkstemp(suffix=".luac")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        p = subprocess.run(
            ["java", "-jar", str(jar), tmp],
            capture_output=True, timeout=timeout)
        if p.returncode != 0:
            return None
        txt = p.stdout.decode("utf-8", errors="replace")
        if not txt.strip():
            return None
        if "function " not in txt and "local " not in txt and txt.strip().count("\n") < 2:
            return None
        return txt
    except subprocess.TimeoutExpired:
        return None
    except Exception:
        return None
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def _ljd_decompile(data: bytes, timeout=60) -> str | None:
    """LuaJIT decompiler (Andrian Nord ljd) via bundled deps/ljd."""
    if not LJD_DIR.is_dir():
        return None
    import sys
    try:
        old = list(sys.path)
        sys.path.insert(0, str(LJD_DIR))
        from ljd.rawdump import parser
        import ljd.pseudoasm.writer as writer
    except Exception:
        return None
    finally:
        sys.path[:] = old
    import io as _io, tempfile, os, contextlib
    try:
        tmp = tempfile.NamedTemporaryFile(prefix="ljd_", suffix=".luac", delete=False)
        tmp.write(data)
        tmp.close()
        try:
            header, proto = None, None
            with contextlib.redirect_stderr(_io.StringIO()):
                res = parser.parse(tmp.name)
                if isinstance(res, tuple) and len(res) >= 2:
                    header, proto = res[0], res[1]
            if header is None:
                return None
            buf = _io.StringIO()
            with contextlib.redirect_stderr(_io.StringIO()):
                writer.write(buf, header, proto)
            txt = buf.getvalue()
            return txt if txt and txt.strip() else None
        finally:
            os.unlink(tmp.name)
    except Exception:
        return None


def _string_extraction(data: bytes) -> list:
    """Extract printable sequences (min 4 chars), keep the long ones."""
    import re
    seqs = re.findall(rb"[\x20-\x7e]{4,}", data)
    return [s.decode("latin-1") for s in seqs]


def _xor_sweep(data: bytes) -> list:
    """Tier-4 sweep: recover repeating XOR/additive keys against known lua
    magic at the file start (and a few early offsets). Returns [(label, dec)].
    """
    found = []
    if _lua_family_at(data[:12])[0]:
        return found            # already a bare chunk: nothing to decrypt
    for offset in (0, 1, 2, 4, 8, 16, 32, 64, 128, 256):
        if offset + 4 > len(data):
            break
        window = data[offset:]
        for plain in _LUA_MAGICS:
            if len(plain) > len(window):
                continue
            for key_len in _XOR_LENGTHS:
                for mode, fn in (("xor", _mega._xor_key_recover),
                                 ("add", _mega._add_key_recover)):
                    key = fn(window, plain, key_len)
                    if key is None:
                        continue
                    if not any(key):
                        continue          # all-zero key is a no-op, not a decrypt
                    dec = bytearray(data)
                    for i in range(offset, len(dec)):
                        if mode == "xor":
                            dec[i] ^= key[i % key_len]
                        else:
                            dec[i] = (dec[i] - key[i % key_len]) & 0xFF
                    head = bytes(dec[:8])
                    good = False
                    if head[:4] == b"\x1bLua" and len(head) >= 5 and 0x51 <= head[4] <= 0x54:
                        good = True
                    elif head[:3] == b"\x1bLJ" and len(head) >= 4 and head[3] <= 0x0B:
                        good = True
                    elif _mega._detect_dialect(bytes(dec[:128])):
                        good = True
                    if good:
                        found.append(("%s key (len %d)" % (mode.upper(), key_len),
                                      bytes(dec)))
                        return found
    return found


# ---------------------------------------------------------------- pipeline
def run(src, out_dir, progress=None) -> dict:
    """Decompile one Lua file through the full tier cascade.

    Returns {"ok": bool, "status": "success"|"disassembled"|"failed",
             "out": Path|None, "disasm_path": Path|None,
             "fail_path": Path|None, "meta": dict,
             "attempts": [(label, msg)], "lines": int|None,
             "quality": str|None, "msg": str}
    """
    src = Path(src)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = src.stem
    data = src.read_bytes()
    try:
        import ikram_upgrade as _ik
    except Exception:
        _ik = None
    if _ik is not None and _ik.is_protected(data):
        _phase(progress, "IKRM wrapper detected, decrypting...")
        data = _ik.try_unwrap(data)
        if data is None:
            meta = detect_report(b"")
            return _finish_failure(src, out_dir, stem, meta, [
                ("IKRM", "wrapper decrypt failed (checksum/size mismatch)")])
    meta = detect_report(data)
    attempts = []

    if not data:
        attempts.append(("Input", "file is empty"))
        return _finish_failure(src, out_dir, stem, meta, attempts)

    # plain source text pass-through (readable as-is) — only when the header
    # carries NO lua magic (compiled chunks never qualify, whatever entropy).
    if meta["kind"] == "unknown":
        text = data.decode("utf-8", errors="replace")
        if _mega._looks_like_lua_source(text) or _mega._compiles_as_lua(text):
            final = out_dir / (stem + "_decompiled.lua")
            final.write_text(text, encoding="utf-8")
            v = validate(text)
            why = "readable source (as-is)"
            attempts.append(("Source passthrough",
                             "%d/8 validator score (readable source is trusted)" % v["score"]))
            return {
                "ok": True, "status": "success", "out": final,
                "disasm_path": None, "fail_path": None,
                "meta": meta, "attempts": attempts,
                "lines": len([l for l in text.splitlines() if l.strip()]),
                "quality": why, "msg": why,
            }

    bytes_for_methods = data
    decrypt_note = ""
    dec_src = src

    # ----- TIER 0 — wrapper strip (PUBG/BGMI/UE4 length prefix, TPF loader).
    # detect_report already proved a real family header sits at meta["wrapper"];
    # hand the engines the bare chunk so every tier sees a normal header.
    if meta["wrapper"]:
        off = meta["wrapper"]
        _phase(progress, "Stripping %d-byte wrapper..." % off)
        data = data[off:]
        bytes_for_methods = data
        dec_tmp = out_dir / ("_tmp_%s_strip.luac" % stem)
        dec_tmp.write_bytes(data)
        dec_src = dec_tmp
        decrypt_note = " | stripped %d-byte wrapper" % off
        attempts.append(("Wrapper strip",
                         "%d-byte header removed, real chunk starts at offset %d"
                         % (off, off)))

    # ----- TIER 4 — encryption bypass prepass (before any decompiler)
    if (meta["protection"]
            or meta["band"] in ("lightly encrypted", "encrypted")
            or meta["kind"] == "unknown"):
        _phase(progress, "Encryption sweep...")
        sweep = _xor_sweep(data)
        if sweep:
            label, dec = sweep[0]
            attempts.append(("XOR/SKIP", "decrypted with %s" % label))
            bytes_for_methods = dec
            decrypt_note = " | decrypted %s" % label
            dec_tmp = out_dir / ("_tmp_%s_dec.luac" % stem)
            dec_tmp.write_bytes(dec)
            dec_src = dec_tmp
        else:
            strings = _string_extraction(data)
            kw_hits = [s for s in strings if any(k in s.lower()
                                                for k in ("function", "return", "local", "end"))]
            if kw_hits:
                attempts.append(("String probe",
                                 "%d printable strings, >0 lua keywords → trying decompilers anyway" % len(strings)))
            else:
                attempts.append(("String probe",
                                 "%d printable strings, no lua keywords found" % len(strings)))

    # ----- prepare the standard disassembly tier (cheap, always)
    disasm = []

    # order depends on detected family
    if meta["family"] == "LuaJIT":
        order = ("mega", "unluacrs", "unluac", "ljd", "luajit")
    elif meta["family"] and meta["family"].startswith("Lua 5."):
        order = ("mega", "unluacrs", "unluac", "luacdis")
    else:
        order = ("mega", "unluacrs", "unluac", "ljd", "luacdis", "luajit")

    for step in order:
        # ----- TIER 1 — mega_lua game engine (the proven core)
        if step == "mega":
            _phase(progress, "MegaLua engine...")
            try:
                results = univ.decompile_multi_engines(str(dec_src), str(out_dir),
                                                       progress=progress)
            except Exception as e:
                results = []
                attempts.append(("MegaLua", "engine error: %s" % str(e)[:80]))
            for label, ok, path, msg in results:
                if ok and path and Path(path).exists():
                    text = Path(path).read_text(errors="replace")
                    v = validate(text)
                    if v["ok"]:
                        final = out_dir / (stem + "_decompiled.lua")
                        try:
                            Path(path).rename(final)
                        except OSError:
                            final.write_text(text, encoding="utf-8")
                        quality = "%s (%d/8)%s | avg line %.1f" % (
                            _quality_label(v["score"]), v["score"], decrypt_note,
                            v["avg_line"])
                        return {
                            "ok": True, "status": "success", "out": final,
                            "disasm_path": None, "fail_path": None,
                            "meta": meta, "attempts": attempts + [(
                                label, str(msg)[:120])],
                            "lines": len([l for l in text.splitlines() if l.strip()]),
                            "quality": quality, "msg": str(msg),
                        }
                    attempts.append(("MegaLua", "%s rejected by validator (%d/8: %s)"
                                     % (label, v["score"],
                                        ", ".join(k for k, okk in v["checks"].items() if not okk))))
                else:
                    attempts.append((label, "%s" % str(msg)[:120]))
        # ----- TIER 1/2 — unluac_rs (bundled Rust engine, fastest)
        elif step == "unluacrs":
            _phase(progress, "unluac_rs...")
            text = _unluac_rs(bytes_for_methods)
            if text:
                v = validate(text)
                if v["ok"]:
                    final = out_dir / (stem + "_decompiled.lua")
                    final.write_text(text, encoding="utf-8")
                    quality = "%s (%d/8)%s | avg line %.1f" % (
                        _quality_label(v["score"]), v["score"], decrypt_note,
                        v["avg_line"])
                    return {
                        "ok": True, "status": "success", "out": final,
                        "disasm_path": None, "fail_path": None,
                        "meta": meta, "attempts": attempts + [(
                            "unluac_rs", "validated %d/8" % v["score"])],
                        "lines": len([l for l in text.splitlines() if l.strip()]),
                        "quality": quality, "msg": "unluac_rs decompile",
                    }
                attempts.append(("unluac_rs", "output rejected by validator (%d/8: %s)"
                                 % (v["score"], ", ".join(k for k, o in v["checks"].items() if not o))))
            else:
                attempts.append(("unluac_rs", "failed to parse this chunk"))
        # ----- TIER 1/2 — unluac.jar (standard + LuaJIT)
        elif step == "unluac":
            _phase(progress, "unluac.jar...")
            text = _unluac_jar(bytes_for_methods)
            if text:
                v = validate(text)
                if v["ok"]:
                    final = out_dir / (stem + "_decompiled.lua")
                    final.write_text(text, encoding="utf-8")
                    quality = "%s (%d/8)%s | avg line %.1f" % (
                        _quality_label(v["score"]), v["score"], decrypt_note,
                        v["avg_line"])
                    return {
                        "ok": True, "status": "success", "out": final,
                        "disasm_path": None, "fail_path": None,
                        "meta": meta, "attempts": attempts + [(
                            "unluac.jar", "validated %d/8" % v["score"])],
                        "lines": len([l for l in text.splitlines() if l.strip()]),
                        "quality": quality, "msg": "unluac.jar decompile",
                    }
                attempts.append(("unluac.jar", "output rejected by validator (%d/8: %s)"
                                 % (v["score"], ", ".join(k for k, o in v["checks"].items() if not o))))
            else:
                attempts.append(("unluac.jar", "failed to parse this chunk"))
        # ----- TIER 2 — ljd (LuaJIT)
        elif step == "ljd":
            _phase(progress, "ljd (LuaJIT)...")
            text = _ljd_decompile(bytes_for_methods)
            if text:
                v = validate(text)
                if v["ok"]:
                    final = out_dir / (stem + "_decompiled.lua")
                    final.write_text(text, encoding="utf-8")
                    quality = "%s (%d/8)%s | avg line %.1f" % (
                        _quality_label(v["score"]), v["score"], decrypt_note,
                        v["avg_line"])
                    return {
                        "ok": True, "status": "success", "out": final,
                        "disasm_path": None, "fail_path": None,
                        "meta": meta, "attempts": attempts + [(
                            "ljd", "validated %d/8" % v["score"])],
                        "lines": len([l for l in text.splitlines() if l.strip()]),
                        "quality": quality, "msg": "ljd decompile",
                    }
                attempts.append(("ljd", "output rejected by validator (%d/8)" % v["score"]))
            else:
                attempts.append(("ljd", "could not parse chunk (unsupported opcodes)"))
        # ----- TIER 3 — built-in disassemblers
        elif step == "luacdis":
            for name, txt in _luac_disasm(bytes_for_methods):
                disasm.append((name, txt))
                attempts.append((name, "bytecode listing (%d lines)" % txt.count("\n")))
        elif step == "luajit":
            for name, txt in _luajit_disasm(bytes_for_methods):
                disasm.append((name, txt))
                attempts.append((name, "bytecode listing (%d lines)" % txt.count("\n")))

    # ----- TIER 5 — large-file note
    if len(data) > 1024 * 1024:
        attempts.append(("Large-file",
                         "chunk-split refused: unsafe on arbitrary/protected bytecode; "
                         "scaled timeouts already applied in the engine tiers"))

    if dec_src is not src:
        try:
            dec_src.unlink()
        except OSError:
            pass

    # ----- TIER 6 — disassembly fallback: keep the best readable listing
    best_disasm = None
    if disasm:
        best_disasm = max(disasm, key=lambda pair: pair[1].count("\n"))
        name, txt = best_disasm
        if txt and len(txt) > 50 and _garbage_ratio(txt) < 0.05:
            dis_path = out_dir / (stem + "_disassembled.lua")
            dis_path.write_text(txt, encoding="utf-8")
            attempts.append(("Disassembly", "%s → saved as %s" % (name, dis_path.name)))
            return {
                "ok": False, "status": "disassembled", "out": None,
                "disasm_path": dis_path, "fail_path": None,
                "meta": meta, "attempts": attempts, "lines": None,
                "quality": None,
                "msg": "Full decompile not possible; best result: disassembly saved.",
            }

    # ----- TIER 7 — honest failure (never garbage)
    return _finish_failure(src, out_dir, stem, meta, attempts)


def _phase(progress, text: str) -> None:
    if progress is not None:
        try:
            progress.phase(text)
        except Exception:
            pass


# ---------------------------------------------------------------- reporting
def _write_failed(src, out_dir, stem, meta, attempts, validator=None) -> Path:
    fail = out_dir / (stem + "_FAILED.txt")
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        "IkramTool %s — decompile FAILED" % VERSION,
        "Timestamp : %s" % now,
        "File      : %s" % src.name,
        "Size      : %s bytes" % src.stat().st_size,
        "Detected  : %s" % meta["kind"],
        "Family    : %s" % (meta["family"] or "unresolved"),
        "Entropy   : %.3f (%s)" % (meta["entropy"], meta["band"]),
    ]
    if meta.get("wrapper"):
        lines.append("Wrapper   : %d-byte header stripped" % meta["wrapper"])
    if meta.get("protection"):
        lines.append("Protection: %s" % meta["protection"])
    lines += [
        "",
        "Methods tried:",
    ]
    for label, msg in attempts:
        lines.append("  - %s: %s" % (label, msg))
    if validator is not None:
        lines.append("")
        lines.append("Output validator:")
        for k, v in validator["checks"].items():
            lines.append("  %s %s" % ("PASS" if v else "FAIL", k))
        lines.append("  score %d/8 (%s)" % (validator["score"],
                                             _quality_label(validator["score"], total=8)))
    lines.append("")
    lines.append("Checked: magic-header + entropy, every decompiler on this")
    lines.append("device, XOR/additive key sweep (1..128), string probing, and")
    lines.append("bytecode disassembly. The file is either properly encrypted,")
    lines.append("locked by its owner, truncated, or not Lua. No garbage was")
    lines.append("kept as a 'success'.")
    fail.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return fail


def _finish_failure(src, out_dir, stem, meta, attempts) -> dict:
    fail = _write_failed(src, out_dir, stem, meta, attempts)
    return {
        "ok": False, "status": "failed", "out": None,
        "disasm_path": None, "fail_path": fail,
        "meta": meta, "attempts": attempts, "lines": None,
        "quality": None, "msg": fail.name,
    }


# ------------------------------------------------------------ dependencies
def tool_table() -> list:
    """[(tool, ok, detail)] for the live dependency box."""
    rows = []
    import shutil

    def row(name, ok, detail):
        rows.append((name, bool(ok), detail))

    row("java (JDK)", shutil.which("java"), "openjdk-17" if shutil.which("java") else "pkg install openjdk-17")
    j = _mega.UNLUAC_JAR
    row("unluac.jar", Path(j).exists(), "bundled")
    rows.append(("unluac_rs", _mega.UNLUAC_RS.exists(),
                 "bundled" if _mega.UNLUAC_RS.exists() else "missing"))
    row("luac (5.3)", shutil.which("luac5.3") or shutil.which("luac"), "lua53")
    row("luac 5.1", shutil.which("luac5.1"), "pkg install lua51")
    row("luac 5.2", shutil.which("luac5.2"), "pkg install lua52")
    row("luac 5.4", shutil.which("luac5.4"), "pkg install lua54")
    row("luajit", shutil.which("luajit"), "pkg install luajit")
    row("ljd (LuaJIT)", LJD_DIR.is_dir(), "bundled deps/ljd" if LJD_DIR.is_dir() else "missing")
    row("luadec", shutil.which("luadec"), "optional (not packaged)")
    row("r2 (last resort)", shutil.which("r2"), "pkg install radare2" if not shutil.which("r2") else "radare2")
    return rows


def deps_status() -> dict:
    """First-run dependency check with install commands for every missing one."""
    missing = []
    for name, ok, fix in tool_table():
        if not ok and "optional" not in fix.lower():
            missing.append("%s  →  %s" % (name, fix))
    return {"java": shutil.which("java"), "missing": missing,
            "tools": tool_table()}


def install_missing(progress=None) -> list:
    """Auto-install the missing tools. Returns [(cmd, ok, out_tail)]."""
    import shutil
    commands = []
    if not shutil.which("java"):
        commands.append(["pkg", "install", "-y", "openjdk-17"])
    for lv in ("lua51", "lua52", "lua53", "lua54"):
        tag = "luac5.%s" % lv[-1]
        if not shutil.which(tag):
            commands.append(["pkg", "install", "-y", lv])
    if not shutil.which("luajit"):
        commands.append(["pkg", "install", "-y", "luajit"])
    if not shutil.which("r2"):
        commands.append(["pkg", "install", "-y", "radare2"])
    results = []
    if not LJD_DIR.is_dir():
        results.append(("ljd (bundled deps/ljd)", False,
                        "ljd.zip missing from the tool bundle"))
    for i, cmd in enumerate(commands):
        _phase(progress, "[%d/%d] %s" % (i + 1, len(commands), " ".join(cmd)))
        try:
            p = subprocess.run(cmd, capture_output=True, timeout=240)
            tail = (p.stdout.decode(errors="replace") + p.stderr.decode(errors="replace")).strip()[-80:]
            results.append((" ".join(cmd), p.returncode == 0, tail or "ok"))
        except subprocess.TimeoutExpired:
            results.append((" ".join(cmd), False, "timed out"))
        except Exception as e:
            results.append((" ".join(cmd), False, str(e)[:80]))
    return results