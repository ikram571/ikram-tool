"""IkramTool VIP theme engine (V112).

One terminal-aware ANSI colour engine. Every colour the tool prints comes
from here — 256-colour palettes, 10 built-in themes, one persisted selection.

Config lives at `~/.ikramtool/config` (not inside the tool dir, so a
clean-slate auto-update never wipes the user's chosen theme).

Rules (Phase 8):
  - ROLE, not hardcoded colour. Callers say "success" / "error" / "title".
  - Every theme defines every role.
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

# Fallback roles when a palette omits one (Red is a sane default accent).
ROLES = (
    "border", "border_dark", "title", "secondary", "text", "dim", "number",
    "prompt", "separator", "success", "error", "warn", "accent", "primary",
    "info",
)

_PALETTES = {
    "Original Color": dict(
        primary=228, secondary=51, accent=141, border=135, border_dark=61,
        title=228, number=45, text=231, dim=103, prompt=51, separator=135,
        success=46, error=196, warn=214, info=141, bg=(14, 8, 23),
    ),
    "Cyber Blue": dict(
        primary=117, secondary=159, accent=81, border=117, border_dark=24,
        title=87, number=45, text=231, dim=253, prompt=87, separator=117,
        success=48, error=196, warn=214, info=159, bg=(5, 10, 20),
    ),
    "Neon Pink": dict(
        primary=213, secondary=218, accent=205, border=213, border_dark=133,
        title=213, number=45, text=231, dim=253, prompt=213, separator=177,
        success=48, error=196, warn=220, info=218, bg=(20, 8, 18),
    ),
    "Blood Red": dict(
        primary=210, secondary=216, accent=203, border=210, border_dark=124,
        title=203, number=45, text=231, dim=253, prompt=203, separator=167,
        success=48, error=196, warn=208, info=222, bg=(22, 5, 8),
    ),
    "Matrix Green": dict(
        primary=114, secondary=158, accent=82, border=114, border_dark=28,
        title=46, number=154, text=231, dim=253, prompt=46, separator=114,
        success=46, error=196, warn=220, info=159, bg=(3, 14, 6),
    ),
    "Gold VIP": dict(
        primary=220, secondary=229, accent=220, border=220, border_dark=172,
        title=229, number=220, text=231, dim=253, prompt=220, separator=178,
        success=48, error=196, warn=208, info=229, bg=(18, 14, 4),
    ),
    "Purple Reign": dict(
        primary=183, secondary=189, accent=147, border=183, border_dark=140,
        title=207, number=183, text=231, dim=253, prompt=207, separator=140,
        success=48, error=196, warn=220, info=189, bg=(20, 6, 26),
    ),
    "Ice White": dict(
        primary=152, secondary=195, accent=117, border=152, border_dark=60,
        title=231, number=152, text=231, dim=255, prompt=231, separator=152,
        success=48, error=196, warn=214, info=159, bg=(4, 6, 10),
    ),
    "Sunset Orange": dict(
        primary=215, secondary=216, accent=209, border=215, border_dark=172,
        title=222, number=215, text=231, dim=253, prompt=214, separator=172,
        success=48, error=196, warn=202, info=216, bg=(24, 10, 5),
    ),
    "Ocean Teal": dict(
        primary=80, secondary=123, accent=44, border=80, border_dark=23,
        title=87, number=45, text=231, dim=253, prompt=45, separator=80,
        success=48, error=196, warn=220, info=159, bg=(4, 16, 18),
    ),
    "Lava": dict(
        primary=215, secondary=216, accent=214, border=215, border_dark=130,
        title=226, number=208, text=231, dim=253, prompt=208, separator=172,
        success=48, error=196, warn=172, info=222, bg=(24, 10, 4),
    ),
}

THEMES = (
    "Original Color", "Neon Pink", "Cyber Blue", "Blood Red", "Matrix Green",
    "Gold VIP", "Purple Reign", "Ice White", "Sunset Orange", "Ocean Teal",
    "Lava",
)
THEME_NAMES = {
    "Original Color": "Original Color",
    "Neon Pink": "Neon Pink",
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
    "Original Color": "👑", "Neon Pink": "🌸", "Cyber Blue": "💙", "Blood Red": "❤️",
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


def _fansi(code: int, bold=False, dim=False, bg=None) -> str:
    if color_support() == 0:
        return ""
    parts = []
    if bold:
        parts.append(BOLD)
    if dim:
        parts.append(DIM)
    if code:
        parts.append("38;5;%d" % code)
    if bg:
        parts.append("48;2;%d;%d;%d" % (bg[0], bg[1], bg[2]))
    if not parts:
        return ""
    return C + ";".join(parts) + "m"


class Theme:
    def __init__(self, name):
        if name not in THEMES:
            name = "Original Color"
        self.name = name
        pal = _PALETTES.get(name, _PALETTES["Original Color"])
        self._pal = dict(pal)
        for r in ROLES:
            self._pal.setdefault(r, 231)
        self._bg = tuple(pal.get("bg", (0, 0, 0)))

    def apply(self, text, role="text", bold=None):
        if role not in ROLES:
            role = "text"
        text = "" if text is None else str(text)
        code = self._pal[role]
        if bold is None:
            bold = role in ("title", "success", "error", "accent", "warn",
                            "number", "primary", "prompt")
        dim = role in ("dim", "secondary", "info")
        fg = _fansi(code, bold=bold, dim=dim)
        if not fg:
            return text
        return fg + text + RESET

    def paint_code(self, text, code, bold=True):
        """Exact ANSI colour by 256-code (V111 `_vip_num` cycle)."""
        text = "" if text is None else str(text)
        fg = _fansi(code, bold=bold)
        if not fg:
            return text
        return fg + text + RESET

    @property
    def bg(self):
        return self._bg

    def paint(self, text, role="text"):
        return self.apply(text, role)

    def emoji(self):
        return _EMOJI.get(self.name, "")

    def numbers(self, text):
        """Number slots: the theme's number colour."""
        return self.apply(text, "number")

    def paint_code(self, text, code, bold=True):
        """Exact ANSI colour by 256-code (V111 `_vip_num` cycle)."""
        text = "" if text is None else str(text)
        fg = _fansi(code, bold=bold)
        if not fg:
            return text
        return fg + text + RESET


def load_theme() -> Theme:
    """Saved config -> Original Color (default on fresh/no config)."""
    try:
        cfg = config_file()
        if cfg.is_file():
            d = json.loads(cfg.read_text(errors="ignore"))
            name = str(d.get("theme", ""))
            if name and name in THEMES:
                return Theme(name)
    except Exception:
        pass
    return Theme("Original Color")


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


def display_width(text: str) -> int:
    """True terminal column width: ANSI stripped, wide chars (emoji/CJK) = 2,
    combining marks = 0. Used by the box engine so every row lines up edge
    to edge even with emoji in the title lines."""
    import unicodedata
    w = 0
    for ch in strip_ansi(str(text)):
        o = ord(ch)
        if unicodedata.combining(ch) or o in (0x200B, 0x00AD, 0xFEFF):
            continue
        if unicodedata.east_asian_width(ch) in ("W", "F"):
            w += 2
        else:
            w += 1
    return w