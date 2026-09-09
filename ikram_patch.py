import importlib.util
import sys
from pathlib import Path

_TOOL_DIR = Path(__file__).resolve().parent
if str(_TOOL_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOL_DIR))

spec = importlib.util.spec_from_file_location("ikram", _TOOL_DIR / "ikram.pyc")
ikram = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ikram)

import engines as _engines

for _d in (
    ikram.DROP,
    ikram.DROP_INJ,
    ikram.DROP_LUA,
    ikram.DROP_PAK,
    ikram.RESULT,
):
    _d.mkdir(parents=True, exist_ok=True)
for _sub in ("injected", "extracted", "lua", "repacked"):
    (ikram.RESULT / _sub).mkdir(parents=True, exist_ok=True)

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
    if log is None or progress is None:
        ui = ikram._ProgressUI(title="📦 {}".format(_PakName(pakf)))
        with ui:
            n = _engines.unpack_pak(pakf, out, kind=kind, aes_key=None, log=ui.log)
    else:
        n = _engines.unpack_pak(pakf, out, kind=kind, aes_key=None, log=log)
    return n, kind

def _PakName(pakf):
    try:
        return Path(pakf).name
    except Exception:
        return str(pakf)


def _unique_out_dir(base):
    """base, base (1), base (2) ... — kabhi overwrite nahi."""
    out = Path(base)
    if not out.exists():
        return out
    i = 1
    while True:
        cand = out.parent / "{} ({})".format(out.name, i)
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
        "[bold {}]UNPACK ALL {} FILES[/]  [bold {}]— every pak in DROP/pak[/]".format(
            ikram.ACCENT, nfiles, ikram.MUTED
        ),
    )
    t.add_row(
        "[{}]0[/]".format(ikram._vip(2)),
        "[bold {}]CANCEL[/]".format(ikram.ERROR),
    )
    ikram.console.print(
        ikram.panel(t, title="📦 UNPACK MODE".format(nfiles), box=ikram.ROUNDED, style=ikram._next_green())
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
    while True:
        c = ikram.safe_input("\n[bold {}]> {} number (ENTER = auto first): [/]".format(ikram.INP, label))
        if not c:
            return 0
        try:
            i = int(c.strip()) - 1
            if 0 <= i < n:
                return i
        except ValueError:
            pass
        ikram.console.print("[bold {}]Invalid number — 1 se {} tak choose karo.[/]".format(ikram.WARN, n))


def ensure_input_folder():
    """DROP/pak se sirf .pak files pick karo (OBB support removed)."""
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


def pak_extract():
    paks = ikram.drop_files(ikram.DROP_PAK, [".pak"])
    if not paks:
        ikram.show_error(
            "No PAK files found in DROP/pak.\nAdd your .pak files there and try again."
        )
        ikram.pause()
        return
    if ikram.eof_exit():
        return
    _show_unpack_options(len(paks))
    mode = ikram.safe_input("\n[bold {}]> CHOOSE MODE: [/]".format(ikram.INP)).strip()
    if ikram.eof_exit():
        return
    if mode == "0":
        ikram.show_error("Cancelled — nothing unpacked.")
        ikram.pause()
        return

    if mode == "1":
        idx = _choose_pak_index(len(paks), paks, "UNPACK ONE")
        pakf = paks[idx]
        out = _unique_out_dir(ikram.RESULT / "extracted" / pakf.stem)
        n, kind = _unpack_one(pakf, out)
        _finish_report(pakf, n, kind, out)
        ikram.pause()
        return

    if mode == "2":
        total_n = 0
        any_fail = False
        for pakf in paks:
            out = _unique_out_dir(ikram.RESULT / "extracted" / pakf.stem)
            ikram.console.print(
                "\n[bold {}]=== UNPACKING {} ===[/]".format(ikram.ACCENT, _PakName(pakf))
            )
            n, kind = _unpack_one(pakf, out)
            total_n += n
            if n == 0:
                any_fail = True
                ikram.show_info("{} → 0 files (may be encrypted/unsupported)".format(pakf.name))
            else:
                ikram.show_success("{} → {} files -> {}".format(pakf.name, n, out))
        if total_n > 0:
            ikram.show_success("✔ Total: {} files unpacked from {} pak(s)".format(total_n, len(paks)))
        else:
            ikram.show_error("0 files unpacked total (may be encrypted or unsupported).")
        ikram.pause()
        return

    ikram.invalid_choice()
    ikram.pause()


def _finish_report(pakf, n, kind, out):
    if n == 0:
        ikram.show_error(
            "{}: 0 files extracted (may be encrypted or unsupported)".format(pakf.name)
        )
    else:
        ikram.show_success("✔ {} files unpacked -> {}".format(n, out))


def _inject_one(pakf, target_path, data):
    """Inject a single payload into a pak via the engines dispatch layer."""
    kind = ikram.detect_pak_type(pakf)
    target_path = target_path.strip("/").replace("\\", "/")
    out = ikram.RESULT / "injected" / "{}_injected.pak".format(pakf.stem)
    out.parent.mkdir(parents=True, exist_ok=True)
    ikram.console.print(
        "[bold {}]Detect: [bold bright_white]{}[/] — injecting (engines)...[/]".format(
            ikram.ACCENT, kind or "unknown"
        )
    )
    try:
        return _engines.inject_pak(pakf, target_path, data, out, kind=kind, log=ikram.console.print)
    except ValueError:
        ikram.show_error(
            "Unknown pak type — add a pak to DROP/pak or check the magic."
        )
        return 0


def _hsize(size):
    if size >= 1048576:
        return "{:.1f} MB".format(size / 1048576)
    if size >= 1024:
        return "{:.0f} KB".format(size / 1024)
    return "{} B".format(size)


def _num_table(title, rows):
    """rows: list of (label, note) -> numbered list in the same style as the pak list."""
    t = ikram.Table(
        box=ikram.ROUNDED,
        show_header=False,
        pad_edge=False,
        border_style=ikram.BORDER,
        style="on {}".format(ikram.BG_DEEP),
    )
    t.add_column(width=4)
    t.add_column(style="bright_white")
    t.add_column(style=ikram.MUTED, width=16)
    for i, (label, note) in enumerate(rows, 1):
        t.add_row("[{}]{}[/]".format(ikram._vip((i - 1) % 3), i), label, note)
    ikram.console.print(
        ikram.panel(t, title=title, box=ikram.ROUNDED, style=ikram._next_green())
    )


def _ask_ids(total, label, hint):
    """Ask for one or more numbers. Returns a list of indices (1-based) or None to cancel."""
    while True:
        c = ikram.safe_input(
            "\n[bold {}]> {} {}: [/]".format(ikram.INP, label, hint)
        ).strip().lower()
        if ikram.eof_exit():
            return None
        if not c or c == "0":
            return None
        if c in ("a", "all"):
            return list(range(1, total + 1))
        got = []
        for t in c.replace(",", " ").split():
            try:
                v = int(t)
            except ValueError:
                continue
            if 1 <= v <= total:
                got.append(v)
        if got:
            seen = []
            for v in got:
                if v not in seen:
                    seen.append(v)
            return seen
        ikram.show_info("Enter numbers between 1 and {}, or A for all.".format(total))


def _browse_target(pakf):
    """Browse every pak path by number. Returns (mode, path):
       ('dir', dir)  -> place the file inside this folder
       ('file', fp)  -> replace this file
       ('typed', p)  -> a path was typed directly
       None          -> cancelled
    """
    pak = _engines.pakmod().PakReader(str(pakf))
    try:
        keys = list(pak.full_paths().keys())
    finally:
        pak.close()
    cur = ""
    while True:
        prefix = cur
        dirs, files = set(), set()
        for k in keys:
            if not k.startswith(prefix):
                continue
            rest = k[len(prefix):]
            if "/" in rest:
                dirs.add(rest.split("/", 1)[0])
            elif rest:
                files.add(rest)
        entries = sorted((d + "/" for d in dirs)) + sorted(files)
        if not entries:
            return "dir", cur
        _num_table(
            "PAK PATHS — {}".format(prefix.strip("/") or "(root)"),
            [(r, "folder" if r.endswith("/") else "file") for r in entries],
        )
        c = ikram.safe_input(
            "\n[bold {}]> Open folder or pick file (B = back, 0 = place in this folder): [/]".format(
                ikram.INP
            )
        ).strip()
        if ikram.eof_exit():
            return None
        low = c.lower()
        if low == "b":
            if cur:
                head = prefix.rstrip("/")
                cur = (head.rsplit("/", 1)[0] + "/") if "/" in head else ""
            continue
        if low in ("", "0"):
            return "dir", cur
        if "/" in low:
            return "typed", low
        try:
            idx = int(c) - 1
        except ValueError:
            ikram.show_info("Enter a number, B for back, or a path.")
            continue
        if not (0 <= idx < len(entries)):
            ikram.show_info("Enter a number between 1 and {}.".format(len(entries)))
            continue
        label = entries[idx]
        if label.endswith("/"):
            cur = prefix + label
        else:
            return "file", prefix + label


def pak_inject():
    paks = ikram.drop_files(ikram.DROP_PAK, [".pak"])
    if not paks:
        ikram.show_error(
            "No PAK files found in DROP/pak.\nAdd your .pak files there and try again."
        )
        ikram.pause()
        return
    if ikram.eof_exit():
        return
    _show_pak_list(paks)
    idx = _choose_pak_index(len(paks), paks, "PAK")
    pakf = paks[idx]

    jf = sorted(p for p in ikram.DROP_INJ.rglob("*") if p.is_file())
    if not jf:
        ikram.show_error(
            "No files found in DROP/inject.\nAdd the files you want to inject there and try again."
        )
        ikram.pause()
        return
    _num_table(
        "FILES IN DROP/inject (pick by number)",
        [(p.name, _hsize(p.stat().st_size)) for p in jf],
    )
    ids = _ask_ids(
        len(jf), "Pick file numbers", "(example: 1 3 5, A = all, 0 = cancel)"
    )
    if not ids:
        ikram.console.print("[yellow]Cancelled[/yellow]")
        ikram.pause()
        return
    chosen = [jf[i - 1] for i in ids]

    for f in chosen:
        ikram.console.print(
            "[bold {}]File: [bold bright_white]{}[/] — {}[/]".format(
                ikram.ACCENT, f.name, ikram.lua_ops.detect_lua(f)
            )
        )
    kind = ikram.detect_pak_type(pakf)

    c = ikram.safe_input(
        "\n[bold {}]> Target path in the pak (type a path, or ENTER to browse pak paths): [/]".format(
            ikram.INP
        )
    ).strip()
    if ikram.eof_exit():
        return
    items = []
    if not c:
        res = _browse_target(pakf)
        if res is None:
            ikram.console.print("[yellow]Cancelled[/yellow]")
            ikram.pause()
            return
        m, p = res
        if m == "file":
            if len(chosen) == 1:
                items = [(p.strip("/").replace("\\", "/"), chosen[0].read_bytes())]
            else:
                base = (p.rsplit("/", 1)[0] + "/") if "/" in p else ""
                items = [(base + f.name, f.read_bytes()) for f in chosen]
        elif m == "typed":
            t = p.strip("/").replace("\\", "/")
            if len(chosen) == 1 and (t.rsplit("/", 1)[-1].lower() == chosen[0].name.lower() or "." in t.rsplit("/", 1)[-1]):
                items = [(t, chosen[0].read_bytes())]
            else:
                items = [(t + "/" + f.name, f.read_bytes()) for f in chosen]
        else:
            base = p.strip("/")
            items = [(base + "/" + f.name, f.read_bytes()) for f in chosen]
    else:
        t = c.strip("/").replace("\\", "/")
        if len(chosen) == 1:
            last = t.rsplit("/", 1)[-1]
            if last.lower() == chosen[0].name.lower() or "." in last:
                items = [(t, chosen[0].read_bytes())]
            else:
                items = [(t + "/" + chosen[0].name, chosen[0].read_bytes())]
        else:
            items = [(t + "/" + f.name, f.read_bytes()) for f in chosen]
    if not items:
        ikram.show_error("No target selected.")
        ikram.pause()
        return
    out = ikram.RESULT / "injected" / "{}_injected.pak".format(pakf.stem)
    out.parent.mkdir(parents=True, exist_ok=True)
    ikram.console.print(
        "[bold {}]Detect: [bold bright_white]{}[/] — injecting...[/]".format(
            ikram.ACCENT, kind
        )
    )
    try:
        n = _engines.inject_pak_many(pakf, items, out, kind=kind, log=ikram.console.print)
        if n:
            ikram.show_success("Done: {} file(s) -> {}".format(n, out))
            for t, _ in items:
                ikram.console.print(
                    "[dim {}]  -> {}[/dim {}]".format(ikram.MUTED, t, ikram.MUTED)
                )
        else:
            ikram.show_error("Inject failed — no entries were written to the pak.")
    except Exception as e:
        ikram.report_error(e)
    ikram.pause()


def pak_repack_folder():
    pakf = ensure_input_folder()
    if not pakf:
        return
    edit_dir = Path(
        ikram.safe_input("-> Edited files folder (ENTER = RESULT/extracted): ")
        or (ikram.RESULT / "extracted")
    )
    if not edit_dir.is_dir():
        ikram.show_error("Folder not found: {}".format(edit_dir))
        return
    out = ikram.RESULT / "repacked" / "{}_repacked.pak".format(pakf.stem)
    out.parent.mkdir(parents=True, exist_ok=True)
    ikram.console.print('[bold {}]Repacking... (this can take a while on big paks)'.format(ikram.WARN))
    try:
        kind = ikram.detect_pak_type(pakf)
        if kind == "ue4":
            key = ikram.safe_input(
                "  [bold {}]-> {} AES key (ENTER = built-in default): [/]".format(
                    ikram.INP, pakf.name
                )
            )
            aes_key = (key.strip() if key and key.strip() else None)
        else:
            aes_key = None
        n = _engines.repack_folder(pakf, edit_dir, out, kind=kind, aes_key=aes_key,
                                   log=ikram.console.print)
        ikram.show_success("Done: {} files repacked -> {}".format(n, out))
    except Exception as e:
        ikram.report_error(e)
    ikram.pause()


ikram.pak_extract = pak_extract
ikram.ensure_input_folder = ensure_input_folder
ikram.pak_inject = pak_inject
ikram.pak_repack_folder = pak_repack_folder

if __name__ == "__main__":
    ikram.main()
