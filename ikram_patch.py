import importlib.util
import shutil
import sys
import tempfile
from pathlib import Path

_TOOL_DIR = Path(__file__).resolve().parent
if str(_TOOL_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOL_DIR))

spec = importlib.util.spec_from_file_location("ikram", _TOOL_DIR / "ikram.pyc")
ikram = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ikram)

import engines as _engines
import assetprocs as _assets

# ---- real DROP/RESULT override (installed layout: .engine/ ke PARENT me
# drop/result lowercase; repo layout: DROP/RESULT. compiled module points at
# its own __file__ dir = .engine/DROP, which must NEVER have user data).
import paths as _paths
for _name, _val in (
    ("DROP", _paths.DROP_DIR),
    ("DROP_PAK", _paths.DROP_PAK),
    ("DROP_LUA", _paths.DROP_LUA),
    ("DROP_INJ", _paths.DROP_INJECT),
    ("RESULT", _paths.RESULT_DIR),
):
    setattr(ikram, _name, _val)

for _d in (
    ikram.DROP,
    ikram.DROP_INJ,
    ikram.DROP_LUA,
    ikram.DROP_PAK,
    ikram.RESULT,
):
    _d.mkdir(parents=True, exist_ok=True)
for _sub in ("injected", "extracted", "lua", "processed", "CostomPak", "Repacked"):
    (ikram.RESULT / _sub).mkdir(parents=True, exist_ok=True)


def _purge_legacy_repacked_folders():
    """Double-repack bug, folder side: older releases + the stale one-liner
    install.sh created the LOWERCASE RESULT/repacked/ twin (compiled engine
    era wrote RESULT+'repacked'). Android's case-sensitive FS then keeps
    BOTH 'Repacked' and 'repacked' forever -> "Result/ me 2 folders". Remove
    every leftover file under the legacy twin, then the empty folder."""
    legacy = ikram.RESULT / "repacked"
    if not legacy.is_dir():
        return
    try:
        for p in list(legacy.iterdir()):
            if p.is_file():
                p.unlink(missing_ok=True)
            elif p.is_dir():
                shutil.rmtree(p, ignore_errors=True)
        legacy.rmdir()
    except OSError:
        pass


_purge_legacy_repacked_folders()

# ENTER (nothing typed) in Costom Pak -> full skeleton (all folders + all
# file names, zero-byte bodies). Sentinel returned by _pick_folders.
_SKELETON = "\x00_COSTOM_SKELETON_"

# ---- default Unreal Engine AES key for UE4 paks ---------------------------
# The user's real UE4 AES key. Auto-applied to UE4-standard paks across
# UNPACK / REPACK / INJECT (Ue4Pak.aes_key drives BOTH extract and repack).
# A blank AES key input now means "use this default" instead of "no key".
# Publg/tencent paks are NOT affected (their own SM4/SIMPLE crypto needs no
# key and runs through the `pak` module, not Ue4Pak). If you get a *different*
# pak set with its own key, just change this hex to that key.
DEFAULT_UE4_AES_KEY_HEX = (
    "8A75AFDF1C74AB55B79DC1DD4ABE4B01360A059D77F243EF4EFADA41A59D71A0"
)


def _ue4_key_bytes(hex_str=None):
    """Hex string (optionally 0x/- prefixed) -> AES-128/192/256 key bytes."""
    h = (hex_str or DEFAULT_UE4_AES_KEY_HEX).strip()
    h = h.replace("0x", "").replace("0X", "").replace("-", "").replace(" ", "")
    try:
        b = bytes.fromhex(h)
    except Exception:
        return None
    return b if len(b) in (16, 24, 32) else None


def _patch_ue4_default_key():
    """Make Ue4Pak use DEFAULT_UE4_AES_KEY when no aes_key is passed.

    Covers UNPACK, REPACK and INJECT at a single point because all three build
    Ue4Pak and Ue4Pak.aes_key drives both extract (read_encoded_entry) and
    repack (write_entry). The key is only ever applied to *encrypted* entries
    / encrypted index, so an edited or un-encrypted ue4 pak is untouched and
    the tencent (PUBG) path is untouched -> nothing breaks.
    """
    base = ikram.ue4mod.Ue4Pak
    if getattr(base, "_ikram_default_key_wrapped", False):
        return

    class _DefaultKeyUe4Pak(base):
        def __init__(self, file_path, aes_key=None):
            if not aes_key:
                aes_key = _ue4_key_bytes(DEFAULT_UE4_AES_KEY_HEX)
            super().__init__(file_path, aes_key)

    _DefaultKeyUe4Pak._ikram_default_key_wrapped = True
    ikram.ue4mod.Ue4Pak = _DefaultKeyUe4Pak
    # also expose the wrapper under the same module name for any direct use
    ikram.ue4mod.Ue4Pak._ikram_original = base


_patch_ue4_default_key()


def _unpack_one(pakf, out, log=None, progress=None):
    """Unpack a single pak -> out. Returns (n, kind). IETA: engines layer."""
    kind = ikram.detect_pak_type(pakf)
    if kind not in ("tencent", "ue4"):
        ikram._unsupported_pak(pakf, kind)
        return 0, kind
    ikram.console.print(
        "[bold {}]▸[/] {} [bold {}]({})[/]".format(
            ikram.CYAN, _PakName(pakf), ikram.MUTED, kind
        )
    )
    n = 0
    if kind == "ue4":
        # V112: engines layer auto-tries saved/shipped AES keys now; passing
        # None (instead of the default) lets a user's working key win first.
        aes_key = None
    else:
        aes_key = None
    if log is None or progress is None:
        ui = ikram._ProgressUI(title="📦 {}".format(_PakName(pakf)))
        with ui:
            n = _engines.unpack_pak(pakf, out, kind=kind, aes_key=aes_key, log=ui.log)
    else:
        n = _engines.unpack_pak(pakf, out, kind=kind, aes_key=aes_key, log=log)
    return n, kind

def _PakName(pakf):
    try:
        return Path(pakf).name
    except Exception:
        return str(pakf)


def _unique_out_dir(base):
    """base, base (1), base (2) ... — existing files are never overwritten."""
    out = Path(base)
    if not out.exists():
        return out
    i = 1
    while True:
        cand = out.parent / "{} ({})".format(out.name, i)
        if not cand.exists():
            return cand
        i += 1


def _unique_out_file(path):
    """Same as _unique_out_dir but for a single file — keep original name,
    suffix (1), (2) ... — existing files are never overwritten."""
    if not path.exists():
        return path
    i = 1
    while True:
        cand = path.with_name("{} ({}){}".format(path.stem, i, path.suffix))
        if not cand.exists():
            return cand
        i += 1


def _show_unpack_options(nfiles):
    t = ikram.Table(
        box=ikram.ROUNDED,
        show_header=False,
        pad_edge=False,
        border_style=ikram.BORDER,
        style="on {}".format(ikram.BG_DEEP),
    )
    t.add_column(width=3)
    t.add_column(style="bright_white")
    t.add_row(
        "[{}]1[/]".format(ikram._vip(0)),
        "[bold {}]UNPACK ONE FILE[/]  [bold {}]— choose 1 pak[/]".format(
            ikram.SUCCESS, ikram.MUTED
        ),
    )
    t.add_row(
        "[{}]2[/]".format(ikram._vip(1)),
        "[bold {}]UNPACK ALL {} FILES[/]  [bold {}]— every pak + asset in DROP/pak[/]".format(
            ikram.ACCENT, nfiles, ikram.MUTED
        ),
    )
    t.add_row(
        "[{}]0[/]".format(ikram._vip(2)),
        "[bold {}]CANCEL[/]".format(ikram.ERROR),
    )
    ikram.console.print(
        ikram.panel(t, title="📦 UNPACK MODE ({})".format(nfiles), box=ikram.ROUNDED, style=ikram._next_green())
    )


def _show_pak_list(paks):
    t = ikram.Table(
        box=ikram.ROUNDED,
        show_header=False,
        pad_edge=False,
        border_style=ikram.BORDER,
        style="on {}".format(ikram.BG_DEEP),
    )
    t.add_column(width=4)
    t.add_column(style="bright_white")
    t.add_column(style=ikram.MUTED, width=14)
    rows = 0
    for i, p in enumerate(paks, 1):
        try:
            size = p.stat().st_size
        except Exception:
            size = 0
        hsize = (
            "{:.1f} MB".format(size / 1048576)
            if size >= 1048576
            else "{:.0f} KB".format(size / 1024)
        )
        t.add_row("[{}]{}[/]".format(ikram._vip((i - 1) % 3), i), p.name, hsize)
        rows += 1
    title = "📦 FILES IN DROP/pak ({})".format(rows)
    ikram.console.print(
        ikram.panel(t, title=title, box=ikram.ROUNDED, style=ikram._next_green())
    )


def _choose_pak_index(n, paks, label):
    _show_pak_list(paks)
    ikram.console.print(
        "[bold {}]0 = cancel[/bold {}]".format(ikram.MUTED, ikram.MUTED)
    )
    while True:
        c = ikram.safe_input("\n[bold {}]> {} number (ENTER = auto first): [/]".format(ikram.INP, label))
        if not c:
            return 0
        if c.strip() == "0":
            return None
        try:
            i = int(c.strip()) - 1
            if 0 <= i < n:
                return i
        except ValueError:
            pass
        ikram.console.print("[bold {}]Invalid number — choose a number from 1 to {}.[/]".format(ikram.WARN, n))


def ensure_input_folder():
    """Pick only .pak files from DROP/pak (OBB support removed)."""
    paks = ikram.drop_files(ikram.DROP_PAK, [".pak"])
    if not paks:
        ikram.show_error(
            "No PAK files found in DROP/pak.\nAdd your .pak files there and try again."
        )
        ikram.pause()
        return None
    return ikram.pick_file(
        ikram.DROP_PAK,
        "📦 Choose a PAK file [bold {}](DROP/pak)[/bold {}]".format(ikram.MUTED, ikram.MUTED),
        [".pak"],
    )


def _is_pak(p):
    try:
        return Path(p).suffix.lower() == ".pak"
    except Exception:
        return False


def _drop_items():
    """ALL files in DROP/pak — .pak files are paks, everything else is assets/raw."""
    base = Path(ikram.DROP_PAK)
    if not base.is_dir():
        return []
    return [p for p in sorted(base.rglob("*"))
            if p.is_file() and not p.name.startswith(".")]


def _process_standalone(f):
    """Standalone non-pak file: raw copy -> RESULT/extracted/<name>/,
    processed sidecars -> RESULT/processed/<name>/."""
    f = Path(f)
    raw_dir = _unique_out_dir(ikram.RESULT / "extracted" / f.stem)
    raw_dir.mkdir(parents=True, exist_ok=True)
    proc_dir = ikram.RESULT / "processed" / f.stem
    _assets.process_file(f, proc_dir, log=ikram.console.print)
    shutil.copy2(f, raw_dir / f.name)
    ikram.console.print(
        "[bold {}]▸[/] [bold {}]([bold {}]raw copy[/])[/] → {}".format(
            ikram.CYAN, f.name, ikram.MUTED, raw_dir
        )
    )
    return raw_dir


def _auto_process_tree(out_dir, pakstem):
    """After pak unpack, the inner files are auto-processed:
    RESULT/extracted/<pak> -> sidecars RESULT/processed/<pak> (raw tree clean)."""
    proc_root = ikram.RESULT / "processed" / pakstem
    ui = ikram._ProgressUI(title="⚙ PROCESSING FILES")
    with ui:
        n, stats, errs = _assets.process_tree(out_dir, proc_root, log=ui.log, every=200)
    if n == 0:
        return 0
    rows = sorted(stats.items(), key=lambda x: -x[1])[:6]
    detail = "  ".join("[bold {}]{}:{}[/]".format(ikram._vip(i % 3), k, v) for i, (k, v) in enumerate(rows))
    ikram.console.print(
        "[bold {}]⚙ {} files processed[/] [bold {}]→ {}[/]  [bold {}]({} error)[/]".format(
            ikram.ACCENT, n, ikram.SUCCESS, proc_root, ikram.MUTED, len(errs)
        )
    )
    ikram.console.print("[bold {}]{}[/]".format(ikram.MUTED, detail))
    return n


def pak_extract():
    items = _drop_items()
    if not items:
        ikram.show_error(
            "No PAK/asset files found in DROP/pak.\nAdd your .pak OR asset files (uasset/uexp/locres/...) there and try again."
        )
        ikram.pause()
        return
    if ikram.eof_exit():
        return
    _show_unpack_options(len(items))
    mode = ikram.safe_input("\n[bold {}]> CHOOSE MODE: [/]".format(ikram.INP)).strip()
    if ikram.eof_exit():
        return
    if mode == "0":
        ikram.show_error("Cancelled — nothing unpacked.")
        ikram.pause()
        return

    if mode == "1":
        idx = _choose_pak_index(len(items), items, "UNPACK ONE")
        if idx is None:
            return
        f = items[idx]
        if _is_pak(f):
            out = _unique_out_dir(ikram.RESULT / "extracted" / f.stem)
            n, kind = _unpack_one(f, out)
            _finish_report(f, n, kind, out)
            if n > 0:
                _auto_process_tree(out, f.stem)
        else:
            ikram.console.print("\n[bold {}]=== PROCESSING {} ===[/]".format(ikram.ACCENT, f.name))
            try:
                raw_dir = _process_standalone(f)
                ikram.show_success(
                    "✔ {} unpacked/processed -> RESULT/extracted/{} (+ RESULT/processed/{})".format(
                        f.name, f.stem, f.stem
                    )
                )
            except Exception as e:
                ikram.report_error(e)
        ikram.pause()
        return

    if mode == "2":
        total_n = 0
        npak = 0
        nasset = 0
        any_fail = False
        for f in items:
            ikram.console.print("\n[bold {}]=== PROCESSING {} ===[/]".format(ikram.ACCENT, f.name))
            if _is_pak(f):
                npak += 1
                out = _unique_out_dir(ikram.RESULT / "extracted" / f.stem)
                n, kind = _unpack_one(f, out)
                total_n += n
                if n == 0:
                    any_fail = True
                    ikram.show_info("{} → 0 files (may be encrypted/unsupported)".format(f.name))
                else:
                    ikram.show_success("{} → {} files -> {}".format(f.name, n, out))
                    _auto_process_tree(out, f.stem)
            else:
                try:
                    _process_standalone(f)
                    nasset += 1
                except Exception as e:
                    any_fail = True
                    ikram.report_error(e)
        ikram.console.print("")
        if total_n + nasset > 0:
            ikram.show_success(
                "✔ Total: {} pak(s) unpacked ({} files) + {} asset file(s) processed".format(
                    npak, total_n, nasset
                )
            )
        else:
            ikram.show_error("0 files unpacked total (may be encrypted or unsupported).")
        ikram.pause()
        return

    ikram.invalid_choice()
    ikram.pause()


def _notify_tg(operation, msg, limit=800):
    """Graceful (non-raising) failure -> owner Telegram, same lazy-load as
    telemetry.pyc. Exceptions elsewhere already reach TG via report_error."""
    try:
        import importlib.util as _ilu
        _s = _ilu.spec_from_file_location("_tel_pak", _TOOL_DIR / "telemetry.pyc")
        _m = _ilu.module_from_spec(_s)
        _s.loader.exec_module(_m)
        _m.send_error(RuntimeError(msg[:limit]), extra=operation)
    except Exception:
        pass


def _finish_report(pakf, n, kind, out):
    if n == 0:
        ikram.show_error(
            "{}: 0 files extracted (may be encrypted or unsupported)".format(pakf.name)
        )
        _notify_tg("pak unpack (0 files)",
                   "{}({}): 0 files extracted".format(pakf.name, kind))
    else:
        ikram.show_success("✔ {} files unpacked -> {}".format(n, out))


_compiled_pak_inject = ikram.pak_inject


def pak_inject():
    """INJECT FILE gateway — runs the original compiled wizard UI
    (CHOOSE MODE, INJECT ONE/ALL, WHERE TO PUT THIS FILE?)."""
    return _compiled_pak_inject()


def pak_repack_folder():
    pakf = ensure_input_folder()
    if not pakf:
        return
    edit_dir = ikram.RESULT / "extracted" / pakf.stem
    if not edit_dir.is_dir():
        ikram.show_error(
            "Extracted folder not found: RESULT/extracted/{}\n"
            "First UNPACK this pak, then REPACK it.".format(pakf.stem)
        )
        ikram.pause()
        return
    out = ikram.RESULT / "Repacked" / "{}.pak".format(pakf.stem)
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()
    ikram.console.print('[bold {}]Repacking {} -> {} (auto folder: RESULT/extracted/{})'.format(
        ikram.WARN, pakf.name, out.name, pakf.stem))
    try:
        kind = ikram.detect_pak_type(pakf)
        aes_key = None
        if kind == "ue4":
            key = ikram.safe_input(
                "  [bold {}]-> {} AES key (ENTER = built-in default): [/]".format(
                    ikram.INP, pakf.name
                )
            )
            key = (key.strip() if key and key.strip() else "")
            aes_key = key or None
        n = _engines.repack_folder(pakf, edit_dir, out, kind=kind, aes_key=aes_key,
                                   log=ikram.console.print)
        # Double-repack fix: older releases wrote the result to the lowercase
        # RESULT/repacked/ twin; on case-sensitive Android both then coexist
        # ("Result/ shows TWO repacked files"). Purge the legacy twin so one
        # repack == exactly one output.
        _legacy = ikram.RESULT / "repacked" / "{}.pak".format(pakf.stem)
        if _legacy.exists():
            try:
                _legacy.unlink()
            except OSError:
                pass
        _purge_legacy_repacked_folders()
        ikram.show_success("✔ {} files repacked -> {}".format(n, out))
    except Exception as e:
        ikram.report_error(e)
    ikram.pause()


def _chain_dirs(target):
    """Target rel-dir se full ancestor chain — har level mount-relative,
    trailing '/' ke saath (PakWriter index format).
    'ShadowTrackerExtra/Content/Lua' -> ['ShadowTrackerExtra/',
    'ShadowTrackerExtra/Content/', 'ShadowTrackerExtra/Content/Lua/']"""
    parts = [p for p in str(target).replace("\\", "/").split("/") if p]
    return ["/".join(parts[:i]) + "/" for i in range(1, len(parts) + 1)]


def _sanitize_custom_path(p, mount):
    """Custom path — resolved under the auto source-mount.
    If the mount already ends with 'ShadowTrackerExtra' (e.g.
    '../../../ShadowTrackerExtra/'), the path stays under it,
    otherwise the 'ShadowTrackerExtra/' prefix is added automatically.
    'Content/Lua/...' never creates a doubled ShadowTrackerExtra."""
    s = str(p).strip().strip("'\"`")
    s = s.replace("\\", "/")
    segs = s.split("/")
    if ".." in segs:
        return None
    parts = [seg for seg in segs if seg and seg != "."]
    if not parts:
        return None
    mount_has_st = any(
        seg.lower() in ("shadowtracker", "shadowtrackerextra")
        for seg in str(mount).replace("\\", "/").split("/")
    )
    if parts[0].lower() in ("shadowtracker", "shadowtrackerextra"):
        parts = parts[1:]
    if not parts:
        return None
    if mount_has_st:
        return "/".join(parts)
    return "ShadowTrackerExtra/" + "/".join(parts)


def _pick_folders(pakf):
    """All FOLDER paths inside the pak — choose by number, 0 = cancel,
    or type your own path (auto under ShadowTrackerExtra).
    Returns (mount-relative target dir, exists_in_source), or None on cancel."""
    with _engines.pakmod().PakReader(pakf) as r:
        mount = r.mount_point
        all_paths = [k.rstrip("/") for k in r.dirs if k.strip("/")]
        file_map = r.full_paths()
    paths = [p for p in all_paths if p]
    if not paths and not file_map:
        ikram.show_error(
            "No folders inside this pak — can't build a structure pak."
        )
        ikram.pause()
        return None
    t = ikram.Table(
        box=ikram.ROUNDED, show_header=False, pad_edge=False,
        border_style=ikram.BORDER, style="on {}".format(ikram.BG_DEEP),
    )
    t.add_column(justify="right", width=4)
    t.add_column(style="bright_white")
    for i, p in enumerate(paths, 1):
        t.add_row("[{}]{}[/]".format(ikram._vip(i), i), p)
    ikram.console.print(
        ikram.panel(
            t, title='📦 "{}" — {} folders'.format(pakf.name, len(paths)),
            box=ikram.ROUNDED,
        )
    )
    ikram.console.print(
        "[bold {}]number = choose folder · 0 = cancel · type new path = auto under ShadowTrackerExtra[/bold {}]".format(ikram.MUTED, ikram.MUTED)
    )
    c = ikram.safe_input("[bold {}]> Select: [/]".format(ikram.INP)).strip()
    if ikram.eof_exit():
        return None
    if not c:
        # ENTER (nothing typed) -> FULL SKELETON mode: all folders + all
        # file names, every file EMPTY (engine-valid, for inject-into pak).
        return _SKELETON, False
    if c == "0":
        return None
    if c.isdigit():
        i = int(c)
        if 1 <= i <= len(paths):
            return paths[i - 1], True
        ikram.show_error("Invalid number — cancelled.")
        ikram.pause()
        return None
    target = _sanitize_custom_path(c, mount)
    if not target:
        ikram.show_error("Invalid path — cancelled.")
        ikram.pause()
        return None
    exists = target in all_paths
    return target, exists


def _prompt_empty_file_name(target):
    """Target folder not found in source — ask for a name for the empty file.
    '0' or empty = cancel. Path separators / '..' rejected."""
    ikram.console.print(
        "[bold {}]Folder '{}' not found in source pak → an empty file will be created.[/bold {}]".format(
            ikram.WARN, target, ikram.WARN
        )
    )
    ikram.console.print(
        "[bold {}]0 = cancel[/bold {}]".format(ikram.MUTED, ikram.MUTED)
    )
    while True:
        nm = ikram.safe_input(
            "[bold {}]> File name (e.g. Xxx.lua): [/]".format(ikram.INP)
        ).strip()
        if not nm or ikram.eof_exit() or nm == "0":
            return None
        if (
            "/" in nm
            or "\\" in nm
            or ".." in nm
            or nm in (".", "", ".")
            or nm.startswith(".")
        ):
            ikram.console.print(
                "[bold {}]Invalid name — bas file name, no slashes.[/]".format(ikram.WARN)
            )
            continue
        return nm


_CORPUS_TEMPLATES = None


def _candidate_paks():
    """Accessible pak corpus: Paks/ next to the tool, DROP/pak, home — whenever.
    Returns sorted list of .pak paths, deduped, no double scans."""
    seen = set()
    out = []
    bases = []
    for b in (
        _TOOL_DIR.parent / "Paks",
        _TOOL_DIR / "Paks",
        Path(ikram.DROP_PAK),
        Path(ikram.DROP_PAK).parent / "Paks",
        Path.home(),
    ):
        try:
            if b.is_dir():
                bases.append(b)
        except Exception:
            continue
    for b in bases:
        try:
            for f in sorted(b.glob("*.pak")):
                key = str(f).lower()
                if key in seen:
                    continue
                seen.add(key)
                out.append(f)
        except Exception:
            continue
    return out


def _corpus_templates(log=None):
    """First entry per file-extension (a→z order) from corpus as template —
    so an empty file of ANY extension can be engine-valid.
    Lazy memoised: scanned on first empty-file need, then cached."""
    global _CORPUS_TEMPLATES
    if _CORPUS_TEMPLATES is not None:
        return _CORPUS_TEMPLATES
    log = log or (lambda *a, **k: None)
    _CORPUS_TEMPLATES = {}
    paks = _candidate_paks()
    scanned = 0
    for pf in paks:
        tmpl_key = _PakName(pf)
        try:
            with _engines.pakmod().PakReader(pf) as r:
                for fp, e in r.full_paths().items():
                    ext = Path(fp).suffix.lower()
                    if ext and ext not in _CORPUS_TEMPLATES:
                        _CORPUS_TEMPLATES[ext] = e
        except Exception:
            continue
        scanned += 1
        if scanned % 10 == 0:
            log("  corpus: {} paks scanned, {} templates...".format(scanned, len(_CORPUS_TEMPLATES)))
    log(
        "  corpus: {} paks scanned, {} extension templates cached".format(
            scanned, len(_CORPUS_TEMPLATES)
        )
    )
    return _CORPUS_TEMPLATES


def _make_empty_entry(tmpl, version):
    """Engine-valid empty entry. Template clone (if found) inherits the
    compression fields for its extension; otherwise a raw CM_NONE entry.
    compressed_blocks/offset/size zero — so the write phase writes nothing
    and the reuse-copy path never stamps source/another-pak data."""
    pak = _engines.pakmod()
    if tmpl is not None:
        ne = tmpl.clone()
        ne.compressed_blocks = []
        ne.offset = 0
        ne.size = 0
        return ne
    ne = pak.TencentPakEntry.__new__(pak.TencentPakEntry)
    ne.content_hash = b"\x00" * 20
    ne.offset = 0
    ne.uncompressed_size = 0
    ne.size = 0
    ne.compression_method = pak.CM_NONE
    ne.unk1 = 0
    ne.unk2 = b"\x00" * (20 if version >= 5 else 0)
    ne.compressed_blocks = []
    ne.compression_block_size = 65536
    ne.encrypted = False
    ne.encryption_method = 0
    ne.index_new_sep = 0
    ne.stem = ""
    return ne


def _subtree_files(r, target):
    """All files under the target folder: {full_path: entry}.
    If target itself is a file, it is also included."""
    target_r = target.rstrip("/")
    prefix = target_r + "/"
    fp_map = r.full_paths()
    return {
        fp: e
        for fp, e in fp_map.items()
        if fp == target_r or fp.startswith(prefix)
    }


def _inject_empty_file(r, out, target, fname, mount, version, log):
    """Chain + one empty file (engine-valid entry). Template = source/same-suffix
    entry, else a corpus scan template, else a raw CM_NONE."""
    import hashlib
    target_r = target.rstrip("/")
    fname_p = Path(fname)
    fp = target_r + "/" + fname
    stem = fname_p.stem
    suffix = fname_p.suffix.lower()
    chain = _chain_dirs(target)
    r.dirs = {d: {} for d in chain}
    tmpl = None
    for old, e in r.full_paths().items():
        if Path(old).suffix.lower() == suffix:
            tmpl = e
            break
    if tmpl is None:
        tmpl = _corpus_templates(log).get(suffix)
    ne = _make_empty_entry(tmpl, version)
    ne.stem = stem
    if tmpl is None:
        path_hash = hashlib.sha1((mount + fp).lower().encode("utf-8")).digest()
        ne.unk2 = path_hash
    r.dirs[target_r + "/"] = {fname: ne}
    r.files = [ne]
    edits = [(fp, (b"", None, stem))]
    _engines.pakmod().PakWriter(r).inject_files(edits, str(out), force_add=False)
    return len(chain), 1


def _align_block_windows(r, sel, log):
    """Reuse-path safety (single-block entries only). pak.pyc inject_files
    splices only the block span of a compressed/encrypted single-block entry,
    but the reader decrypts align_encrypted_size(size) bytes — when span is
    smaller than the aligned window, the last ciphertext block bleeds bytes
    from the next entry → the content tail corrupts (verified: .uexp 16-byte
    tail field gets changed). Extend the last block end to the aligned window
    so the splice takes the full window. Multi-block entries are skipped:
    their blocks already splice self-aligned, and fiddling block ends shifts
    boundaries + corrupts content."""
    pc = _engines.pakmod().pc
    fixed = 0
    for fp, e in sel.items():
        blocks = getattr(e, "compressed_blocks", None)
        if not (blocks and getattr(e, "encrypted", False)):
            continue
        if len(blocks) != 1:
            continue
        em = getattr(e, "encryption_method", None)
        if not em:
            continue
        want = pc.align_encrypted_size(e.size, em)
        span = sum(b.end - b.start for b in blocks)
        if span < want:
            blocks[-1].end += want - span
            fixed += 1
    if fixed and log:
        log(f"  block-window aligned entries: {fixed}")


def _inject_subtree_copy(r, out, target, log):
    """Files of the target folder — the source index entries are copied as-is
    (read_entry → edits), inject_files compressed/encrypted reuse path
    splices the original bytes → byte-identical content."""
    sel = _subtree_files(r, target)
    if not sel:
        return None
    chain = _chain_dirs(target)
    r.dirs = {d: {} for d in chain}
    for fp, e in sorted(sel.items()):
        d, _, nm = fp.rpartition("/")
        key = (d + "/") if d else ""
        r.dirs.setdefault(key, {})[nm] = e
    r.files = [e for _, e in sorted(sel.items())]
    _align_block_windows(r, sel, log)
    edits = [(fp, (r.read_entry(e), None, e.stem)) for fp, e in sorted(sel.items())]
    _engines.pakmod().PakWriter(r).inject_files(edits, str(out), force_add=False)
    return len(r.dirs), len(sel)


def _inject_skeleton(r, out, target, log):
    """COSTOM Pak ENTER-mode: the index gets ALL folder paths + ALL file NAMES
    from the source pak, but every file body is EMPTY (engine-valid zero entries).
    Templates come from a same-suffix entry in source (else corpus) — so the
    skeleton pak loads in the real game, and the user injects into it later."""
    import hashlib
    fp_map = r.full_paths()
    chain = _chain_dirs(target)
    all_dirs = {d: {} for d in chain}
    for fp in fp_map:
        d, _, nm = fp.rpartition("/")
        key = (d + "/") if d else ""
        all_dirs.setdefault(key, {})
    version = getattr(r, "version", None)
    if version is None:
        version = getattr(r, "version_num", 14)
    mount = r.mount_point
    edits = []
    all_files = []
    for fp, e in sorted(fp_map.items()):
        d, _, nm = fp.rpartition("/")
        key = (d + "/") if d else ""
        stem_p = Path(fp).stem
        tmpl = e
        suffix = Path(fp).suffix.lower()
        if tmpl is None:
            tmpl = _corpus_templates(log).get(suffix)
        ne = _make_empty_entry(tmpl, version)
        ne.stem = stem_p
        if tmpl is None:
            path_hash = hashlib.sha1((str(mount) + fp).lower().encode("utf-8")).digest()
            ne.unk2 = path_hash
        all_dirs.setdefault(key, {})[nm] = ne
        all_files.append(ne)
        edits.append((fp, (b"", None, stem_p)))
    r.dirs = all_dirs
    r.files = all_files
    _engines.pakmod().PakWriter(r).inject_files(edits, str(out), force_add=False)
    _trim_tencent_pad(out, log)
    return len(all_dirs), len(edits)


def _trim_tencent_pad(path, log=None):
    """After inject_files in a COSTOM pak, the writer appends a zero-pad so the
    output = source pak size (pak.py:645-648 'total < orig_size' branch). Those
    wasted bytes only sit before the index — shift the index+footer right after
    the data and re-key the footer's index_offset field (keystream XOR, the same
    bytes the writer uses)."""
    log = log or (lambda *a, **k: None)
    pak = _engines.pakmod()
    path = Path(path)
    try:
        with pak.PakReader(str(path)) as r:
            info = r.info
            fps = r.full_paths()
            data_end = 0
            for _fp, e in fps.items():
                if e.compressed_blocks:
                    b0 = e.compressed_blocks[0]
                    end = b0.start + sum(
                        b.end - b.start for b in e.compressed_blocks
                    )
                elif e.offset and e.size:
                    end = e.offset + e.size
                else:
                    end = 0
                data_end = max(data_end, end)
            idx_off = info.index_offset
            idx_sz = info.index_size
            footer_sz = info.footer_size()
            fs = path.stat().st_size
            if footer_sz <= 0 or footer_sz > fs:
                footer_sz = fs - idx_off - idx_sz
            if footer_sz <= 0:
                return
        if idx_off <= data_end:
            return
        raw = path.read_bytes()
        data = raw[:data_end]
        index = raw[idx_off:idx_off + idx_sz]
        footer = raw[-footer_sz:]
        if len(footer) != footer_sz:
            return
        keystream = info._keystream
        key = (keystream[0] << 32) | keystream[1]
        new_footer = footer[:-8] + (data_end ^ key).to_bytes(8, "little")
        path.write_bytes(data + index + new_footer)
        log(
            "  costom: reduced {} -> {} bytes ({} files, no zero-pad)".format(
                fs, len(data) + len(index) + len(new_footer), len(fps)
            )
        )
    except Exception:
        return


def _make_costom_pak(pakf, out, target, kind=None, aes_key=None, log=None,
                     empty_name=None):
    """Build a COSTOM pak from source pakf:

      empty_name None  + target in source → keep chain-dir + copy the chosen
                                     folder's files byte-identical (real pak)
      empty_name None  + target missing  → folderless / structure-only pak
                                     (chain-dirs only, files = 0, tencent)
      empty_name set   + target missing  → chain + one empty file (valid entry)

    tencent: keep the source mount_point, index only the chosen chain +
    files. PakWriter.inject_files recomputes sha1/CRC footer fields.

    ue4: standard UE4 pak has no folder-only records — build an
    empty twin (mount + version preserved, zero records)."""
    log = log or (lambda *a, **k: None)
    pakf = Path(pakf)
    out = Path(out)
    kind = kind or ikram.detect_pak_type(pakf)
    if kind == "tencent":
        log("  engine: ikram-custom (tencent)")
        out.parent.mkdir(parents=True, exist_ok=True)
        with _engines.pakmod().PakReader(pakf) as r:
            chain = _chain_dirs(target)
            version = getattr(r, "version", None)
            if version is None:
                version = getattr(r, "version_num", 14)
            mount = r.mount_point
            if target == _SKELETON:
                # ENTER pressed: ALL folders + ALL file names, EMPTY bodies.
                return _inject_skeleton(r, out, mount, log)
            if empty_name is not None:
                got = _inject_empty_file(
                    r, out, target, empty_name, mount, version, log
                )
                _trim_tencent_pad(out, log)
                return got
            got = _inject_subtree_copy(r, out, target, log)
            if got is not None:
                _trim_tencent_pad(out, log)
                return got
            r.files = []
            r.dirs = {d: {} for d in chain}
            _engines.pakmod().PakWriter(r).inject_files(
                [], str(out), force_add=False
            )
            _trim_tencent_pad(out, log)
            return len(chain), 0
    if kind == "ue4":
        log("  engine: repak-pack (standard UE4)")
        repak = _engines.find_repak()
        if repak is None:
            raise RuntimeError(
                "repak missing — can't build an empty UE4 pak (install repak)"
            )
        version, mount_point, compression_u8 = _engines._ue4_meta(
            pakf, aes_key=aes_key
        )
        out.parent.mkdir(parents=True, exist_ok=True)
        if out.exists():
            out.unlink()
        with tempfile.TemporaryDirectory(prefix="ikram_costom_") as tmp:
            _engines._run(
                [
                    repak, "pack", tmp,
                    "--mount-point", mount_point,
                    "--version", _engines._repak_version_str(version, compression_u8),
                    "--compression", "Zlib", out,
                ],
                log,
            )
        if not out.exists() or out.stat().st_size == 0:
            raise RuntimeError("UE4 empty-pak write produced no output")
        return 0, 0
    ikram._unsupported_pak(pakf, kind)
    return 0, 0


def pak_costom_pak():
    """COSTOM PAK — pak pick → folder pick (number / 0 cancel / custom path) →
    empty pak with just that folder chain -> RESULT/CostomPak/<same name>.pak"""
    paks = ikram.drop_files(ikram.DROP_PAK, [".pak"])
    if not paks:
        ikram.show_error(
            "No PAK files found in DROP/pak.\nAdd your .pak files there and try again."
        )
        ikram.pause()
        return
    if ikram.eof_exit():
        return
    idx = _choose_pak_index(len(paks), paks, "COSTOM PAK")
    if idx is None or ikram.eof_exit():
        return
    pakf = paks[idx]
    out_root = ikram.RESULT / "CostomPak"
    out_root.mkdir(parents=True, exist_ok=True)
    out = _unique_out_file(out_root / pakf.name)
    ikram.console.print(
        "\n[bold {}]=== COSTOM PAK {} ===[/]".format(ikram.ACCENT, pakf.name)
    )
    try:
        kind = ikram.detect_pak_type(pakf)
        aes_key = None
        target = None
        empty_name = None
        if kind == "ue4":
            key = ikram.safe_input(
                "  [bold {}]-> {} AES key (ENTER = built-in default): [/]".format(
                    ikram.INP, pakf.name
                )
            )
            key = (key.strip() if key and key.strip() else "")
            aes_key = key or None
        else:
            picked = _pick_folders(pakf)
            if picked is None:
                ikram.console.print("[bold {}]Cancelled.[/]".format(ikram.MUTED))
                ikram.pause()
                return
            target, target_exists = picked
            if target == _SKELETON:
                pass
            elif not target_exists:
                empty_name = _prompt_empty_file_name(target)
                if empty_name is None:
                    ikram.console.print("[bold {}]Cancelled.[/]".format(ikram.MUTED))
                    ikram.pause()
                    return
            else:
                empty_name = None
        ndirs, nfiles = _make_costom_pak(
            pakf, out, target, kind=kind, aes_key=aes_key,
            log=ikram.console.print, empty_name=empty_name,
        )
        ikram.console.print(
            "[bold {}]▸[/] {} ({}) → {}".format(
                ikram.CYAN, pakf.name, kind, out
            )
        )
        if target == _SKELETON:
            ikram.console.print(
                "    [bold {}]•[/] ALL folders + all file names, EMPTY bodies".format(
                    ikram.MUTED
                )
            )
        elif target:
            for d in _chain_dirs(target):
                ikram.console.print("    [bold {}]•[/] {}".format(ikram.MUTED, d))
        if empty_name is not None:
            ikram.console.print(
                "    [bold {}]•[/] {} (empty file)".format(
                    ikram.MUTED, Path(empty_name).name
                )
            )
        elif nfiles and target != _SKELETON:
            ikram.console.print(
                "    [bold {}]•[/] {} file(s) copied byte-identical".format(
                    ikram.MUTED, nfiles
                )
            )
        ikram.show_success(
            "✔ Costom Pak ready: {} folders, {} files -> {}".format(
                ndirs, nfiles, out
            )
        )
    except Exception as e:
        ikram.report_error(e)
    ikram.pause()


def pak_tool_menu():
    """PAK TOOL menu (patched): original 4 options + '4. Costom Pak'.
    Mirrors the compiled pak_tool_menu byte-for-byte in style/flow."""
    while True:
        ikram.clear_screen()
        opts = [
            ("[1]", "📦 Unpack PAK",
             "WORK: take all files out of the pak.\nPUT FILE IN: DROP/pak\nOUTPUT: RESULT/extracted/"),
            ("[2]", "📦 Inject File",
             "WORK: put any file (lua/uasset/asset) into the pak —\ntype is found automatically and added to the game.\n1 file or all files at once — auto or manual path.\nPUT FILE IN: DROP/inject + DROP/pak\nOUTPUT: RESULT/injected/"),
            ("[3]", "📦 Repack PAK",
             "WORK: build the pak again.\n1) first UNPACK the pak\n2) edit files in RESULT/extracted\n3) old pak files are NEVER touched\nOUTPUT: RESULT/Repacked/"),
            ("[4]", "📦 Costom Pak",
             "WORK: make an empty pak.\nENTER (no typing) = ALL folders +\nall file names but EMPTY files\n(real in game when you inject into it).\nnumber = pick 1 folder · typed path = only\nthat path + its files copied (not empty).\nPUT FILE IN: DROP/pak\nOUTPUT: RESULT/CostomPak/"),
            ("[0]", "Back", "back to main menu"),
        ]
        t = ikram.build_menu_table(opts)
        ikram.console.print(
            ikram.panel(t, title="📦 PAK TOOL 📦", box=ikram.MENU_BOX)
        )
        c = ikram.safe_input("[bold {}]-> Select: [/]".format(ikram.INP))
        if ikram.eof_exit():
            return
        if c == "1":
            ikram.pak_extract()
        elif c == "2":
            ikram.pak_inject()
        elif c == "3":
            ikram.pak_repack_folder()
        elif c == "4":
            ikram.pak_costom_pak()
        elif c == "0":
            return
        else:
            ikram.invalid_choice()
            ikram.pause()


ikram.pak_extract = pak_extract
ikram.ensure_input_folder = ensure_input_folder
ikram.pak_inject = pak_inject
ikram.pak_repack_folder = pak_repack_folder
ikram.pak_costom_pak = pak_costom_pak
ikram.pak_tool_menu = pak_tool_menu

if __name__ == "__main__":
    import vip_ui
    vip_ui.Vip(ikram=ikram).run()
