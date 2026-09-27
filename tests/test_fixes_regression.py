"""Regression tests for the V122 audit fixes.

Each test pins one defect found in the audit, so it cannot come back:

  * the beacon      — telemetry is local-only and the .pyc is gone
  * the log         — every menu action is recorded, and logging never raises
  * the count       — "N files repacked" describes the pak that was written
  * the wait        — a version check is 5s, not 30s
  * the dpkg race   — the env repair is not a daemon thread
  * the launcher    — paths are derived, .bashrc is written once, no dupes
  * the numbers     — menu digits follow the theme, default is untouched
"""
import ast
import io
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def read(name):
    return (ROOT / name).read_text(encoding="utf-8", errors="replace")


def live_strings(name):
    """Every string literal in a file that is not a docstring.

    Parsed, not regexed: `#` and newlines inside string literals make
    text-level stripping silently corrupt real source.
    """
    tree = ast.parse(read(name))
    docs = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                 ast.AsyncFunctionDef)):
            continue
        if (node.body and isinstance(node.body[0], ast.Expr)
                and isinstance(node.body[0].value, ast.Constant)
                and isinstance(node.body[0].value.value, str)):
            docs.add(id(node.body[0].value))
    return [n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
            and id(n) not in docs]


def imports_of(name):
    """Every module name imported anywhere in a file, nested ones included."""
    tree = ast.parse(read(name))
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                found.add(a.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module.split(".")[0])
    return found


class NoBeacon(unittest.TestCase):
    """The tool must not talk to anyone but the user's own filesystem."""

    def test_telemetry_imports_nothing_that_reaches_the_network(self):
        banned = {"socket", "urllib", "urllib2", "requests", "http",
                  "http.client", "ftplib", "smtplib", "telnetlib", "aiohttp"}
        used = imports_of("telemetry.py")
        self.assertEqual(used & banned, set(),
                         "telemetry.py reached for the network: %s"
                         % sorted(used & banned))

    def test_telemetry_has_no_url_or_endpoint_literal(self):
        text = read("telemetry.py")
        for pat in (r"https?://", r"api\.telegram", r"t\.me/", r"bot_token",
                    r"BOT_TOKEN", r"CHAT_ID"):
            self.assertIsNone(re.search(pat, text),
                              "telemetry.py still mentions %r" % pat)

    def test_the_beacon_pyc_is_gone(self):
        self.assertFalse((ROOT / "telemetry.pyc").exists(),
                         "telemetry.pyc is back on disk")
        for name in ("ikram_patch.py", "update.py", "engines.py", "menus.py"):
            # docstrings are allowed to explain the removal; only live code
            # may not name the file.
            for lit in live_strings(name):
                self.assertNotIn("telemetry.pyc", lit,
                                 "%s still loads telemetry.pyc" % name)

    def test_only_the_compiled_engine_loads_a_pyc_by_path(self):
        # Loading a .pyc straight off disk bypasses sys.modules entirely, so
        # it is the one way the telemetry pin could be defeated. The engine's
        # own compiled modules are meant to load that way; telemetry is not.
        allowed = {"ikram.pyc", "ikram_patch.pyc"}
        for name in ("ikram_patch.py", "update.py", "menus.py", "engines.py",
                     "vip_ui.py"):
            for m in re.finditer(r"spec_from_file_location\(([^)]*)\)",
                                 read(name)):
                arg = m.group(1)
                for hit in re.findall(r"[\w./-]+\.pyc", arg):
                    base = hit.rsplit("/", 1)[-1]
                    if base.startswith("{"):          # f-string / format var
                        continue
                    self.assertIn(base, allowed,
                                  "%s loads %s by path" % (name, hit))


class TelemetryContract(unittest.TestCase):
    """The local log: useful, bounded, and incapable of breaking a run."""

    def setUp(self):
        import telemetry
        self.tel = telemetry
        self._saved = telemetry._LOG
        self.tmp = Path(tempfile.mkdtemp(prefix="tel_"))
        telemetry._LOG = self.tmp / "telemetry.log"

    def tearDown(self):
        self.tel._LOG = self._saved

    def test_login_and_error_both_land_in_the_file(self):
        self.tel.send_login()
        self.tel.send_error(ValueError("boom"), extra="pak.unpack")
        text = self.tel.log_file().read_text()
        self.assertIn("[login]", text)
        self.assertIn("[pak.unpack]", text)
        self.assertIn("ValueError: boom", text)

    def test_a_log_line_has_the_documented_shape(self):
        self.tel.send_event("pak.repack", file="a.pak", status="OK",
                            engine="tencent", files=7)
        line = self.tel.log_file().read_text().strip()
        cols = line.split(" ")
        self.assertRegex(line, r"^\[\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\]")
        self.assertIn("[pak.repack]", line)
        self.assertIn("[a.pak]", line)
        self.assertIn("[tencent]", line)
        self.assertIn("[files=7]", line)
        self.assertGreaterEqual(len(cols), 6)

    def test_newlines_in_a_field_cannot_forge_a_line(self):
        self.tel.send_event("x", file="a.pak\n[2020] [FAKE]")
        lines = self.tel.log_file().read_text().strip().split("\n")
        self.assertEqual(len(lines), 1, "a field injected a second line")
        self.assertIn("a.pak [2020] [FAKE]", lines[0])

    def test_rotation_bounds_the_file(self):
        path = self.tel.log_file()
        path.write_text("".join(
            "line %05d %s\n" % (i, "x" * 60) for i in range(20000)))
        self.assertGreater(path.stat().st_size, self.tel.MAX_BYTES)
        self.tel.log("trigger")
        text = path.read_text()
        self.assertLessEqual(len(text.split("\n")), self.tel.KEEP_LINES + 1)
        self.assertIn("trigger", text)

    def test_nothing_raises_even_with_no_writable_path(self):
        self.tel._LOG = Path("/proc/definitely/not/writable/telemetry.log")
        self.assertFalse(self.tel.log("nope"))
        self.tel.send_login()                 # must not raise
        self.tel.send_error(RuntimeError("x"))
        self.assertTrue(self.tel.app_version(), "app_version came back empty")
        self.assertTrue(self.tel.device_name(), "device_name came back empty")

    def test_a_read_only_log_does_not_break_the_caller(self):
        d = Path(tempfile.mkdtemp(prefix="telro_"))
        f = d / "telemetry.log"
        f.write_text("")
        f.chmod(0o444)
        self.tel._LOG = f
        try:
            if os.geteuid() != 0:
                self.assertFalse(self.tel.log("nope"))
        finally:
            f.chmod(0o644)

    def test_device_and_version_helpers_never_raise(self):
        self.assertTrue(self.tel.device_name())
        self.assertTrue(self.tel.app_version())


class EveryActionIsLogged(unittest.TestCase):
    """One seam, so no menu action can run unrecorded."""

    def test_both_menus_dispatch_through_act(self):
        text = read("vip_ui.py")
        # every action call is wrapped; a bare menus.* call would slip past
        bare = [m for m in re.findall(r"(?<!self\.act\(\")(?<!\.)\bmenus\."
                                     r"(\w+)\(self\)", text)]
        self.assertEqual(bare, [],
                         "menu actions called without the log seam: %s" % bare)
        self.assertIn("def act(self, name, fn", text)
        self.assertIn("def logged(self, name", text)

    def test_act_logs_success_and_failure(self):
        import telemetry
        import vip_ui
        saved = telemetry._LOG
        tmp = Path(tempfile.mkdtemp(prefix="telact_"))
        telemetry._LOG = tmp / "telemetry.log"
        vip = vip_ui.Vip.__new__(vip_ui.Vip)      # no ctor: only act is tested
        try:
            vip.act("demo.ok", lambda: "fine")
            self.assertIn("[demo.ok]", telemetry._LOG.read_text())
            with self.assertRaises(ValueError):
                vip.act("demo.bad", lambda: (_ for _ in ()).throw(ValueError("x")))
            text = telemetry._LOG.read_text()
            self.assertIn("[demo.bad]", text)
            self.assertIn("ValueError: x", text)
        finally:
            telemetry._LOG = saved

    def test_a_log_failure_does_not_break_the_action(self):
        import telemetry
        import vip_ui
        saved = telemetry._LOG
        telemetry._LOG = Path("/proc/nope/telemetry.log")
        vip = vip_ui.Vip.__new__(vip_ui.Vip)
        try:
            self.assertEqual(vip.act("demo.silent", lambda: 42), 42)
        finally:
            telemetry._LOG = saved

    def test_pak_flows_record_the_file_they_touched(self):
        text = read("ikram_patch.py")
        self.assertIn('telemetry.send_event("pak.unpack"', text)
        self.assertIn('telemetry.send_event("pak.repack"', text)


class RepackCount(unittest.TestCase):
    """"N files repacked" must describe the output, whichever engine ran."""

    def test_every_engine_path_returns_the_packed_count(self):
        text = read("engines.py")
        body = text[text.index("def repack_folder"):]
        body = body[:body.index("\ndef ", 10)]
        paths = [ln.strip() for ln in body.split("\n")
                 if ln.strip().startswith("return ")]
        self.assertEqual(len(paths), 3, "expected three engine return paths")
        for p in paths:
            self.assertIn("_packed_count(", p,
                          "an engine path returns its own count: %s" % p)

    def test_the_fallback_is_the_staged_set_not_a_raw_walk(self):
        import engines
        staged = engines._staged_files
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            (d / "a.lua").write_text("x")
            (d / "sub").mkdir()
            (d / "sub" / "b.lua").write_text("y")
            (d / ".hidden").write_text("z")
            (d / "sub" / ".dotfile").write_text("z")
            self.assertEqual([p.name for p in staged(d)], ["a.lua", "b.lua"])

    def test_a_pak_that_cannot_be_read_falls_back(self):
        import engines
        seen = []
        n = engines._count_packed(Path("/nonexistent/x.pak"), "tencent",
                                  None, seen.append)
        self.assertIsNone(n)
        self.assertTrue(seen, "the fallback was silent")
        self.assertEqual(engines._packed_count(
            Path("/nonexistent/x.pak"), "tencent", None,
            lambda *a: None, 99), 99)


class VersionCheckIsFiveSeconds(unittest.TestCase):
    def test_the_constant_is_five(self):
        import update
        self.assertEqual(update.VERSION_CHECK_TIMEOUT, 5)

    def test_the_release_download_keeps_its_own_longer_timeout(self):
        text = read("update.py")
        # the ZIP is tens of MB; only the version probe needed shortening
        self.assertIn("timeout=120", text)
        self.assertIn("timeout=VERSION_CHECK_TIMEOUT", text)
        self.assertNotIn("timeout=30)", text)


class EnvRepairIsNotADaemon(unittest.TestCase):
    """A dpkg killed halfway leaves the package database locked."""

    def test_the_repair_runs_inline(self):
        text = read("update.py")
        self.assertNotIn("daemon=True", text,
                         "the env repair is still a daemon thread")
        self.assertNotIn("threading.Thread", text)
        self.assertRegex(text, r"print\(\"INSTALLED_OK\"\)\s*\n(.*\n)*?\s*_fix_env\(\)")

    def test_the_wait_is_visible_to_the_user(self):
        text = read("update.py")
        self.assertIn("ENV_REPAIR:", text)

    def test_repair_imports_nothing_heavy(self):
        used = imports_of("update.py")
        self.assertNotIn("threading", used)


class LauncherPaths(unittest.TestCase):
    """No hardcoded install path, and one launcher however often it runs."""

    def _fix_env(self, home):
        import importlib
        import update
        importlib.reload(update)
        old = (os.environ.get("HOME"), os.environ.get("PREFIX"))
        os.environ["HOME"] = str(home)
        os.environ["PREFIX"] = str(Path(home) / "prefix")
        try:
            update._fix_env()
        finally:
            for k, v in zip(("HOME", "PREFIX"), old):
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        return update

    def test_no_hardcoded_engine_path_is_left(self):
        for name in ("update.py", "install.sh", "run.sh"):
            text = read(name)
            self.assertNotIn("Ikram_Tool/.engine", text,
                             "%s still hardcodes the install path" % name)

    def test_bashrc_is_created_even_when_it_does_not_exist(self):
        home = Path(tempfile.mkdtemp(prefix="home_"))
        self.assertFalse((home / ".bashrc").exists())
        self._fix_env(home)
        self.assertTrue((home / ".bashrc").exists())

    def test_running_it_twice_leaves_one_launcher(self):
        home = Path(tempfile.mkdtemp(prefix="home_"))
        self._fix_env(home)
        self._fix_env(home)
        text = (home / ".bashrc").read_text()
        self.assertEqual(text.count("ikram()"), 1)
        self.assertEqual(text.count("# Ikram Tool launcher"), 1)

    def test_the_launcher_points_at_this_install(self):
        home = Path(tempfile.mkdtemp(prefix="home_"))
        update = self._fix_env(home)
        text = (home / ".bashrc").read_text()
        self.assertIn(str(update.TOOL_DIR), text)

    def test_the_bin_launcher_uses_a_derived_dir(self):
        home = Path(tempfile.mkdtemp(prefix="home_"))
        self._fix_env(home)
        b = home / "prefix" / "bin" / "ikram"
        self.assertTrue(b.exists(), "bin/ikram was not written")
        text = b.read_text()
        self.assertIn("TOOL_DIR=", text)
        self.assertNotIn("Ikram_Tool/.engine", text)

    def test_placeholders_are_all_substituted(self):
        # A .format() on shell text full of braces raised, the write was
        # swallowed, and no launcher appeared with no error to show for it.
        home = Path(tempfile.mkdtemp(prefix="home_"))
        self._fix_env(home)
        for f in (home / ".bashrc",):
            self.assertNotIn("@@", f.read_text(), "%s kept a placeholder" % f)
        b = next(home.rglob("bin/ikram"), None)
        if b is not None:
            self.assertNotIn("@@", b.read_text(), "bin/ikram kept a placeholder")

    def test_every_placeholder_is_replaced_in_the_source(self):
        # Each @@X@@ in the shell templates needs a .replace() naming it, or
        # it reaches the user's .bashrc verbatim.
        text = read("update.py")
        for ph in sorted(set(re.findall(r"@@[A-Z_]+@@", text))):
            self.assertIn('"%s",' % ph, text,
                          "%s is never substituted" % ph)


class MenuNumbers(unittest.TestCase):
    def test_the_default_theme_renders_exactly_as_it_did(self):
        from box_engine import _DEFAULT_NUM_CYCLE, vip_num_cycle
        from theme_engine import Theme
        self.assertEqual(_DEFAULT_NUM_CYCLE,
                         {"0": 183, "1": 45, "2": 51,
                          "3": 39, "4": 118, "5": 119})
        self.assertEqual(vip_num_cycle(Theme("Original Color")._pal,
                                       "Original Color"), _DEFAULT_NUM_CYCLE)

    def test_no_module_still_carries_the_hardcoded_cycle(self):
        from box_engine import BoxEngine
        for name in ("box_engine.py", "vip_ui.py"):
            text = read(name)
            self.assertNotIn("{183", text.replace(" ", ""),
                             "%s hardcodes a number colour" % name)
        # the one place allowed to know the default is the default itself
        self.assertIn("_VIP_NUM", read("box_engine.py"))
        self.assertIsNotNone(BoxEngine)

    def test_other_themes_get_their_own_numbers(self):
        from box_engine import vip_num_cycle
        from theme_engine import THEMES, Theme
        seen = set()
        for name in THEMES:
            c = vip_num_cycle(Theme(name)._pal, name)
            self.assertEqual(set(c), set("012345"), name)
            seen.add(tuple(sorted(c.items())))
        self.assertGreater(len(seen), 1,
                           "every theme still lands on the same numbers")

    def test_the_renderer_reads_the_cycle_per_draw(self):
        text = read("box_engine.py")
        self.assertIn("def num_cycle(self)", text)
        self.assertIn("cycle = self.num_cycle", text)

    def test_vip_ui_shares_the_one_definition(self):
        text = read("vip_ui.py")
        self.assertIn("from box_engine import", text)
        self.assertIn("vip_num_cycle", text)
        self.assertNotIn('pal.get("warn", 214)', text,
                         "vip_ui still keeps a second copy of the mapping")


if __name__ == "__main__":
    unittest.main(verbosity=2)
