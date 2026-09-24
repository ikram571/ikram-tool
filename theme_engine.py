"""IkramTool VIP theme engine (V112).

One terminal-aware ANSI colour engine. Every colour the tool prints comes
from here — 256-colour palettes, 10 built-in themes, one persisted selection.

Config lives at `~/.ikramtool/config` (not inside the tool dir, so a
clean-slate auto-update never wipes the user's chosen theme).

Rules (Phase 8):
  - ROLE, not hardcoded colour. Callers say "success" / "error" / "title".
  - Every theme defines every role.
  - Rainbow paints EVERY character (titles, text and box borders alike)
    through the full spectrum RED -> YELLOW -> GREEN -> CYAN -> BLUE -> MAGENTA.
  - No ANSI is emitted when the stream is not a real terminal.
"""
import json
import os
import sys
from pathlib import Path

CFG_NAME = ".ikramtool"


def config_file() -> Path:
    return Path.home() / CFG_NAME / "config"

C = "\x1b["
RESET = C + "0m"
BOLD = "1"
DIM = "2"

ROLES = (
    "border", "title", "secondary", "text", "dim", "number", "prompt",
    "separator", "success", "error", "warn", "accent", "primary", "info",
)

# Red, Yellow, Green, Cyan, Blue, Magenta — the Rainbow cycle.
RAINBOW_HUE = (196, 220, 46, 51, 27, 201)

_PALETTES = {
    "Cyber Blue": dict(
        primary=33, secondary=117, accent=45, border=32, title=51, number=39,
        text=231, dim=245, prompt=51, separator=32, success=48, error=196,
        warn=214, info=123,
    ),
    "RAINBOW": dict(  # template only; Rainbow paints every char, ignores roles
        primary=141, secondary=215, accent=57, border=51, title=213, number=214,
        text=231, dim=245, prompt=51, separator=141, success=48, error=196,
        warn=220, info=123,
    ),
    "Blood Red": dict(
        primary=52, secondary=203, accent=196, border=88, title=196, number=196,
        text=231, dim=244, prompt=196, separator=88, success=48, error=196,
        warn=208, info=210,
    ),
    "Matrix Green": dict(
        primary=22, secondary=84, accent=82, border=28, title=46, number=118,
        text=231, dim=243, prompt=46, separator=28, success=46, error=124,
        warn=220, info=114,
    ),
    "Gold VIP": dict(
        primary=94, secondary=178, accent=220, border=136, title=220, number=214,
        text=231, dim=244, prompt=220, separator=136, success=48, error=196,
        warn=208, info=186,
    ),
    "Purple Reign": dict(
        primary=129, secondary=141, accent=141, border=96, title=207, number=99,
        text=231, dim=245, prompt=207, separator=96, success=48, error=196,
        warn=220, info=182,
    ),
    "Ice White": dict(
        primary=66, secondary=152, accent=117, border=66, title=231, number=117,
        text=231, dim=247, prompt=231, separator=66, success=48, error=196,
        warn=214, info=159,
    ),
    "Sunset Orange": dict(
        primary=130, secondary=208, accent=209, border=166, title=214, number=215,
        text=231, dim=245, prompt=214, separator=166, success=48, error=196,
        warn=202, info=216,
    ),
    "Ocean Teal": dict(
        primary=30, secondary=80, accent=44, border=36, title=45, number=39,
        text=231, dim=244, prompt=45, separator=36, success=48, error=196,
        warn=220, info=116,
    ),
    "Lava": dict(
        primary=58, secondary=179, accent=214, border=94, title=208, number=196,
        text=231, dim=244, prompt=208, separator=94, success=48, error=196,
        warn=172, info=222,
    ),
}

THEMES = (
    "Rainbow", "Cyber Blue", "Blood Red", "Matrix Green", "Gold VIP",
    "Purple Reign", "Ice White", "Sunset Orange", "Ocean Teal", "Lava",
)
THEME_NAMES = {
    "Rainbow": "Rainbow",
    "Cyber Blue": "Cyber Blue",
    "Blood Red": "Blood Red",
    "Matrix Green": "Matrix Green",
    "Gold VIP": "Gold VIP",
    "Purple Reign": "Purple Reign",
    "Ice White": "Ice White",
    "Sunset Orange": "Sunset Orange",
    "Ocean Teal": "Ocean Teal",
    "Lava": "Lava",
}

_EMOJI = {
    "Rainbow": "🌈", "Cyber Blue": "💙", "Blood Red": "❤️",
    "Matrix Green": "💚", "Gold VIP": "💛", "Purple Reign": "💜",
    "Ice White": "🤍", "Sunset Orange": "🧡", "Ocean Teal": "🩵",
    "Lava": "🔴",
}


def is_tty(stream=None) -> bool:
    stream = stream or sys.stdout
    try:
        return bool(stream.isatty()) and os.environ.get("NO_COLOR") is None
    except Exception:
        return False


def color_support() -> int:
    """0 = none, 8 = basic, 256 = full."""
    if not is_tty():
        return 0
    if os.environ.get("COLORTERM") in ("truecolor", "24bit"):
        return 256
    term = os.environ.get("TERM", "")
    if "256" in term:
        return 256
    return 8 if term else 8


def terminal_width(default=80) -> int:
    try:
        w = os.get_terminal_size().columns
    except Exception:
        w = default
    return w if w and w > 20 else default


def _fansi(code: int, bold=False, dim=False) -> str:
    if color_support() == 0:
        return ""
    parts = []
    if bold:
        parts.append(BOLD)
    if dim:
        parts.append(DIM)
    if code:
        parts.append("38;5;%d" % code)
    if not parts:
        return ""
    return C + ";".join(parts) + "m"


def _rainbow_char(ch: str, idx: int) -> str:
    fg = _fansi(RAINBOW_HUE[idx % len(RAINBOW_HUE)])
    if not fg:
        return ch
    return fg + ch + RESET


class Theme:
    def __init__(self, name):
        if name not in THEMES:
            name = "Rainbow" if name == "RAINBOW" else "Cyber Blue"
        self.name = name
        pal = _PALETTES.get(name, _PALETTES["Cyber Blue"])
        self._pal = dict(pal)
        for r in ROLES:
            self._pal.setdefault(r, 231)
        self.rainbow = (name == "Rainbow")

    def apply(self, text, role="text", bold=None):
        if role not in ROLES:
            role = "text"
        text = "" if text is None else str(text)
        if self.rainbow:
            return "".join(_rainbow_char(ch, i) for i, ch in enumerate(text))
        code = self._pal[role]
        if bold is None:
            bold = role in ("title", "success", "error", "accent", "warn",
                            "number", "primary", "prompt")
        dim = role in ("dim", "secondary", "info")
        fg = _fansi(code, bold=bold, dim=dim)
        if not fg:
            return text
        return fg + text + RESET

    def paint(self, text, role="text"):
        return self.apply(text, role)

    def emoji(self):
        return _EMOJI.get(self.name, "")

    def numbers(self, text):
        """Number slots: Rainbow -> rainbow, else the theme's number colour."""
        return self.apply(text, "number")


def load_theme() -> Theme:
    """Saved config -> Cyber Blue (default on fresh/no config)."""
    try:
        cfg = config_file()
        if cfg.is_file():
            d = json.loads(cfg.read_text(errors="ignore"))
            name = str(d.get("theme", ""))
            if name and name in THEMES:
                return Theme(name)
    except Exception:
        pass
    return Theme("Cyber Blue")


def save_theme(name: str) -> None:
    if name not in THEMES:
        return
    try:
        cfg = config_file()
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text(json.dumps({"theme": name}, indent=1))
    except Exception:
        pass


def strip_ansi(text: str) -> str:
    import re
    return re.sub(r"\x1b\[[0-9;]*m", "", text)