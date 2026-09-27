"""Key-gate child process for the release gates.

Drives the REAL compiled key_lock through the real vip_ui wrapper in a
fresh process, with a scripted terminal, and prints one JSON verdict. The
gate must never hang, so the driver runs the gate on a thread and reports
whether the thread is still alive — a hang is a failed gate, not a stuck
test run.
"""
import builtins
import io
import json
import re
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from rich.console import Console                    # noqa: E402

import ikram_patch                                   # noqa: E402
from vip_ui import Vip                               # noqa: E402

ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")

answers = json.loads(sys.argv[1]) if len(sys.argv) > 1 else []
eof_mode = len(sys.argv) > 2 and sys.argv[2] == "eof"
accept = len(sys.argv) > 3 and sys.argv[3] == "accept"
timeout = float(sys.argv[4]) if len(sys.argv) > 4 else 20.0

ik = ikram_patch.ikram
buf = io.StringIO()
vip = Vip(ikram=ik, stream=buf)
sink = Console(file=buf, width=100, legacy_windows=False)
ik.console = sink
pre_console = sink
if accept:
    ik.key_lock = lambda: True

real_input = builtins.input
queue = list(answers)


def answer(prompt=""):
    if eof_mode or not queue:
        raise EOFError
    return queue.pop(0)


verdict = {}


def body():
    try:
        verdict["ok"] = bool(vip._key_gate())
    except BaseException as exc:                     # noqa: BLE001
        verdict["ok"] = "raised:%s" % type(exc).__name__


builtins.input = answer
t = threading.Thread(target=body, daemon=True)
t.start()
t.join(timeout)
post_input = builtins.input
post_console = ik.console
builtins.input = real_input

text = ANSI.sub("", buf.getvalue())
# The compiled core clears the screen with raw escapes on stdout, so the
# verdict is tagged: the gate finds the marker instead of guessing a line.
print("###VERDICT###" + json.dumps({
    "ok": verdict.get("ok", "HUNG"),
    "hung": t.is_alive(),
    "invalid": text.count("Invalid key!"),
    "prompts": text.count("Enter key:"),
    "too_many": "Too many attempts" in text,
    "input_restored": post_input is answer,
    "console_restored": post_console is pre_console,
    "text_tail": text[-400:],
}))
sys.exit(0)
