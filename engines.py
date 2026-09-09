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
from pathlib import Path

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
    return _ue4mod


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


def _ue4_meta(pakf):
    p = ue4mod().Ue4Pak(pakf)
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
        out = Path(out_dir)
        repak = find_repak()
        if repak is not None:
            aes_args = ["-a", aes_key] if aes_key else []
            try:
                _run([repak, "unpack", pakf, "--output", out, "-f"] + aes_args, log)
                return sum(1 for p in out.rglob("*") if p.is_file())
            except Exception as e:
                log(f"  repak tried, python fallback: {e}")
        p = ue4mod().Ue4Pak(pakf, aes_key=aes_key)
        if p.files() and getattr(p, "encrypted_index", False) and not aes_key:
            log("  (pak index encrypted -- pass AES key)")
        log("  engine: python-ue4 (standard UE4)")
        return p.extract_all(str(out))

    raise ValueError(f"Unknown pak format (no UE4/Tencent magic): {pakf.name}")


def inject_pak(pakf, target, data, out, kind=None, aes_key=None, log=None):
    """Inject one file into a pak. Returns count of injected entries."""
    log = log or (lambda *a, **k: None)
    pakf = Path(pakf)
    kind = kind or detect_kind(pakf)
    target = target.strip("/").replace("\\", "/")

    if kind == "tencent":
        log("  engine: ikram-custom (tencent)")
        with pakmod().PakReader(pakf) as pak:
            existing = pak.full_paths()
            force = target.lower() not in {k.strip("/").lower() for k in existing}
            return pakmod().PakWriter(pak).inject_files(
                [(target, (data, None, Path(target).stem))], str(out),
                force_add=force, target_path=str(Path(target).parent))

    if kind == "ue4":
        version, _, _ = _ue4_meta(pakf)
        repak = find_repak()
        if isinstance(version, int) and version >= 10 and repak is not None:
            log("  engine: repak-inject (UE4 v10+)")
            return _repak_inject(pakf, target, data, out, aes_key, log)
        log("  engine: python-ue4 (standard UE4)")
        p = ue4mod().Ue4Pak(pakf, aes_key=aes_key)
        was_present = target in p.files()
        if was_present:
            n = p.repack(str(out), replacements={target: data})
        else:
            n = p.repack(str(out), add_files={target: data})
        return 1 if n else 0


def inject_pak_many(pakf, items, out, kind=None, aes_key=None, log=None):
    """Inject many files into a pak in one pass and return how many were placed.

    items: list of (target_path, file_data). Targets are mount-relative,
    folders are created automatically, existing files are replaced.
    """
    log = log or (lambda *a, **k: None)
    pakf = Path(pakf)
    kind = kind or detect_kind(pakf)

    if kind == "tencent":
        log("  engine: ikram-custom (tencent)")
        edits = []
        with pakmod().PakReader(pakf) as pak:
            existing = {k.strip("/").lower() for k in pak.full_paths()}
            for t, data in items:
                t = t.strip("/").replace("\\", "/")
                edits.append((t, (data, None, Path(t).stem)))
            return pakmod().PakWriter(pak).inject_files(
                edits, str(out), force_add=True,
                target_path=None)

    if kind == "ue4":
        version, _, _ = _ue4_meta(pakf)
        repak = find_repak()
        n = 0
        if isinstance(version, int) and version >= 10 and repak is not None:
            log("  engine: repak-inject (UE4 v10+)")
            for t, data in items:
                n += _repak_inject(pakf, t, data, out, aes_key, log)
        else:
            log("  engine: python-ue4 (standard UE4)")
            p = ue4mod().Ue4Pak(pakf, aes_key=aes_key)
            for t, data in items:
                if t in p.files():
                    n += p.repack(str(out), replacements={t: data}) or 0
                else:
                    n += p.repack(str(out), add_files={t: data}) or 0
        return n

    raise ValueError(f"Unknown pak format (no UE4/Tencent magic): {pakf.name}")


def _repak_inject(pakf, target, data, out, aes_key, log):
    repak = find_repak()
    if repak is None:
        raise RuntimeError("repak not installed -- " + repak_hint())
    version, mount_point, compression_u8 = _ue4_meta(pakf)
    with tempfile.TemporaryDirectory(prefix="ikram_repak_") as tmp:
        tmpdir = Path(tmp)
        aes_args = ["-a", aes_key] if aes_key else []
        _run([repak, "unpack", pakf, "--output", tmpdir, "-f"] + aes_args, log)
        rel = target.strip("/").replace("\\", "/")
        dst = tmpdir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(data)
        out = Path(out)
        out.parent.mkdir(parents=True, exist_ok=True)
        if out.exists():
            out.unlink()
        _run([repak, "pack", tmpdir, "--mount-point", mount_point,
              "--version", _repak_version_str(version, compression_u8),
              "--compression", "Zlib", out], log)
    return 1


def repack_folder(pakf, edit_dir, out, kind=None, aes_key=None, log=None):
    """Repack a whole edited folder tree into a pak. Returns file count."""
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
            return pakmod().PakWriter(pak).inject_files(edits, str(out), force_add=True)

    if kind == "ue4":
        version, mount_point, compression_u8 = _ue4_meta(pakf)
        repak = find_repak()
        if repak is not None:
            log("  engine: repak-pack (standard UE4)")
            with tempfile.TemporaryDirectory(prefix="ikram_repack_") as tmp:
                stage = Path(tmp) / "tree"
                stage.mkdir(parents=True, exist_ok=True)
                aes_args = ["-a", aes_key] if aes_key else []
                try:
                    _run([repak, "unpack", pakf, "--output", stage, "-f"] + aes_args, log)
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
            return sum(1 for p in edit_dir.rglob("*") if p.is_file())

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
        return p.repack(str(out), replacements=repl, add_files=adds)

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