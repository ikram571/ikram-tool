"""IKRAM TOOL - telemetry (OWNER ONLY).

V121 rewrite. The public API is byte-identical to the compiled V120 module
so every existing call site keeps working unchanged:

    device_name()            -> str
    app_version()            -> str
    send_login(extra="")     -> None   (daemon thread, never blocks)
    send_error(exc, extra="") -> None  (daemon thread, never blocks)
    BOT_TOKEN / CHAT_ID / API  (module constants)

WHY THIS FILE EXISTS
--------------------
V120 shipped the Telegram bot token and the owner chat id as plain string
constants inside a public GitHub release. Both values are deliberately NOT
reproduced here; the token is quoted nowhere, not even in this comment.

Anyone who downloaded the zip could (a) send arbitrary messages as the
owner's bot, spoofing update and error alerts, and (b) read the chat
history, which is every user's device name plus every error string the
tool has ever reported. Reading a constant out of a public archive takes
no skill at all.

V121 reads both from the environment, and from an optional owner-only
credentials file:

    IKRAM_TG_TOKEN   bot token
    IKRAM_TG_CHAT    owner chat id
    ~/.ikramtool/telegram.json   {"token": "...", "chat_id": "..."}

The file exists because a token pasted into a shell profile is a token that
ends up in .bash_history, and "set an env var" is a worse answer than a real
one to a non-technical user. Precedence is file then environment, so a
machine that exports the variable overrides the file without editing it.

The file is read at CALL time, not import time, for the same reason
paths.read_version() replaced the module-level version constants: a value
baked in at import is a value that silently goes stale, and here stale means
either telemetry pointing at a revoked token or the owner editing the file
and watching nothing change until restart.

With none of the three set, every send is a silent no-op. The tool therefore
has no network dependency and no credential in the release, and the owner's
alerts are the owner's business alone.

The old token must still be REVOKED at @BotFather. Editing this file does
not un-leak it -- anything already published stays published.

Both senders are daemon threads and _send() swallows every exception, so a
dead network, a blocked host or a revoked token can never raise into the
caller or stall the UI.
"""
import datetime
import json
import os
import platform
import subprocess
import threading
import urllib.request
from pathlib import Path

TOOL_DIR = Path(__file__).resolve().parent
CRED_FILE = Path.home() / ".ikramtool" / "telegram.json"

API_BASE = "https://api.telegram.org/bot"
TIMEOUT = 10

_creds_cache = (None, None)


def _read_cred_file():
    """(token, chat_id) from ~/.ikramtool/telegram.json, or (None, None).

    Accepts the keys "token"/"chat_id" and tolerates "chat"/"id", because
    hand-editing a JSON file should not require knowing my exact naming.
    Malformed JSON, a missing file, or a file the user cannot read all
    return empty: telemetry is a courtesy channel and has no business being
    the thing that crashes the tool.
    """
    try:
        data = json.loads(CRED_FILE.read_text())
    except Exception:
        return None, None
    if not isinstance(data, dict):
        return None, None
    token = data.get("token") or data.get("bot_token") or ""
    chat = data.get("chat_id") or data.get("chat") or data.get("id") or ""
    return str(token).strip() or None, str(chat).strip() or None


def credentials(refresh=False):
    """Return (token, chat_id) as strings, possibly empty.

    File first, environment second. Cached after the first read because this
    runs on every send and the file does not change mid-session -- but
    refresh=True exists so a test, or an owner who just revoked and replaced
    the token, can pick up the new value without restarting the tool.
    """
    global _creds_cache
    if refresh or _creds_cache == (None, None):
        tok, chat = _read_cred_file()
        tok = tok or (os.environ.get("IKRAM_TG_TOKEN") or "").strip() or None
        chat = chat or (os.environ.get("IKRAM_TG_CHAT") or "").strip() or None
        _creds_cache = (tok, chat)
    return _creds_cache


def _enabled():
    """True only when both credentials are available from either source."""
    tok, chat = credentials()
    return bool(tok and chat)


def api_url(token=None):
    """sendMessage endpoint for the active token, or '' when disabled."""
    tok = token or (credentials()[0] or "")
    return (API_BASE + tok + "/sendMessage") if tok else ""


def device_name():
    """Best-effort human name for this device. Never raises."""
    try:
        out = subprocess.run(
            ["getprop", "ro.product.model"],
            capture_output=True, text=True, timeout=4,
        )
        name = (out.stdout or "").strip()
        if name:
            return name
    except Exception:
        pass
    try:
        return platform.node() or platform.system() or "unknown"
    except Exception:
        return "unknown"


def app_version():
    """VERSION file contents, or '0' when it is missing."""
    try:
        v = TOOL_DIR / "VERSION"
        if v.exists():
            return v.read_text().strip() or "0"
    except Exception:
        pass
    return "0"


def _now():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _post(text):
    """One HTTPS POST. Returns True on a 200, False on anything else.

    Every failure path is swallowed by design: telemetry is a courtesy
    channel and must never become a failure mode of the tool.
    """
    tok, chat = credentials()
    if not (tok and chat):
        return False
    try:
        payload = json.dumps({
            "chat_id": chat,
            "text": text,
            "parse_mode": "HTML",
        }).encode("utf-8")
        req = urllib.request.Request(
            api_url(tok),
            data=payload,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "ikram-tool",
            },
        )
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return 200 <= getattr(r, "status", 200) < 300
    except Exception:
        return False


def _thread(text):
    # daemon=True: a Telegram outage cannot keep the process alive, and
    # cannot make the tool wait on a socket the user never asked for.
    try:
        threading.Thread(
            target=_post, args=(text,), daemon=True,
        ).start()
    except Exception:
        pass


def send_login(extra=""):
    """Live-use ping: who launched the tool, on what, when."""
    try:
        where = str(extra) if extra else "startup"
        _thread(
            "\U0001f534 <b>IKRAM TOOL — LIVE USE</b>\n"
            "\U0001f4f1 <b>Device:</b> {}\n"
            "\U0001f9ed <b>Where:</b> {}\n"
            "\U0001f550 <b>Time:</b> {}".format(
                device_name(), where, _now())
        )
    except Exception:
        pass


def send_error(exc, extra=""):
    """Report an exception to the owner.

    exc may be an Exception instance or a plain string. The detail is
    clipped so one enormous traceback cannot blow past Telegram's 4096
    character limit, which would otherwise turn a real error report into
    a dropped one.
    """
    try:
        detail = str(exc) if exc is not None else ""
        if len(detail) > 700:
            detail = detail[:700].rstrip() + "..."
        where = str(extra) if extra else "unknown"
        _thread(
            "⚠️ <b>IKRAM TOOL — ERROR</b>\n"
            "\U0001f4f1 <b>Device:</b> {}\n"
            "\U0001f4c4 <b>Detail:</b> {}\n"
            "\U0001f522 <b>Version:</b> v{}\n"
            "\U0001f550 <b>Time:</b> {}".format(
                device_name(), detail, app_version(), _now())
        )
    except Exception:
        pass


def status():
    """Non-secret one-line summary, safe to print or log."""
    tok, chat = credentials()
    if tok and chat:
        src = "file" if _read_cred_file()[0] else "env"
        return "enabled via {} (bot {})".format(src, tok.split(":")[0])
    if tok or chat:
        return "incomplete: need BOTH token and chat id ({} set)".format(
            "token" if tok else "chat id")
    return "disabled (no token, no-op)"


if __name__ == "__main__":
    print("telemetry         :", status())
    print("cred file         :", CRED_FILE,
          "(present)" if CRED_FILE.exists() else "(absent)")
    print("device            :", device_name())
    print("version           :", app_version())
