"""IkramTool VIP box engine (V112).

The ONLY printer in the tool. No raw print() anywhere else — every line a
box, every box terminal-width aware ((term - 4), clamped 50..100), every
overflow truncated with an ellipsis, every border theme-aware.

Styles (Phase 8):
  heavy   ╔═╗  double  ╠ ╣  rounded ╭─╮  thick ┏━┓  light ┌─┐  minimal ▌
  `minimal` is only legal for the Press-ENTER wait line.

Internal divider rows: a content row equal to the SEP sentinel renders a
full-width divider (╠═╣ / ├─┤ ...) per the box style.
"""
from theme_engine import Theme, terminal_width, strip_ansi, display_width

SEP = "__SEP__"

_BOXES = {
    "heavy":   {"tl": "╔", "tr": "╗", "bl": "╚", "br": "╝",
                "h": "═", "v": "║", "jt": "╠", "je": "╣"},
    "double":  {"tl": "╔", "tr": "╗", "bl": "╚", "br": "╝",
                "h": "═", "v": "║", "jt": "╠", "je": "╣"},
    "rounded": {"tl": "╭", "tr": "╮", "bl": "╰", "br": "╯",
                "h": "─", "v": "│", "jt": "├", "je": "┤"},
    "thick":   {"tl": "┏", "tr": "┓", "bl": "┗", "br": "┛",
                "h": "━", "v": "┃", "jt": "┣", "je": "┫"},
    "light":   {"tl": "┌", "tr": "┐", "bl": "└", "br": "┘",
                "h": "─", "v": "│", "jt": "├", "je": "┤"},
    "minimal": {"tl": "▌", "tr": "", "bl": "▌", "br": "",
                "h": "", "v": "", "jt": "", "je": ""},
}


def visible_len(s: str) -> int:
    return display_width(s)


def _truncate(line: str, inner_w: int) -> str:
    """Truncate a pre-coloured line to inner_w visible chars, adding …."""
    if visible_len(line) <= inner_w:
        return line
    plain = strip_ansi(line)
    cut = plain[: max(1, inner_w - 1)] + "…"
    if visible_len(cut) > inner_w:  # multibyte overhang — trim hard
        cut = plain[:inner_w] + "…"
    return cut


class ProgressBar:
    """A single-line progress bar: «[▓▓▓▒░░░░]  62%»."""

    def __init__(self, theme):
        self.theme = theme

    def render(self, pct, width=34):
        pct = max(0.0, min(100.0, pct if isinstance(pct, (int, float)) else 0.0))
        filled = int(round(pct / 100.0 * width))
        bar = "▓" * filled + "░" * (width - filled)
        colored = "".join(
            self.theme.apply(ch, "accent") if ch == "▓" else self.theme.apply(ch, "dim")
            for ch in bar
        )
        return "  [%s]  %3d%%" % (colored, int(pct))


class BoxEngine:
    def __init__(self, theme: Theme | None = None):
        self.theme = theme or Theme("Cyber Blue")
        self._bar = ProgressBar(self.theme)

    # ------------------------------------------------------------- public
    def draw_box(self, content, style="heavy", title=None, subtitle=None,
                 width=None, align="left", padding=1, color_role="border"):
        lines = self._resolve(content)
        w = self._resolve_width(width)
        b = _BOXES.get(style, _BOXES["heavy"])
        inner_w = w - 4
        body = []

        if title is not None:
            body.append(self._row(b, self.theme.apply(str(title), "title"),
                                  inner_w, "center"))
            if subtitle is not None:
                body.append(self._row(b, self.theme.apply(str(subtitle), "secondary"),
                                      inner_w, "center"))
            body.append(self._divider(b, inner_w + 2, color_role))

        pad = max(0, int(padding or 0))
        for ln in lines:
            if ln == SEP:
                body.append(self._divider(b, inner_w + 2, color_role))
                continue
            chunk = _truncate(str(ln), inner_w)
            body.append(self._row(b, chunk, inner_w, align))
        if pad:
            rows = body

        if style == "minimal":
            out = []
            for l in body[1:]:
                if visible_len(l) <= len(b["tl"]):
                    continue
                if "\x1b[" in l:
                    out.append(l.rstrip())
                else:
                    out.append(self.theme.apply(b["tl"] + " ", color_role)
                              + l.rstrip())
            return "\n".join(out or [" "])

        top = self.theme.apply(b["tl"] + b["h"] * (w - 2) + b["tr"], color_role)
        bottom = self.theme.apply(b["bl"] + b["h"] * (w - 2) + b["br"], color_role)
        return "\n".join([top] + body + [bottom])

    def draw_progress(self, pct=None, done=None, total=None, cur=None,
                      speed=None, eta=None, style="heavy", width=None,
                      title="Working..."):
        w = self._resolve_width(width)
        b = _BOXES.get(style, _BOXES["heavy"])
        inner_w = w - 4
        lines = []
        hdr = self.theme.apply(str(title), "title")
        lines.append(self._row(b, _truncate(hdr, inner_w), inner_w, "center"))
        lines.append(self._divider(b, inner_w + 2, "border"))

        if isinstance(pct, (int, float)):
            lines.append(self._row(b, self._bar.render(pct), inner_w, "left"))
        if done is not None or total is not None:
            f = int(done) if done is not None else 0
            t = int(total) if total is not None else 0
            txt = "Files   : %d / %d" % (f, t) if t else "Files   : %d" % f
            lines.append(self._row(b, self.theme.apply(txt, "secondary"),
                                   inner_w, "left"))
        if cur:
            lines.append(self._row(
                b, "Current : " + _truncate(self.theme.apply(str(cur), "text"), inner_w - 10),
                inner_w, "left"))
        if speed:
            lines.append(self._row(b, self.theme.apply("Speed   : " + str(speed), "info"),
                                   inner_w, "left"))
        if eta:
            lines.append(self._row(b, self.theme.apply("Remaining: " + str(eta), "info"),
                                   inner_w, "left"))
        top = self.theme.apply(b["tl"] + b["h"] * (w - 2) + b["tr"], "border")
        bottom = self.theme.apply(b["bl"] + b["h"] * (w - 2) + b["br"], "border")
        return "\n".join([top] + lines + [bottom])

    def draw_labeled_row(self, label, value, label_role="dim", value_role="text"):
        l = self.theme.apply(str(label), label_role)
        v = self.theme.apply(str(value), value_role)
        return "  %-14s :  %s" % (l.rstrip(), v.rstrip())

    # ------------------------------------------------------------- internal
    def _resolve(self, content):
        if isinstance(content, str):
            return content.split("\n")
        return [str(x) for x in content]

    def _resolve_width(self, width):
        if width is None:
            width = terminal_width() - 4
        width = int(width or 80)
        return max(50, min(width, 100))

    def _row(self, b, inner, inner_w, align, color_role="border"):
        inner = self._align(inner, inner_w, align)
        if not b["v"]:
            if "\x1b[" in inner:
                return inner
            return self.theme.apply(b["v"] + " " + inner, color_role)
        if "\x1b[" in inner:
            return (self.theme.apply(b["v"] + " ", color_role)
                    + inner + " "
                    + self.theme.apply(b["v"], color_role))
        return self.theme.apply(b["v"] + " " + inner + " " + b["v"], color_role)

    def _divider(self, b, inner_w, color_role):
        return self.theme.apply(b["jt"] + b["h"] * inner_w + b["je"], color_role)

    def _align(self, inner, inner_w, align):
        vis = visible_len(inner)
        if vis >= inner_w:
            return inner[:inner_w]
        gap = inner_w - vis
        if align == "center":
            l = gap // 2
            r = gap - l
            return (" " * l) + inner + (" " * r)
        if align == "right":
            return (" " * gap) + inner
        return inner + (" " * gap)


def box(content, style="heavy", title=None, subtitle=None, width=None,
        align="left", padding=1):
    return BoxEngine().draw_box(content, style, title, subtitle, width,
                                align, padding)