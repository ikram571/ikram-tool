"""IkramTool — theme engine tests.

The theme list is generated from the xterm-256 colour space, so it needs real
coverage rather than "it imported". Every theme is checked for: a unique name,
all 15 roles, in-range colour codes, and the ability to actually paint. The
first 11 hand-tuned themes are pinned by name AND by palette so a change to
the generator can never silently move or restyle a shipped theme.

Run:  python3 tests/test_themes.py
Exit 0 = all green.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import theme_engine as te          # noqa: E402

# the 11 palettes that shipped before the generator existed
SHIPPED = (
    "Original Color", "Neon Pink", "Cyber Blue", "Blood Red", "Matrix Green",
    "Gold VIP", "Purple Reign", "Ice White", "Sunset Orange", "Ocean Teal",
    "Lava",
)

# the entire xterm-256 space, every code must have a theme
EXPECT_CODES = 256
EXPECT_TOTAL = len(SHIPPED) + EXPECT_CODES


def main():
    failed = []

    def check(name, cond, detail=""):
        print("  %-38s %s%s" % (name, "PASS" if cond else "FAIL",
                                "" if cond or not detail else "  <- " + detail))
        if not cond:
            failed.append(name)

    print("theme engine: %d themes" % len(te.THEMES))
    print()

    # ---- list integrity
    check("total themes == 267", len(te.THEMES) == EXPECT_TOTAL,
          "got %d" % len(te.THEMES))
    check("names unique", len(set(te.THEMES)) == len(te.THEMES))
    check("all names non-empty str",
          all(isinstance(n, str) and n.strip() for n in te.THEMES))
    check("shipped 11 at positions 1-11",
          tuple(te.THEMES[:11]) == SHIPPED,
          str(te.THEMES[:11]))

    # ---- table integrity
    check("THEME_NAMES covers every theme",
          all(n in te.THEME_NAMES for n in te.THEMES))
    check("_PALETTES covers every theme",
          all(n in te._PALETTES for n in te.THEMES))
    check("_EMOJI covers every theme",
          all(n in te._EMOJI for n in te.THEMES))

    # ---- per-theme colour validity
    bad_codes, bad_roles, bad_paint = [], [], []
    for n in te.THEMES:
        pal = te._PALETTES[n]
        missing = [r for r in te.ROLES if r not in pal]
        if missing:
            bad_roles.append("%s:%s" % (n, ",".join(missing)))
            continue
        for role in te.ROLES:
            c = pal[role]
            if not isinstance(c, int) or not 0 <= c <= 255:
                bad_codes.append("%s.%s=%r" % (n, role, c))
        try:
            t = te.Theme(n)
            painted = t.apply("X", "title")
            if not isinstance(painted, str):
                bad_paint.append(n)
        except Exception as e:
            bad_paint.append("%s(%s)" % (n, type(e).__name__))

    check("every role present in every theme", not bad_roles,
          "; ".join(bad_roles[:3]))
    check("every colour code in 0..255", not bad_codes,
          "; ".join(bad_codes[:5]))
    check("every theme paints", not bad_paint, "; ".join(bad_paint[:5]))

    # ---- the xterm-256 space really is covered
    covered = set()
    for n in te.THEMES[len(SHIPPED):]:
        covered.add(te._PALETTES[n]["primary"])
    check("all 256 codes have a theme", covered == set(range(256)),
          "missing %s" % sorted(set(range(256)) - covered)[:5])

    # ---- ANSI colour space maths
    check("ansi_rgb(16)==(0,0,0)", te.ansi_rgb(16) == (0, 0, 0),
          str(te.ansi_rgb(16)))
    check("ansi_rgb(231)==(255,255,255)", te.ansi_rgb(231) == (255, 255, 255),
          str(te.ansi_rgb(231)))
    check("ansi_rgb(232)==(8,8,8) grey ramp", te.ansi_rgb(232) == (8, 8, 8),
          str(te.ansi_rgb(232)))
    check("ansi_rgb(255)==(238,238,238)", te.ansi_rgb(255) == (238, 238, 238),
          str(te.ansi_rgb(255)))
    check("_nearest_cube snaps into 16..231",
          all(16 <= te._nearest_cube(r, g, b) <= 231
              for r, g, b in ((0, 0, 0), (255, 255, 255), (12, 200, 77),
                              (255, 0, 128))))

    # ---- no dead definitions left behind
    import inspect
    check("Theme.paint_code defined once",
          inspect.getsource(te.Theme).count("def paint_code") == 1)

    print()
    if failed:
        print("FAIL %d / %d" % (len(failed), len(failed) + 1))
        return 1
    print("PASS all theme checks (%d themes)" % len(te.THEMES))
    return 0


if __name__ == "__main__":
    sys.exit(main())
