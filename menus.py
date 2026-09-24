"""IkramTool V112 — menu handlers.

Every real operation is the ORIGINAL V111 flow, run exactly as shipped:

    PAK  1 Unpack    -> ikram.pak_extract
         2 Inject    -> ikram.pak_inject        (compiled 7-step wizard)
         3 Repack    -> ikram.pak_repack_folder
         4 Costom    -> ikram.pak_costom_pak
    LUA  1 Compile   -> ikram.lua_compile_one
         2 Decompile -> ikram.lua_decompile_one

Delegating (instead of re-implementing) is what guarantees Section G:
paths, prompt order, numbered displays, auto-replace, never-modify-original,
new-folder creation, example/help text, repack + costom logic and output
path behaviour are byte-identical to V111. The V112 layer only adds the
shell around them: themed main menu, Themes switcher, dependency check at
launch, and the C/R clear utilities below.

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
    ik = _ikram(vip)
    if ik is None:
        return
    ik.pak_costom_pak()


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