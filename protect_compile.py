"""Compatibility shim — protection now lives in ikram_upgrade.

Until V120 this module carried a *second, independent* implementation of the
junk-inflation + IKRM wrapper. It claimed the same ``IKRM``/v1 magic as
ikram_upgrade but emitted a different container:

    protect_compile.protect(std)  -> 2,005,943 B, starts 1b4c7561 (plain chunk)
                                     ikram_upgrade.is_protected(...) is False
                                     ikram_upgrade.try_unwrap(...)     is None

so anything wrapped here was unreadable by the tool's own unwrapper and
unloadable by the game. Nothing imported it, which is the only reason the
landmine never fired.

V120 removes the duplicate. Every knob below is derived from ikram_upgrade so
the two can never drift again. The live compile path in mega_lua.compile_bgmi
calls ikram_upgrade directly and is unaffected.
"""

import os

import ikram_upgrade

MAGIC = ikram_upgrade.MAGIC
VERSION = ikram_upgrade.VERSION
HEADER_SIZE = ikram_upgrade.HEADER_SIZE
ENV_OFF = ikram_upgrade.ENV_OFF

# Single source of truth. Historically these were 10-20MB here and 2-4MB in
# ikram_upgrade, so "the same" protection had two different output sizes.
MIN_BYTES = ikram_upgrade.MIN_BYTES
MAX_BYTES = ikram_upgrade.MAX_BYTES


def enabled() -> bool:
    """True unless the operator explicitly disabled protection."""
    return not (ENV_OFF in os.environ and os.environ[ENV_OFF] == "0")


def protect(std: bytes, min_bytes: int = MIN_BYTES, max_bytes: int = MAX_BYTES) -> bytes:
    """Apply the live protection chain to a patched standard Lua chunk.

    Mirrors mega_lua.compile_bgmi exactly:
        stage1_inflate -> std_to_bgmi -> stage3_wrap
    Returns the finished IKRM-wrapped BGMI file, or ``std`` untouched when
    protection is disabled through IKRM_PROTECT=0.
    """
    if not enabled():
        return std
    inflated = ikram_upgrade.stage1_inflate(std, min_bytes=min_bytes,
                                            max_bytes=max_bytes)
    bgmi = ikram_upgrade.std_to_bgmi(inflated)
    return ikram_upgrade.stage3_wrap(bgmi)


def unprotect(data: bytes):
    """Recover the standard chunk, or None when not IKRM-wrapped."""
    bgmi = ikram_upgrade.try_unwrap(data)
    if bgmi is None:
        return None
    return ikram_upgrade.bgmi_to_std(bgmi)


def harden_compile(std: bytes) -> bytes:
    return protect(std)
