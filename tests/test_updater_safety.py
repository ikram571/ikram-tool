"""Updater safety: a bad or partial download must never damage the install.

The V119 installer deleted the old runtime first and copied the new payload
second, with nothing between those two steps. A truncated download therefore
left the tool uninstalled and unrecoverable without a manual reinstall. These
tests pin the transaction: validate -> move aside -> copy -> verify, and a
rollback on every failure path.
"""
import io
import os
import shutil
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO))

import update as u  # noqa: E402

WORK = REPO / ".updater_safety_test"
PASS, FAIL = [], []


def check(name, cond):
    (PASS if cond else FAIL).append(name)
    print("  %s  %s" % ("PASS" if cond else "FAIL", name))


def make_payload(root, files, version="V120"):
    """A payload directory: required entry points plus `files` extras."""
    root.mkdir(parents=True, exist_ok=True)
    for name in u.REQUIRED_ENTRIES:
        (root / name).write_text("# %s payload\n" % name)
    for name in files:
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("payload %s\n" % name)
    return root


def make_live(root, version="V119", runtime_files=0):
    """A realistic installed tool: runtime + user data that must survive."""
    root.mkdir(parents=True, exist_ok=True)
    for name in u.REQUIRED_ENTRIES:
        (root / name).write_text("# V119 installed %s\n" % name)
    for i in range(runtime_files):
        (root / ("mod_%02d.py" % i)).write_text("old module %d\n" % i)
    (root / "stale_from_v118.py").write_text("stale\n")
    (root / "stale_dir").mkdir(exist_ok=True)
    (root / "stale_dir" / "old.py").write_text("old\n")
    (root / "VERSION").write_text(version + "\n")
    (root / "ikram_key.json").write_text(
        '{\n  "version": "%s",\n  "key_hash": "7360b6c"}\n' % version)
    (root / "DROP").mkdir(exist_ok=True)
    (root / "DROP" / "user.pak").write_text("MY PRECIOUS PAK")
    (root / "RESULT").mkdir(exist_ok=True)
    (root / "RESULT" / "out.lua").write_text("-- my decompiled output\n")
    return root


def snapshot(root):
    """Every file's relative path + content, so a wipe is detectable."""
    out = {}
    for p in sorted(root.rglob("*")):
        rel = str(p.relative_to(root))
        if p.is_dir() and not p.is_symlink():
            out[rel + "/"] = None
        else:
            out[rel] = p.read_bytes()
    return out


def protected_intact(before, after, root):
    """User data, version state and the key must be bit-identical."""
    keys = ["DROP/", "DROP/user.pak", "RESULT/", "RESULT/out.lua"]
    if not all(k in after for k in keys):
        return False, "user data missing: %s" % [
            k for k in keys if k not in after]
    if before.get("VERSION") != after.get("VERSION"):
        return False, "VERSION changed"
    if before.get("ikram_key.json") != after.get("ikram_key.json"):
        return False, "ikram_key.json changed"
    return True, ""


def run_case(name, fn):
    live = WORK / name
    shutil.rmtree(live, ignore_errors=True)
    make_live(live)
    return fn(live)


def main():
    shutil.rmtree(WORK, ignore_errors=True)
    WORK.mkdir(parents=True)
    real_tool_dir = u.TOOL_DIR
    real_fix_env = u._fix_env
    u._fix_env = lambda: None          # never touch .bashrc/$PREFIX from a test
    try:
        print("IkramTool — updater safety suite\n")
        run_all(real_tool_dir)
    finally:
        u.TOOL_DIR = real_tool_dir
        u._fix_env = real_fix_env
        shutil.rmtree(WORK, ignore_errors=True)

    print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
    for f in FAIL:
        print("  failed: %s" % f)
    return 1 if FAIL else 0


def run_all(real_tool_dir):
    # ---- 1. validation rejects anything that is not a real release ----
    print("[1] a partial or empty payload is refused before anything is touched")

    def case_partial(live):
        u.TOOL_DIR = live
        before = snapshot(live)
        bad = make_payload(WORK / "payload_partial", ["one.py"])
        try:
            u._clean_replace(bad)
            check("partial payload raises InstallError", False)
        except u.InstallError as e:
            check("partial payload raises InstallError", True)
            check("partial payload reason is explained",
                  "missing" in str(e) or "truncated" in str(e))
        after = snapshot(live)
        check("partial payload leaves the install untouched", before == after)
        ok, why = protected_intact(before, after, live)
        check("partial payload keeps user data + key", ok)
        if not ok:
            print("        " + why)

    run_case("partial", case_partial)

    def case_empty(live):
        u.TOOL_DIR = live
        before = snapshot(live)
        empty = WORK / "payload_empty"
        empty.mkdir(exist_ok=True)
        try:
            u._clean_replace(empty)
            check("empty payload raises InstallError", False)
        except u.InstallError as e:
            check("empty payload raises InstallError", True)
            check("empty payload reason is explained", "no files" in str(e))
        check("empty payload leaves the install untouched",
              before == snapshot(live))

    run_case("empty", case_empty)

    def case_missing_dir(live):
        u.TOOL_DIR = live
        before = snapshot(live)
        try:
            u._clean_replace(WORK / "does_not_exist")
            check("missing payload dir raises InstallError", False)
        except u.InstallError:
            check("missing payload dir raises InstallError", True)
        check("missing payload leaves the install untouched",
              before == snapshot(live))

    run_case("missing", case_missing_dir)

    # ---- 2. zip-slip is refused ----
    print("\n[2] an archive that writes outside the staging dir is refused")

    def case_zip_slip(live):
        u.TOOL_DIR = live
        before = snapshot(live)
        evil = WORK / "evil.zip"
        with zipfile.ZipFile(evil, "w") as z:
            z.writestr("ikram.pyc", "x")
            z.writestr("../../escaped.txt", "pwned")
        dest = WORK / "unpack"
        dest.mkdir(exist_ok=True)
        try:
            u._safe_extract(evil, dest)
            check("zip-slip entry is refused", False)
        except u.InstallError as e:
            check("zip-slip entry is refused", True)
            check("zip-slip reason is explained", "unsafe path" in str(e))
        check("nothing escaped the staging dir",
              not (WORK / "escaped.txt").exists()
              and not (REPO.parent / "escaped.txt").exists())
        check("zip-slip leaves the install untouched", before == snapshot(live))

    run_case("zipslip", case_zip_slip)

    def case_absolute_member(live):
        u.TOOL_DIR = live
        evil = WORK / "abs.zip"
        with zipfile.ZipFile(evil, "w") as z:
            z.writestr("/etc/passwd", "x")
        dest = WORK / "unpack_abs"
        dest.mkdir(exist_ok=True)
        try:
            u._safe_extract(evil, dest)
            check("absolute archive member is refused", False)
        except u.InstallError:
            check("absolute archive member is refused", True)

    run_case("absmember", case_absolute_member)

    def case_empty_zip(live):
        u.TOOL_DIR = live
        z = WORK / "none.zip"
        with zipfile.ZipFile(z, "w"):
            pass
        dest = WORK / "unpack_empty"
        dest.mkdir(exist_ok=True)
        try:
            u._safe_extract(z, dest)
            check("empty archive is refused", False)
        except u.InstallError:
            check("empty archive is refused", True)

    run_case("emptyzip", case_empty_zip)

    # ---- 3. a failure part way through the copy rolls everything back ----
    print("\n[3] a copy that dies mid-install restores the old runtime")

    def case_copy_crash(live):
        u.TOOL_DIR = live
        before = snapshot(live)
        good = make_payload(
            WORK / "payload_good",
            ["brand_new_%02d.py" % i for i in range(45)])

        real_copy2 = shutil.copy2
        state = {"n": 0}

        def flaky(src, dst, *a, **kw):
            state["n"] += 1
            if state["n"] == 3:
                raise OSError(28, "No space left on device")
            return real_copy2(src, dst, *a, **kw)

        shutil.copy2 = flaky
        try:
            u._clean_replace(good)
            check("copy failure raises InstallError", False)
        except u.InstallError as e:
            check("copy failure raises InstallError", True)
            check("copy failure says the install was restored",
                  "restored" in str(e))
        finally:
            shutil.copy2 = real_copy2

        after = snapshot(live)
        check("rollback restores every original file", before == after)
        ok, why = protected_intact(before, after, live)
        check("rollback keeps user data + key", ok)
        if not ok:
            print("        " + why)
        check("rollback leaves no backup directory behind",
              not (live / u.BACKUP_DIR).exists())
        check("rollback leaves no half-written new file",
              not any(p.name.startswith("brand_new")
                      for p in live.iterdir()))

    run_case("copycrash", case_copy_crash)

    # ---- 4. the post-copy verification also triggers a rollback ----
    print("\n[4] a payload that copies but comes out incomplete is rejected")

    def case_incomplete(live):
        u.TOOL_DIR = live
        before = snapshot(live)
        good = make_payload(WORK / "payload_incomplete",
                            ["filler_%02d.py" % i for i in range(45)])

        real_copy2 = shutil.copy2

        def skip_one(src, dst, *a, **kw):
            if Path(src).name == "univ.py":
                return                      # pretend the copy silently vanished
            return real_copy2(src, dst, *a, **kw)

        shutil.copy2 = skip_one
        try:
            u._clean_replace(good)
            check("incomplete install raises InstallError", False)
        except u.InstallError as e:
            check("incomplete install raises InstallError", True)
            check("incomplete install names the missing entry",
                  "univ.py" in str(e))
        finally:
            shutil.copy2 = real_copy2

        check("incomplete install rolls back completely",
              before == snapshot(live))

    run_case("incomplete", case_incomplete)

    # ---- 5. a real payload installs, replaces and cleans up properly ----
    print("\n[5] a real payload installs cleanly and keeps user data")

    def case_good(live):
        u.TOOL_DIR = live
        before = snapshot(live)
        good = make_payload(WORK / "payload_real",
                            ["brand_new_%02d.py" % i for i in range(45)])
        check("_clean_replace succeeds on a real payload", u._clean_replace(good))
        after = snapshot(live)

        check("new payload file is installed",
              (live / "brand_new_00.py").exists())
        check("stale file from the old version is gone",
              not (live / "stale_from_v118.py").exists())
        check("stale directory from the old version is gone",
              not (live / "stale_dir").exists())
        check("updated entry point is in place",
              (live / "lua_pipeline.py").read_text().startswith("# lua_pipeline.py"))
        ok, why = protected_intact(before, after, live)
        check("real install keeps user data + key", ok)
        if not ok:
            print("        " + why)
        check("real install leaves no backup directory",
              not (live / u.BACKUP_DIR).exists())
        check("real install drops every old module", not any(
            p.name.startswith("mod_") for p in live.iterdir()))

    run_case("good", case_good)

    # ---- 6. do_install() end to end over a file:// release URL ----
    print("\n[6] do_install() end to end: success reports honestly, failure aborts")

    def case_e2e_bad(live):
        u.TOOL_DIR = live
        before = snapshot(live)
        bad = make_payload(WORK / "payload_e2e_bad", ["one.py"])
        zpath = WORK / "bad_release.zip"
        with zipfile.ZipFile(zpath, "w") as z:
            for f in bad.iterdir():
                z.write(f, f.name)
        u.latest_remote = lambda: {
            "version": "120", "url": zpath.as_uri()}

        buf = io.StringIO()
        real_stdout = sys.stdout
        sys.stdout = buf
        try:
            rc = u.do_install()
        finally:
            sys.stdout = real_stdout
        out = buf.getvalue()

        check("do_install returns False on a bad payload", rc is False)
        check("do_install says it aborted", "UPDATE_ABORTED" in out)
        check("do_install never claims INSTALLED_OK", "INSTALLED_OK" not in out)
        check("bad release leaves the install untouched",
              before == snapshot(live))
        check("bad release cleans up its staging dir",
              not (live / ".ikram_update_tmp").exists()
              and not (live / ".ikram_update.zip").exists())

    run_case("e2ebad", case_e2e_bad)

    def case_e2e_good(live):
        u.TOOL_DIR = live
        before = snapshot(live)
        good = make_payload(WORK / "payload_e2e_good",
                            ["brand_new_%02d.py" % i for i in range(45)])
        zpath = WORK / "good_release.zip"
        with zipfile.ZipFile(zpath, "w") as z:
            for f in sorted(good.rglob("*")):
                if f.is_file():
                    z.write(f, str(f.relative_to(good)))
        u.latest_remote = lambda: {
            "version": "120", "url": zpath.as_uri()}

        buf = io.StringIO()
        real_stdout = sys.stdout
        sys.stdout = buf
        try:
            rc = u.do_install()
        finally:
            sys.stdout = real_stdout
        out = buf.getvalue()

        check("do_install returns True on a real release", rc is True)
        check("do_install reports INSTALLED_OK", "INSTALLED_OK" in out)
        check("do_install stamps the new VERSION",
              (live / "VERSION").read_text().strip() == "V120")
        check("do_install keeps the key_hash",
              "7360b6c" in (live / "ikram_key.json").read_text())
        check("real release installs the new file",
              (live / "brand_new_00.py").exists())
        check("real release removed the stale file",
              not (live / "stale_from_v118.py").exists())
        after = snapshot(live)
        check("real release keeps the user PAK untouched",
              after.get("DROP/user.pak") == before.get("DROP/user.pak"))
        check("real release keeps the user's decompiled output",
              after.get("RESULT/out.lua") == before.get("RESULT/out.lua"))
        # ikram_key.json is rewritten on purpose: version bumps, key_hash must not
        import json as _json
        key_before = _json.loads(before["ikram_key.json"])
        key_after = _json.loads(after["ikram_key.json"])
        check("real release keeps the key_hash value",
              key_after.get("key_hash") == key_before.get("key_hash"))
        check("real release leaves no staging leftovers",
              not (live / ".ikram_update_tmp").exists()
              and not (live / ".ikram_update.zip").exists()
              and not (live / u.BACKUP_DIR).exists())

    run_case("e2egood", case_e2e_good)

    def case_e2e_nested(live):
        """Real releases sometimes ship one wrapper folder."""
        u.TOOL_DIR = live
        wrapper = make_payload(WORK / "payload_nested_root" / "IkramTool",
                               ["brand_new_%02d.py" % i for i in range(45)])
        check("_payload_root steps into a single wrapper folder",
              u._payload_root(wrapper.parent) == wrapper)
        flat = make_payload(WORK / "payload_flat", ["a.py"])
        check("_payload_root stays put on a flat payload",
              u._payload_root(flat) == flat)

    run_case("nested", case_e2e_nested)

    def case_min_files(live):
        u.TOOL_DIR = live
        thin = make_payload(WORK / "payload_thin", ["only_one.py"])
        ok, reason = u._validate_payload(thin)
        check("a 7-file payload is called truncated", not ok
              and "truncated" in reason)
        fat = make_payload(WORK / "payload_fat",
                           ["f%02d.py" % i for i in range(60)])
        ok, reason = u._validate_payload(fat)
        check("a 66-file payload validates", ok)
        check("validate reports the file count", "66" in reason)

    run_case("minfiles", case_min_files)

    def case_key_hash(live):
        """The activation hash must be one value in all three places.

        V119 shipped a transposed hash in update.py's fallback branch, which
        would have written a key the user can no longer validate.
        """
        u.TOOL_DIR = live
        import json as _json
        canonical = _json.loads(
            (REPO / "ikram_key.json").read_text())["key_hash"]
        check("update.py's constant is the canonical hash",
              u.CANONICAL_KEY_HASH == canonical)
        check("canonical hash is 64 hex chars", len(canonical) == 64
              and all(c in "0123456789abcdef" for c in canonical))

        rel = (REPO / "release.sh").read_text()
        check("release.sh no longer hardcodes a second copy of the hash",
              "7360b6c" not in rel)
        check("release.sh reads the hash from ikram_key.json",
              "key_hash" in rel and "ikram_key.json" in rel)

        # no other 64-hex literal may hide anywhere in the updater
        import re
        others = set(re.findall(
            r"\b[0-9a-f]{64}\b", (REPO / "update.py").read_text()))
        check("update.py holds exactly one hash literal", others == {canonical})

        # a corrupt ikram_key.json must be rebuilt with the right hash
        (live / "ikram_key.json").write_text("{ this is not json")
        good = make_payload(WORK / "payload_keyfix",
                            ["filler_%02d.py" % i for i in range(45)])
        zpath = WORK / "keyfix.zip"
        with zipfile.ZipFile(zpath, "w") as z:
            for f in sorted(good.rglob("*")):
                if f.is_file():
                    z.write(f, str(f.relative_to(good)))
        u.latest_remote = lambda: {"version": "120", "url": zpath.as_uri()}
        buf = io.StringIO()
        real_stdout = sys.stdout
        sys.stdout = buf
        try:
            rc = u.do_install()
        finally:
            sys.stdout = real_stdout
        rebuilt = _json.loads((live / "ikram_key.json").read_text())
        check("corrupt key file is rebuilt after a real install", rc is True)
        check("rebuilt key file keeps the canonical hash",
              rebuilt.get("key_hash") == canonical)
        check("rebuilt key file gets the new version",
              rebuilt.get("version") == "V120")

    run_case("keyhash", case_key_hash)


if __name__ == "__main__":
    sys.exit(main())
