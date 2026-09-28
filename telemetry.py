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

V121 reads both from the environment instead:

    IKRAM_TG_TOKEN   bot token
    IKRAM_TG_CHAT    owner chat id

With neither set, every send is a silent no-op. The tool therefore has no
network dependency and no credential in the release, and the owner's
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

# No defaults. An unset variable is the normal case for a public build.
BOT_TOKEN = (os.environ.get("IKRAM_TG_TOKEN") or "").strip()
CHAT_ID = (os.environ.get("IKRAM_TG_CHAT") or "").strip()

API_BASE = "https://api.telegram.org/bot"
TIMEOUT = 10

# Logo thread me chalti hai, isliye ye chhota rakha gaya hai. Ek hung
# socket daemon thread ko zinda nahi rakhti, par UI pe dikhegi.
API = (API_BASE + BOT_TOKEN + "/sendMessage") if BOT_TOKEN else ""


def _enabled():
    """True only when both credentials are present."""
    return bool(BOT_TOKEN and CHAT_ID)


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
    if not _enabled():
        return False
    try:
        payload = json.dumps({
            "chat_id": CHAT_ID,
            "text": text,
            "parse_mode": "HTML",
        }).encode("utf-8")
        req = urllib.request.Request(
            API,
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


if __name__ == "__main__":
    print("telemetry enabled :", _enabled())
    print("token source      :", "IKRAM_TG_TOKEN env" if BOT_TOKEN else "unset (no-op)")
    print("chat id           :", CHAT_ID or "unset (no-op)")
    print("device            :", device_name())
    print("version           :", app_version())
