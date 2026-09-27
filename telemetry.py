"""IkramTool — local action log.

The tool writes what it did to a plain text file next to itself, on this
device, and nowhere else. No network call, no third-party endpoint, no
account: the log is a local breadcrumb trail for the person running the
tool, readable with `cat` or any text editor.

File   : engine/telemetry.log   (beside this module)
Format : [TIMESTAMP] [ACTION] [FILE] [STATUS] [ENGINE] [ERROR]

Rotation: when the file passes MAX_BYTES it is rewritten to its last
KEEP_LINES lines, so it can never grow without bound on a phone.

Two rules this module never breaks, because the compiled core calls into it
from inside exception handlers:

  1. Nothing here ever raises. Every public function swallows its own
     failures — a full disk or a read-only filesystem must not turn a log
     write into a crash.
  2. Nothing here ever blocks. No sockets, no subprocesses on the hot path.

The compiled core calls `send_login()` after the key is accepted and
`send_error(exc, extra=...)` from its error paths, so those two names and
that call shape are the API contract.
"""
import os
import subprocess
import time
from pathlib import Path

LOG_NAME = "telemetry.log"
MAX_BYTES = 1024 * 1024
KEEP_LINES = 500

_LOG = Path(__file__).resolve().parent / LOG_NAME


def log_file():
    """Absolute path of the log. Resolved late so a test can move it."""
    return _LOG


def _stamp():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _field(value, limit=60):
    """One log column: single line, no padding surprises, no newlines."""
    if value is None:
        return "-"
    text = " ".join(str(value).split())
    if not text:
        return "-"
    return text[:limit] if len(text) > limit else text


def device_name():
    """Best-effort device label, for the log's own FILE column context.

    Reads Android props when they exist and falls back to the hostname, so
    the value is meaningful on Termux and harmless anywhere else.
    """
    for prop in ("ro.product.marketname", "ro.product.model",
                 "ro.product.device", "ro.build.product"):
        try:
            out = subprocess.run(
                ["getprop", prop], capture_output=True, timeout=3
            ).stdout.decode(errors="replace").strip()
        except Exception:
            out = ""
        if out and out not in ("", "unknown"):
            return _field(out, 40)
    try:
        return _field(os.uname().nodename, 40)
    except Exception:
        return "-"


def app_version():
    """VERSION file beside this module, or '?' when it cannot be read."""
    try:
        v = (Path(__file__).resolve().parent / "VERSION").read_text(
            encoding="utf-8").strip()
        return v or "?"
    except Exception:
        return "?"


def _rotate(path):
    """Keep the last KEEP_LINES lines once the file passes MAX_BYTES."""
    try:
        if path.stat().st_size <= MAX_BYTES:
            return
        with path.open("r", errors="replace") as fh:
            lines = fh.readlines()
        tail = lines[-KEEP_LINES:]
        tmp = path.with_suffix(".log.tmp")
        tmp.write_text("".join(tail), errors="replace")
        tmp.replace(path)
    except Exception:
        pass


def log(action, file="", status="OK", engine="", error="", **extra):
    """Append one line. The single write path every helper funnels into.

    Returns True when the line landed, False when it could not. Callers
    ignore the return value on purpose — a failed log is not a tool error.
    """
    parts = [
        "[%s]" % _stamp(),
        "[%s]" % _field(action, 28),
        "[%s]" % _field(file),
        "[%s]" % _field(status, 12),
        "[%s]" % _field(engine, 24),
        "[%s]" % _field(error, 160) if error else "[-]",
    ]
    for key, value in extra.items():
        if value not in (None, ""):
            parts.append("[%s=%s]" % (_field(key, 16), _field(value, 60)))
    line = " ".join(parts) + "\n"
    path = log_file()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", errors="replace") as fh:
            fh.write(line)
    except Exception:
        return False
    _rotate(path)
    return True


def send_login(extra=None):
    """The compiled core calls this the moment the key is accepted."""
    log("login", device_name(), "OK", app_version(), extra=extra)


def send_error(exc, extra=None):
    """The compiled core calls this from its error paths.

    `exc` is an exception instance or a string; `extra` arrives as a keyword
    from some call sites and positionally from none. Both shapes are kept.
    """
    if isinstance(exc, BaseException):
        error = "%s: %s" % (type(exc).__name__, exc)
    else:
        error = str(exc)
    log("error", extra, "FAIL", "", error)


def send_event(action, file="", status="OK", engine="", error="", **extra):
    """Public helper for the Python-side code paths (engines, pipelines)."""
    return log(action, file, status, engine, error, **extra)
