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


def pak_custom(vip):
    """COSTOM PAK — declare a pak's file list with empty file bodies.

    ikram.pyc has no pak_costom_pak (its pak menu only ever had unpack /
    inject / repack), so this option used to raise AttributeError and drop the
    tool into the "Unexpected error" box.

    What it promises is entirely spelled out by the menu text, and this
    implements exactly that, in three modes:

      ENTER          every file in the pack, all bodies empty
      <number>       one FOLDER from the numbered list, all bodies empty
      <typed path>   only that path (or everything under it), and its bytes
                     are COPIED from the template instead of emptied

    The third mode is the one that is not "empty", and it is deliberate: a
    typed path means "give me this file as it already is", whereas ENTER and a
    folder number are the skeleton trick where the game creates the file.
    """
    import engines

    paks = paths.list_drop(paths.DROP_PAK, (".pak",))
    if not paks:
        vip.error_box(["✗ No PAK found",
                       "PUT FILE IN: " + paths.folder_label(paths.DROP_PAK)])
        vip.wait_enter()
        return
    if len(paks) > 1:
        vip.warn_box(["! %d PAK files found — using the first one" % len(paks),
                     "  " + paks[0].name])
    pakf = paks[0]

    try:
        all_paths = engines.list_pak_paths(pakf, log=lambda *a: None)
    except Exception as e:
        vip.error_box(["✗ Cannot read this PAK",
                       "  %s" % str(e)[:70],
                       "PUT A PAK IN: " + paths.folder_label(paths.DROP_PAK)])
        vip.wait_enter()
        return
    if not all_paths:
        vip.error_box(["✗ This PAK has no files",
                       "  " + pakf.name])
        vip.wait_enter()
        return

    if not vip.proceed_box("COSTOM PAK (empty files)",
                           paths.folder_label(paths.DROP_PAK) + " -> " + pakf.name,
                           None,
                           paths.folder_label(paths.RESULT_CUSTOMPAK),
                           extra=["%d file path(s) available" % len(all_paths),
                                  "files inside the new PAK are EMPTY (0 bytes)"]):
        vip.write("  " + vip.theme.apply("Cancelled", "warn"))
        vip.wait_enter()
        return

    # The menu advertises a numbered FOLDER list, so derive the folders out of
    # the flat path list instead of showing every file name.
    folders = engines.pack_folders(all_paths)
    vip.write("\n  " + vip.theme.apply(
        "ENTER = all %d files (empty) · number = that folder's files (empty) · "
        "type a path = only that, COPIED not empty" % len(all_paths), "dim") + "\n")
    if folders:
        vip.write("\n")
        for i, f in enumerate(folders, 1):
            inside = sum(1 for p in all_paths
                         if p == f or p.startswith(f + "/"))
            vip.write("  " + vip.theme.apply("%3d" % i, "accent")
                      + "  " + vip.theme.apply(f[:56], "primary")
                      + vip.theme.apply("  (%d file%s)" % (inside,
                                                          "" if inside == 1 else "s"),
                                        "dim") + "\n")
        vip.write("\n")
    vip.write("  " + vip.theme.apply("Path: ", "prompt") + " ")
    ans, eof = vip._eof_answered("")
    ans = ans.strip()
    if eof and not ans:
        vip.write("  " + vip.theme.apply("Cancelled", "warn"))
        vip.wait_enter()
        return

    # a typed path means "give me this one, contents and all" — that is the
    # only branch the menu describes as copied rather than empty
    copy_mode = False
    if not ans:
        wanted = list(all_paths)
    elif ans.isdigit():
        n = int(ans)
        if not (1 <= n <= len(folders)):
            vip.error_box(["✗ No such number",
                           "  1-%d only" % len(folders)])
            vip.wait_enter()
            return
        picked = folders[n - 1]
        wanted = [p for p in all_paths
                  if p == picked or p.startswith(picked + "/")]
    else:
        low = ans.replace("\\", "/").lstrip("./")
        hits = [p for p in all_paths if p == low or p.endswith("/" + low)]
        if not hits:
            under = [p for p in all_paths
                     if p.startswith(low.rstrip("/") + "/")]
            if under and any(p.startswith(low.rstrip("/") + "/")
                             for p in all_paths):
                hits = under
        if not hits:
            vip.error_box(["✗ Path not in this PAK",
                           "  %s" % ans[:60]])
            vip.wait_enter()
            return
        wanted = hits
        copy_mode = True

    stamp = paths.timestamp()
    out = paths.unique_path(paths.RESULT_CUSTOMPAK /
                            ("costom_%s.pak" % stamp))
    frame = None
    try:
        from vip_ui import ProgressFrame
        frame = ProgressFrame(vip, title="Building costom PAK",
                              total=len(wanted))
    except Exception:
        frame = None

    def _tick(i, _cur):
        if frame is not None:
            frame.show(done=i, total=len(wanted), cur=cur)

    try:
        n = engines.costom_pak(pakf, out, wanted, log=lambda *a: vip.write(
            str(a[0]) + "\n") if a else None, copy=copy_mode)
    except Exception as e:
        if frame is not None:
            frame.show(pct=100, cur="Failed")
        vip.error_box(["✗ Costom PAK failed",
                       "  %s" % str(e)[:70]],
                      next_step="The original PAK was not modified.")
        vip.wait_enter()
        return
    if frame is not None:
        frame.show(pct=100, cur="Finished")

    if copy_mode:
        vip.success_box(["✓ Costom PAK created",
                         "  %s" % out.name,
                         "  %d path(s), COPIED from the original" % n,
                         "  " + paths.folder_label(paths.RESULT_CUSTOMPAK)])
    else:
        vip.success_box(["✓ Costom PAK created",
                         "  %s" % out.name,
                         "  %d path(s), all EMPTY (0 bytes)" % n,
                         "  " + paths.folder_label(paths.RESULT_CUSTOMPAK)])
    vip.wait_enter()


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