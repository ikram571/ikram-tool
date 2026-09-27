"""Ikram Tool — menu handlers.

Five of the six real operations are the ORIGINAL flow, run exactly as
shipped, by delegating to the compiled core:

    PAK  1 Unpack    -> ikram.pak_extract
         2 Inject    -> ikram.pak_inject        (compiled 7-step wizard)
         3 Repack    -> ikram.pak_repack_folder
    LUA  1 Compile   -> ikram.lua_compile_one
         2 Decompile -> ikram.lua_decompile_one

Delegating (instead of re-implementing) is what guarantees Section G: paths,
prompt order, numbered displays, auto-replace, never-modify-original, new
folder creation and output path behaviour stay identical to the original.
The only option NOT delegated is PAK 4 (Costom): ikram.pyc has no
pak_costom_pak, so it used to raise AttributeError and drop the user into
the "Unexpected error" box. That one is implemented in pak_custom() against
the same engine layer, driven entirely by the menu text it already shipped
with. See its docstring for what the option actually promises.

`ikram` is the module loaded by ikram_patch.py (compiled core + patched
overlay). Vip passes it in at construction time.
"""
from pathlib import Path

import box_engine
import paths


# ================================================================== PAK
def _ikram(vip):
    if vip.ikram is None:
        vip.error_box(["✗ Ikram core not loaded",
                       "Run the tool through run.sh / ikram_patch.py."])
        vip.wait_enter()
        return None
    return vip.ikram


def pak_unpack(vip):
    ik = _ikram(vip)
    if ik is None:
        return
    ik.pak_extract()


def pak_inject(vip):
    ik = _ikram(vip)
    if ik is None:
        return
    ik.pak_inject()


def pak_repack(vip):
    ik = _ikram(vip)
    if ik is None:
        return
    ik.pak_repack_folder()


def _numbered(vip, rows, title, subtitle=None, per_page=14):
    """Numbered list inside the tool's own box, paged so a 4000-entry pak
    does not scroll the prompt off the screen. Returns the rendered text."""
    pages = [rows[i:i + per_page] for i in range(0, len(rows), per_page)] or [[]]
    out = []
    for i, page in enumerate(pages, 1):
        body = []
        if len(pages) > 1:
            body.append(vip.theme.apply("page %d / %d" % (i, len(pages)), "dim"))
            body.append(box_engine.SEP)
        body.extend(page)
        out.append(vip.box.draw_box(
            body, "light", title=title if i == 1 else None,
            subtitle=subtitle if i == 1 else None))
        title = subtitle = None
    return "\n".join(out)


def _ask_pak(vip, paks):
    """STEP 1 — pick which pak out of DROP/pak. Re-prompts, never crashes."""
    while True:
        vip.write(_numbered(
            vip,
            [vip.theme.apply("%3d" % i, "number")
             + "  " + vip.theme.apply(p.name, "primary")
             + vip.theme.apply("  " + paths.human(p.stat().st_size), "dim")
             for i, p in enumerate(paks, 1)],
            "CUSTOM PAK — select base pak",
            "%d pak file(s) in %s" % (len(paks), paths.folder_label(paths.DROP_PAK)),
        ) + "\n")
        vip.write("  " + vip.theme.apply("Select file number", "prompt") + " ")
        ans, eof = vip._eof_answered("")
        ans = ans.strip()
        if eof and not ans:
            return None
        if ans.isdigit():
            n = int(ans)
            if n == 0:
                return None
            if 1 <= n <= len(paks):
                return paks[n - 1]
        vip.error_box(["✗ Invalid number",
                       "  Enter 1-%d, or 0 to cancel" % len(paks)])
        vip.pause(0.5)


def _ask_paths(vip, inventory, pak_name):
    """STEP 2 + 3 — show every internal path, then resolve the selection.

    ENTER = every path. A number = that numbered path. A typed path = that
    path (or everything under it). Anything else re-prompts. Returns
    (selected, how) or (None, None) when the user backs out.
    """
    names = sorted(inventory)
    rows = []
    for i, fp in enumerate(names, 1):
        rows.append(vip.theme.apply("%3d" % i, "number")
                    + "  " + vip.theme.apply(fp, "primary")
                    + vip.theme.apply("  " + paths.human(inventory[fp]), "dim"))
    vip.write(_numbered(
        vip, rows, "PATHS INSIDE %s" % pak_name.upper(),
        "%d file(s) — ENTER selects ALL with full content" % len(names),
    ) + "\n")
    vip.write("  " + vip.theme.apply(
        "Enter number, path, or ENTER for ALL (0 = cancel)", "prompt") + " ")
    while True:
        ans, eof = vip._eof_answered("")
        ans = ans.strip()
        if eof and not ans:
            return None, None
        if not ans:
            return list(names), "all %d paths selected with full content" % len(names)
        if ans.isdigit():
            n = int(ans)
            if n == 0:
                return None, None
            if 1 <= n <= len(names):
                return [names[n - 1]], "1 path selected with full content"
            vip.error_box(["✗ Invalid number",
                           "  Enter 1-%d, or press ENTER for ALL" % len(names)])
            vip.pause(0.5)
            continue
        low = ans.replace("\\", "/").lstrip("./")
        if low in inventory:
            return [low], "1 path selected with full content"
        under = [fp for fp in names
                 if fp.startswith(low.rstrip("/") + "/")]
        if under:
            return under, ("%d paths under %s selected with full content"
                           % (len(under), low[:48]))
        tail = [fp for fp in names if fp.endswith("/" + low)]
        if tail:
            return tail, ("%d path(s) matched %s with full content"
                          % (len(tail), low[:48]))
        vip.error_box(["✗ Path not found in pak",
                       "  " + ans[:60]])
        vip.pause(0.5)


_BAD_NAME = set('/\\:*?"<>|')


def _ask_out_name(vip, pakf):
    """STEP 4 — output pak name. Defaults to the source pak's own name."""
    default = pakf.stem
    vip.write("  " + vip.theme.apply("Output pak name (without .pak)", "prompt")
              + vip.theme.apply("  [%s]" % default, "dim") + " ")
    while True:
        ans, eof = vip._eof_answered("")
        ans = ans.strip()
        if eof and not ans:
            return None
        if not ans:
            return default
        if ans.lower().endswith(".pak"):
            ans = ans[:-4]
        if not ans.strip():
            vip.error_box(["✗ Name cannot be empty",
                           "  Press ENTER to use %s" % default])
            vip.pause(0.5)
            continue
        if _BAD_NAME & set(ans):
            vip.error_box(["✗ Illegal character in name",
                           "  Not allowed: " + " ".join(sorted(_BAD_NAME & set(ans))),
                           "  Use letters, numbers, dot, dash, underscore."])
            vip.pause(0.5)
            continue
        return ans


def pak_custom(vip):
    """COSTOM PAK — build a pak from a base pak, with REAL file content.

    ikram.pyc has no pak_costom_pak (its pak menu only ever had unpack /
    inject / repack), so this option used to raise AttributeError and drop the
    tool into the "Unexpected error" box.

    What it does now, in the order the user sees it:

      1. every .pak in DROP/pak is listed and numbered; the user picks one
      2. that pak is extracted WITH its content and every internal path is
         listed and numbered, with the real size of each file
      3. the selection is resolved: ENTER = all paths, a number = that path,
         a typed path = that path or everything under it. Anything invalid
         re-prompts; nothing crashes and nothing is written empty
      4. an output name is asked for, defaulting to the base pak's name
      5. the pak is built into RESULT/CostomPak with every selected file
         carrying its ORIGINAL bytes, then read back and compared
      6. the temp session is removed whether the build succeeded or not

    The old version of this wrote 0-byte entries for the ENTER and folder
    modes, which produced a pak the game could not read, and it silently used
    whichever pak happened to be first in the folder.
    """
    import engines

    paks = paths.list_drop(paths.DROP_PAK, (".pak",))
    if not paks:
        vip.error_box(["✗ No PAK found",
                       "PUT FILE IN: " + paths.folder_label(paths.DROP_PAK)])
        vip.wait_enter()
        return
    pakf = _ask_pak(vip, paks)
    if pakf is None:
        vip.write("  " + vip.theme.apply("Cancelled", "warn") + "\n")
        vip.wait_enter()
        return

    workdir = engines.custom_session_dir(paths.timestamp())
    try:
        try:
            inventory = engines.custom_pak_inventory(
                pakf, workdir, log=lambda *a: vip.write(str(a[0]) + "\n")
                if a else None)
        except Exception as e:
            vip.error_box(["✗ Cannot read this PAK",
                           "  %s" % str(e)[:70],
                           "PUT A PAK IN: " + paths.folder_label(paths.DROP_PAK)])
            vip.wait_enter()
            return
        if not inventory:
            vip.error_box(["✗ This PAK has no readable files",
                           "  " + pakf.name])
            vip.wait_enter()
            return

        wanted, how = _ask_paths(vip, inventory, pakf.name)
        if wanted is None:
            vip.write("  " + vip.theme.apply("Cancelled", "warn") + "\n")
            vip.wait_enter()
            return

        name = _ask_out_name(vip, pakf)
        if name is None:
            vip.write("  " + vip.theme.apply("Cancelled", "warn") + "\n")
            vip.wait_enter()
            return

        out = paths.unique_path(paths.RESULT_CUSTOMPAK / (name + ".pak"))
        if not vip.proceed_box(
                "COSTOM PAK (full content)",
                paths.folder_label(paths.DROP_PAK) + " -> " + pakf.name,
                wanted[:3],
                paths.folder_label(paths.RESULT_CUSTOMPAK) + "/" + out.name,
                extra=["%d path(s): %s" % (len(wanted), how),
                       "every file keeps its ORIGINAL content (no 0-byte files)"]):
            vip.write("  " + vip.theme.apply("Cancelled", "warn") + "\n")
            vip.wait_enter()
            return

        frame = None
        try:
            from vip_ui import ProgressFrame
            frame = ProgressFrame(vip, title="Building costom PAK",
                                  total=len(wanted))
        except Exception:
            frame = None

        def _tick(done, total, label):
            if frame is not None:
                frame.show(done=done, total=total, cur=label)

        try:
            n, nbytes = engines.build_custom_pak(
                pakf, out, wanted, workdir,
                log=lambda *a: vip.write(str(a[0]) + "\n") if a else None,
                progress=_tick)
        except Exception as e:
            if frame is not None:
                frame.show(pct=100, done=0, total=len(wanted), cur="Failed")
            vip.error_box(["✗ Build failed: " + str(e)[:64],
                           "  The base pak was not modified."],
                          next_step="Nothing was written to RESULT/CostomPak.")
            vip.wait_enter()
            return
        if frame is not None:
            frame.show(pct=100, done=len(wanted), total=len(wanted),
                       cur="Finished")
        vip.success_box([
            "✓ Custom PAK built: %s" % paths.folder_label(
                paths.RESULT_CUSTOMPAK) + "/" + out.name,
            "  Files : %d (full original content)" % n,
            "  Size  : %s" % paths.human(nbytes),
            "  File  : %s" % paths.human(out.stat().st_size),
        ])
        vip.logged("pak.custom", files=n, out=out.name)
    finally:
        engines.cleanup_custom_session(workdir)


# ================================================================== LUA
def lua_compile(vip):
    ik = _ikram(vip)
    if ik is None:
        return
    ik.lua_compile_one()


def lua_decompile(vip):
    ik = _ikram(vip)
    if ik is None:
        return
    ik.lua_decompile_one()


# ============================================================ clear utils
def _clear(vip, targets, title, label):
    targets = [Path(t) for t in targets]
    n, _b = 0, 0
    for t in targets:
        a, b = paths.count_dir(t)
        n += a
        _b += b
    if n == 0:
        vip.success_box(["✓ Nothing to clear",
                         "  %s" % paths.folder_label(targets[0])])
        vip.wait_enter()
        return
    if not vip.confirm_box(title, label):
        return
    for t in targets:
        paths.purge(t)
    after, _ = 0, 0
    for t in targets:
        a, _b = paths.count_dir(t)
        after += a
    vip.success_box(["✓ Cleared %d file(s)" % n,
                     "  %s" % " + ".join(paths.folder_label(t) for t in targets)])
    vip.wait_enter()


def clear_drop_pak(vip):
    _clear(vip, [paths.DROP_PAK], "CLEAR DROP FOLDER",
           "Delete all files from DROP/pak/?")


def clear_drop_lua(vip):
    _clear(vip, [paths.DROP_LUA], "CLEAR DROP FOLDER",
           "Delete all files from DROP/lua/?")


def clear_result(vip):
    _clear(vip, [paths.RESULT_EXTRACTED, paths.RESULT_INJECTED,
                 paths.RESULT_LUA, paths.RESULT_PROCESSED,
                 paths.RESULT_CUSTOMPAK, paths.RESULT_REPACKED],
           "CLEAR RESULT FOLDER",
           "Delete everything from RESULT/?")


def clear_result_lua(vip):
    _clear(vip, [paths.RESULT_LUA], "CLEAR RESULT FOLDER",
           "Delete everything from RESULT/lua/?")