"""Engine dispatch layer for the shipped IkramTool PAK TOOL.

Loads the SAME flat compiled runtime modules the tool already runs on
(pak.pyc / ue4.pyc via importlib) and implements the fallback chains
from paktoolproject.txt behind the three PAK TOOL options:

  UNPACK : tencent -> ikram-custom
           ue4     -> repak -> python-ue4 (Ue4Pak + AES key)
  INJECT : tencent -> ikram-custom (PakWriter.inject_files)
           ue4     -> repak-inject (v10+) -> python-ue4 (Ue4Pak.repack)
  REPACK : tencent -> ikram-custom (PakWriter full-tree)
           ue4     -> repak-pack -> python-ue4 (Ue4Pak.repack)

Works in the shipped flat runtime (ikram_patch.py entry) with no
.pyc recompile needed -- engines.py ships as source.
"""
import importlib.util
import os
import shutil
import tempfile
from pathlib import Path, PurePath

MAGIC_BYTES = b"\xe1\x12\x6f\x5a"
REPAK_TIMEOUT = 1800
TOOL_DIR = Path(__file__).resolve().parent

REPAK_CANDIDATES = [
    Path.home() / ".cargo" / "bin" / "repak",
    TOOL_DIR / "repak",
    TOOL_DIR / "engines" / "repak",
]
QUICKBMS_CANDIDATES = [
    Path.home() / "quickbms" / "quickbms",
    Path.home() / "bin" / "quickbms",
]
U4PAK_CANDIDATES = [
    Path.home() / ".local" / "bin" / "u4pak",
    Path.home() / "bin" / "u4pak",
]

_pakmod = None
_ue4mod = None


def _load_flat(name):
    """Load a flat compiled module (pak.pyc / ue4.pyc) like ikram_patch does."""
    spec = importlib.util.spec_from_file_location(name, TOOL_DIR / f"{name}.pyc")
    if spec is None or spec.loader is None:
        raise ImportError(f"{name}.pyc not found in {TOOL_DIR}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def pakmod():
    global _pakmod
    if _pakmod is None:
        _pakmod = _load_flat("pak")
    return _pakmod


def ue4mod():
    global _ue4mod
    if _ue4mod is None:
        _ue4mod = _load_flat("ue4")
        _patch_ue4module(_ue4mod)
    return _ue4mod


def _patch_ue4module(mod):
    """Fix compiled ue4.pyc flaws without recompiling:

    1. _parse_full_directory_index read the FDI blob RAW and never
       decrypted it when the pak index is encrypted -> crash on
       v10+ encrypted paks. Mirror repak: seek fdi_off, read
       fdi_size, AES-ECB decrypt when footer.encrypted.
    2. Same method joined paths as dir_name.strip('/') + fname,
       wiping the trailing '/' -> 'ContentLuagame.lua'. Mirror
       repak: prefix-strip only, keep the separator.
    """
    try:
        aes_ecb_decrypt = mod.aes_ecb_decrypt
        orig = mod.Ue4Pak._parse_full_directory_index
    except Exception:
        return
    import struct as _st

    def _parse_full_directory_index(self, fdi_off, fdi_size, non_encoded, encoded_blob):
        blob = bytes(self.content[fdi_off:fdi_off + fdi_size])
        if self.encrypted_index:
            if not self.aes_key:
                raise ValueError("Index encrypted — AES key required (FDI)")
            blob = aes_ecb_decrypt(blob, self.aes_key)
        r = mod.Reader(blob)
        dir_count = r.u4()
        for _ in range(dir_count):
            dir_name = r.fstring()
            file_count = r.u4()
            for _ in range(file_count):
                file_name = r.fstring()
                encoded_offset = _st.unpack_from("<i", blob, r.c)[0]
                r.c += 4
                d = dir_name
                if d.startswith("/"):
                    d = d[1:]
                path = d + file_name
                if encoded_offset == -2147483648:
                    continue
                if encoded_offset >= 0:
                    er = mod.Reader(encoded_blob, encoded_offset)
                    self.entries[path] = mod.read_encoded_entry(er, self.version)
                else:
                    self.entries[path] = non_encoded[(-encoded_offset) - 1]
        return None

    mod.Reader_original_fdi = orig
    mod.Ue4Pak._parse_full_directory_index = _parse_full_directory_index


def _which_try(first, *extra):
    for cmd in (first,) + extra:
        p = shutil.which(cmd)
        if p:
            return Path(p)
    return None


def find_repak():
    p = _which_try("repak")
    if p:
        return p
    for c in REPAK_CANDIDATES:
        if c.is_file() and os.access(c, os.X_OK):
            return c
    return None


def find_quickbms():
    p = _which_try("quickbms")
    if p:
        return p
    for c in QUICKBMS_CANDIDATES:
        if c.is_file() and os.access(c, os.X_OK):
            return c
    return None


def find_u4pak():
    p = _which_try("u4pak")
    if p:
        return p
    for c in U4PAK_CANDIDATES:
        if c.is_file() and os.access(c, os.X_OK):
            return c
    return None


def repak_hint():
    return ("repak install: pkg install rust && cargo install repak_cli "
            "--git https://github.com/trumank/repak --no-default-features --locked")


def detect_kind(path):
    """'ue4' | 'tencent' | None from magic bytes."""
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 4096))
            tail = f.read(4096)
    except Exception:
        return None
    if MAGIC_BYTES in tail:
        return "ue4"
    if size >= 45 and len(tail) >= 44:
        try:
            import struct
            magic = struct.unpack_from("<I", tail[-44:-40])[0]
            if magic ^ pakmod().pc.zuc_keystream()[2] == 0x4C515443:
                return "tencent"
        except Exception:
            return None
    return None


def _run(args, log=None, timeout=REPAK_TIMEOUT):
    import subprocess as sp
    log = log or (lambda *a, **k: None)
    log("  engine: {} ...".format(" ".join(str(a) for a in args[:3])))
    r = sp.run([str(a) for a in args], capture_output=True, timeout=timeout)
    if r.stdout:
        log("  " + r.stdout.decode(errors="replace").strip())
    if r.returncode != 0:
        raise RuntimeError(
            "repak failed: "
            + (r.stderr.decode(errors="replace").strip()[-300:] or f"exit {r.returncode}")
        )
    return r


def _ue4_meta(pakf, aes_key=None):
    aes_key = _resolve_ue4_key(pakf, aes_key or None, (lambda *a, **k: None))
    p = ue4mod().Ue4Pak(pakf, aes_key=aes_key)
    v = getattr(p, "version", None) or getattr(p, "version_num", None)
    mount = getattr(p, "mount_point", None) or "../../../"
    comp = getattr(p, "compression_u8", None)
    return v, mount, comp


def _repak_version_str(version, compression_u8):
    if version == 8:
        return "V8A" if compression_u8 else "V8B"
    if isinstance(version, int) and 1 <= version <= 11:
        return f"V{version}"
    return "V8B"


# ---------------------------------------------------------------------------
# V112 — multi-AES-key auto-try + working-key persistence (PakEngine keys).
# Keys are stored OUTSIDE the tool dir (~/.config/ikramtool/pak_keys.json) so
# a clean-replace update never wipes a key the user already made to work.
# ---------------------------------------------------------------------------
DEFAULT_UE4_KEYS = [
    # PUBG/BGMI global UE4 AES key (shipped default).
    "8A75AFDF1C74AB55B79DC1DD4ABE4B01360A059D77F243EF4EFADA41A59D71A0",
]

KEY_STORE = Path(
    os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config")
) / "ikramtool" / "pak_keys.json"


def _khex(key):
    """Hex key (0x/-/space tolerant) -> lowercase hex, or None."""
    if key is None:
        return None
    h = str(key).strip().replace("0x", "").replace("0X", "").replace("-", "").replace(" ", "")
    try:
        b = bytes.fromhex(h)
    except Exception:
        return None
    return b.hex().lower() if len(b) in (16, 24, 32) else None


def _load_saved_keys():
    try:
        import json
        if KEY_STORE.is_file():
            d = json.loads(KEY_STORE.read_text(errors="ignore"))
            return [_khex(k) for k in dict.fromkeys(d.get("keys", ())) if _khex(k)]
    except Exception:
        pass
    return []


def _save_keys(keys):
    try:
        import json
        KEY_STORE.parent.mkdir(parents=True, exist_ok=True)
        KEY_STORE.write_text(json.dumps({"keys": keys}, indent=1))
    except Exception:
        pass


def _key_candidates(aes_key=None):
    """Ordered, deduped key list: explicit > saved > shipped defaults."""
    out = []
    if aes_key:
        out.append(_khex(aes_key))
    for k in _load_saved_keys() + DEFAULT_UE4_KEYS:
        h = _khex(k)
        if h and h not in out:
            out.append(h)
    return out


def _try_ue4_key(pakf, key_hex):
    """True when this key parses the pak AND its first entries read back."""
    key = bytes.fromhex(key_hex)
    p = ue4mod().Ue4Pak(pakf, aes_key=key)
    ents = list(p.files())
    if not ents:
        return False
    checked = 0
    for path in ents[:3]:
        try:
            data = p.read_file(path)
        except Exception:
            return False
        if not data:
            return False
        checked += 1
    return checked > 0


def _resolve_ue4_key(pakf, aes_key=None, log=None):
    """AES key for a UE4 pak. None given -> auto-try saved-then-default keys,
    persist whichever one works first. Falls back to the shipped default so
    existing behaviour is never a regression."""
    log = log or (lambda *a, **k: None)
    if _khex(aes_key):
        return aes_key
    if not _khex(DEFAULT_UE4_KEYS[0]):
        return aes_key
    cands = _key_candidates(aes_key)
    tried = []
    for h in cands[1:] if aes_key else cands:
        tried.append(h)
        try:
            if _try_ue4_key(pakf, h):
                saved = _load_saved_keys()
                if not saved or saved[0] != h:
                    _save_keys([h] + [s for s in saved if s != h])
                log("  ue4 key: auto -> %s… (saved)" % h[:8])
                return h
        except Exception:
            continue
    log("  ue4 key: none matched (%d tried) — default fallback" % len(tried))
    return _khex(aes_key) or DEFAULT_UE4_KEYS[0]


def _oodle_stats(pakf, aes_key=None):
    """Count Oodle-compressed (method slot) entries.
    0 for uncompressed/none; -1 when the whole pak is unreadable."""
    try:
        p = ue4mod().Ue4Pak(pakf, aes_key=aes_key)
        n = 0
        for e in __import__("itertools").chain(
            getattr(p, "entries", {}).values(), ()
        ):
            slot = getattr(e, "compression_slot", None)
            if slot is None:
                continue
            try:
                if p._compression_method(slot) == "oodle":
                    n += 1
            except Exception:
                continue
        return n
    except Exception:
        return -1


def unpack_pak(pakf, out_dir, kind=None, aes_key=None, log=None):
    """Unpack any pak -> out_dir. Returns file count."""
    log = log or (lambda *a, **k: None)
    pakf = Path(pakf)
    kind = kind or detect_kind(pakf)

    if kind == "tencent":
        log("  engine: ikram-custom (tencent)")
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        return pakmod().unpack_pak(pakf, out_dir, log=log)

    if kind == "ue4":
        aes_key = _resolve_ue4_key(pakf, aes_key or None, log)
        try:
            oodle = _oodle_stats(pakf, aes_key)
            if oodle:
                log(
                    "  ⚠ %d Oodle-compressed entries — repak/python are "
                    "Zlib-only, those entries may be partial/dropped"
                    % oodle
                )
        except Exception:
            pass
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        repak = find_repak()
        if repak is not None:
            aes_args = ["-a", aes_key] if aes_key else []
            try:
                _run([repak] + aes_args + ["unpack", pakf, "--output", out, "-f"], log)
                return sum(1 for p in out.rglob("*") if p.is_file())
            except Exception as e:
                log(f"  repak tried, python fallback: {e}")
        p = ue4mod().Ue4Pak(pakf, aes_key=aes_key)
        if p.files() and getattr(p, "encrypted_index", False) and not aes_key:
            log("  (pak index encrypted -- pass AES key)")
        log("  engine: python-ue4 (standard UE4)")
        return p.extract_all(str(out))

    raise ValueError(f"Unknown pak format (no UE4/Tencent magic): {pakf.name}")


def _staged_files(edit_dir):
    """The exact file set a repack stages — dotfiles are never packed."""
    return [p for p in sorted(Path(edit_dir).rglob("*"))
            if p.is_file() and not p.name.startswith(".")]


def _count_packed(out, kind, aes_key, log):
    """How many entries the pak that was just written actually holds.

    The number reported to the user has to describe the OUTPUT, not the
    folder that was handed in: the python-ue4 writer reports only the files
    it changed, so an edit that rewrote identical bytes came back as 0 even
    though the pak was rebuilt fine. Reading the finished pak back is the
    only count that cannot lie. If it cannot be read, the staged count is
    the honest fallback.
    """
    out = Path(out)
    try:
        if kind == "tencent":
            with pakmod().PakReader(out) as pak:
                return len(pak.full_paths())
        p = ue4mod().Ue4Pak(out, aes_key=aes_key)
        return len(p.files())
    except Exception as exc:
        log("  (entry count fell back to the staged list: %s)" % exc)
        return None


def _packed_count(out, kind, aes_key, log, fallback):
    """Entries in the pak that was written, or `fallback` if unreadable."""
    n = _count_packed(out, kind, aes_key, log)
    return fallback if n is None else n


def repack_folder(pakf, edit_dir, out, kind=None, aes_key=None, log=None):
    """Repack a whole edited folder tree into a pak. Returns file count.

    Every engine path returns the same thing: the number of entries in the
    pak that was written, so "N files repacked" means the same thing no
    matter which engine did the work.
    """
    log = log or (lambda *a, **k: None)
    pakf = Path(pakf)
    edit_dir = Path(edit_dir)
    kind = kind or detect_kind(pakf)

    if kind == "tencent":
        log("  engine: ikram-custom (tencent)")
        with pakmod().PakReader(pakf) as pak:
            existing = pak.full_paths()
            # The extracted tree carries the mount-point path (e.g.
            # ShadowTrackerExtra/...) while full_paths() keys are
            # mount-relative. Normalise before matching so exact path
            # lookup wins and duplicate basenames don't collide.
            mount_rel = str(getattr(pak, "mount_point", "") or "")
            mount_dir = ""
            if mount_rel.count("/") >= 2:
                mount_dir = mount_rel.rstrip("/").rsplit("/", 1)[-1] + "/"
            edits = []
            for p in sorted(edit_dir.rglob("*")):
                if not p.is_file() or p.name.startswith("."):
                    continue
                rel = str(p.relative_to(edit_dir)).replace("\\", "/")
                rel = rel.lstrip("/")
                if rel.startswith(mount_dir):
                    rel = rel[len(mount_dir):]
                target = None
                if rel in existing:
                    target = rel
                else:
                    for fp in existing:
                        if fp.lower() == rel.lower():
                            target = fp
                            break
                if target is None:
                    for fp in existing:
                        if Path(fp).name.lower() == p.name.lower():
                            target = fp
                            break
                if target is None:
                    target = rel
                edits.append((target, (p.read_bytes(), None, p.stem)))
            pakmod().PakWriter(pak).inject_files(edits, str(out), force_add=True)
            return _packed_count(out, kind, aes_key, log, len(edits))

    if kind == "ue4":
        aes_key = _resolve_ue4_key(pakf, aes_key or None, log)
        version, mount_point, compression_u8 = _ue4_meta(pakf, aes_key=aes_key)
        repak = find_repak()
        if repak is not None:
            log("  engine: repak-pack (standard UE4)")
            with tempfile.TemporaryDirectory(prefix="ikram_repack_") as tmp:
                stage = Path(tmp) / "tree"
                stage.mkdir(parents=True, exist_ok=True)
                aes_args = ["-a", aes_key] if aes_key else []
                try:
                    _run([repak] + aes_args + ["unpack", pakf, "--output", stage, "-f"], log)
                except Exception as e:
                    log(f"  repak unpack failed ({e}) -- python fallback")
                    p0 = ue4mod().Ue4Pak(pakf, aes_key=aes_key)
                    p0.extract_all(str(stage))
                for p in sorted(edit_dir.rglob("*")):
                    if not p.is_file() or p.name.startswith("."):
                        continue
                    rel = str(p.relative_to(edit_dir)).replace("\\", "/")
                    dst = stage / rel
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    dst.write_bytes(p.read_bytes())
                out = Path(out)
                out.parent.mkdir(parents=True, exist_ok=True)
                if out.exists():
                    out.unlink()
                _run([repak, "pack", stage, "--mount-point", mount_point,
                      "--version", _repak_version_str(version, compression_u8),
                      "--compression", "Zlib", out], log)
            return _packed_count(out, kind, aes_key, log,
                                 len(_staged_files(edit_dir)))

        log("  engine: python-ue4 (standard UE4)")
        p = ue4mod().Ue4Pak(pakf, aes_key=aes_key)
        existing = p.files()
        repl, adds = {}, {}
        for fp in sorted(edit_dir.rglob("*")):
            if not fp.is_file() or fp.name.startswith("."):
                continue
            rel = str(fp.relative_to(edit_dir)).replace("\\", "/")
            data = fp.read_bytes()
            if rel in existing:
                repl[rel] = data
            else:
                adds[rel] = data
        p.repack(str(out), replacements=repl, add_files=adds)
        return _packed_count(out, kind, aes_key, log, len(repl) + len(adds))

    raise ValueError(f"Unknown pak format (no UE4/Tencent magic): {pakf.name}")


def list_pak_paths(pakf, aes_key=None, log=None):
    """Every file path declared by a pak, without extracting anything.

    Used by the Costom PAK option, which needs the template's file list to
    build a new pak that declares the same names with empty contents.
    """
    log = log or (lambda *a, **k: None)
    pakf = Path(pakf)
    kind = detect_kind(pakf)
    if kind == "tencent":
        with pakmod().PakReader(pakf) as pak:
            return sorted(pak.full_paths())
    if kind == "ue4":
        aes_key = _resolve_ue4_key(pakf, aes_key or None, log)
        p = ue4mod().Ue4Pak(pakf, aes_key=aes_key)
        return sorted(p.files())
    raise ValueError(f"Unknown pak format (no UE4/Tencent magic): {pakf.name}")


def pack_folders(all_paths):
    """Every distinct folder that holds a file, shallowest first.

    A pak stores one flat list of full paths, so a folder is just a shared
    prefix. Offering the prefixes is what lets the Costom PAK option present a
    numbered FOLDER list instead of a wall of file names.
    """
    folders = set()
    for p in all_paths:
        parts = p.replace("\\", "/").split("/")
        for i in range(1, len(parts)):
            folders.add("/".join(parts[:i]))
    return sorted(folders, key=lambda f: (f.count("/"), f))


def _read_bodies(pakf, kind, names, aes_key, log):
    """Real file contents pulled back out of the template pack.

    Only used when the user typed a path, which the menu promises is copied
    with its contents rather than stored empty.
    """
    bodies = {}
    if kind == "tencent":
        with pakmod().PakReader(pakf) as pak:
            # PakReader keeps a {path: entry} map from the index; read_entry
            # needs the entry object, not the name.
            table = {}
            for attr in ("files", "dirs"):
                src = getattr(pak, attr, None)
                if isinstance(src, dict):
                    table.update(src)
            for name in names:
                entry = table.get(name) or table.get(PurePath(name))
                if entry is None:
                    raise ValueError("entry vanished from the template: %s" % name[:60])
                bodies[name] = pak.read_entry(entry)
            return bodies
    p = ue4mod().Ue4Pak(pakf, aes_key=_resolve_ue4_key(pakf, aes_key or None, log))
    for name in names:
        bodies[name] = p.read_file(name)
    return bodies


def costom_pak(pakf, out, paths_wanted, aes_key=None, log=None, copy=False):
    """Build a pak that DECLARES `paths_wanted` into a new pack.

    This is the Costom PAK trick: the game reads the index, sees the files it
    expects, and creates them itself, so the tool never has to ship real
    content for them. Bodies are written as zero bytes on purpose — that is
    the whole point of the option, not a bug.

    `copy=True` stores each wanted file's real bytes instead. The menu offers
    that when the user types a path, because a typed path is a request to pull
    that file (and anything under it) across as it already is.
    """
    log = log or (lambda *a, **k: None)
    pakf = Path(pakf)
    out = Path(out)
    kind = detect_kind(pakf)
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()
    wanted = list(paths_wanted)
    if copy:
        log("  copying %d file(s) out of the template" % len(wanted))
        bodies = _read_bodies(pakf, kind, wanted, aes_key, log)
    else:
        bodies = {q: b"" for q in wanted}

    if kind == "tencent":
        log("  engine: ikram-custom (tencent) — %s costom pak"
            % ("copied" if copy else "empty-body"))
        with pakmod().PakReader(pakf) as pak:
            edits = [(p, (bodies.get(p, b""), None, PurePath(p).name)) for p in wanted]
            return pakmod().PakWriter(pak).inject_files(
                edits, str(out), force_add=True)

    if kind == "ue4":
        aes_key = _resolve_ue4_key(pakf, aes_key or None, log)
        p = ue4mod().Ue4Pak(pakf, aes_key=aes_key)
        # delete= is what makes a subset: without it repack() keeps every
        # original entry, so asking for one path would still yield the whole
        # pak. Never route this through `repak pack`: repak 0.2.3 writes a
        # corrupt index when a pack mixes a 0-byte entry with other entries,
        # which is exactly the shape a costom pak is.
        log("  engine: python-ue4 (standard UE4) — %s costom pak"
            % ("copied" if copy else "empty-body"))
        return p.repack(str(out),
                        add_files={q: bodies[q] for q in wanted},
                        delete=[q for q in sorted(p.files()) if q not in wanted])

    raise ValueError(f"Unknown pak format (no UE4/Tencent magic): {pakf.name}")


def engine_status():
    out = []
    out.append(f"custom-tencent: ready (pak.pyc)")
    r = find_repak()
    out.append(f"repak: {r.name if r else 'MISSING -- ' + repak_hint()}")
    q = find_quickbms()
    out.append(f"quickbms: {q.name if q else 'not installed (optional fallback)'}")
    u = find_u4pak()
    out.append(f"u4pak: {u.name if u else 'not installed (optional fallback)'}")
    return "\n".join(out)