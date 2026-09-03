import importlib.util
import sys
from pathlib import Path

_TOOL_DIR = Path(__file__).resolve().parent
if str(_TOOL_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOL_DIR))

spec = importlib.util.spec_from_file_location("ikram", _TOOL_DIR / "ikram.pyc")
ikram = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ikram)


def _unpack_one(pakf, out, log=None, progress=None):
    """Unpack a single pak -> out. Returns (n, kind)."""
    kind = ikram.detect_pak_type(pakf)
    if kind not in ("tencent", "ue4"):
        ikram._unsupported_pak(pakf, kind)
        return 0, kind
    ikram.console.print(
        "[bold {}]▸[/] {} [bold {}]({})[/]".format(
            ikram.CYAN, pakf.name, ikram.MUTED, kind
        )
    )
    n = 0
    if kind == "tencent":
        if log is None or progress is None:
            ui = ikram._ProgressUI(title="📦 {}".format(pakf.name))
            with ui:
                n = ikram.pakmod.unpack_pak(pakf, out, log=ui.log, progress=ui.progress)
        else:
            n = ikram.pakmod.unpack_pak(pakf, out, log=log, progress=progress)
    else:
        key = ikram.safe_input(
            "  [bold {}]-> {} AES key (blank = none): [/]".format(ikram.INP, pakf.name)
        )
        p = ikram.ue4mod.Ue4Pak(pakf, aes_key=(key or None))
        if log is None or progress is None:
            ui = ikram._ProgressUI(title="📦 {}".format(pakf.name))
            with ui:
                _files = p.files()
                total = len(_files) if _files else 1
                for _i, _f in enumerate(_files, 1):
                    _ok, _sz = p.extract_one(out, _f)
                    if _ok:
                        n += 1
                    ui.log("  {}  ({} bytes)".format(_f, _sz))
                    ui.progress(_i, total, _f)
        else:
            _files = p.files()
            total = len(_files) if _files else 1
            for _i, _f in enumerate(_files, 1):
                _ok, _sz = p.extract_one(out, _f)
                if _ok:
                    n += 1
                    log("  {}  ({} bytes)".format(_f, _sz))
                progress(_i, total, _f)
    return n, kind


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


def pak_extract():
    paks = ikram.drop_files(ikram.DROP_PAK, [".pak", ".obb"])
    if not paks:
        ikram.show_error(
            "No PAK files found in DROP/pak.\nAdd your .pak or .obb files there and try again."
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
                "\n[bold {}]=== UNPACKING {} ===[/]".format(ikram.ACCENT, pakf.name)
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


ikram.pak_extract = pak_extract

if __name__ == "__main__":
    ikram.main()
