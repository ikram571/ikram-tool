"""IkramTool — decompile hang / timeout safety tests.

These are the regression tests for the two freezes that made the Lua tool look
broken instead of slow:

  1. the key sweep used to transform the WHOLE window for every one of its
     3,600 candidates just to read a 12-byte header, which froze the UI for
     minutes on a ~350KB chunk;
  2. ljd used to run inside this process while accepting a `timeout` argument
     it never enforced, so a chunk that sent ljd.tools.decompile into a loop
     could never be stopped.

Every case here is a hang that must not come back. The suite is deliberately
built around worst-case inputs (large, high-entropy, truncated, empty, and a
worker that never returns) rather than tidy ones.

Run:  python3 tests/test_decompile_safety.py
Exit 0 = all green.
"""
import os
import random
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import lua_pipeline as lp          # noqa: E402

WORK = Path(tempfile.mkdtemp(prefix="ikram_safety_"))
FAILS = []
PASSES = 0


def check(name, cond, detail=""):
    global PASSES
    if cond:
        PASSES += 1
        print("  PASS  %s" % name)
    else:
        FAILS.append(name)
        print("  FAIL  %s   %s" % (name, detail))


def reference_apply(buf, key, key_len, mode):
    """The original byte-at-a-time transform, kept as the oracle."""
    dec = bytearray(buf)
    for i in range(len(dec)):
        if mode == "xor":
            dec[i] ^= key[i % key_len]
        else:
            dec[i] = (dec[i] - key[i % key_len]) & 0xFF
    return bytes(dec)


def make_lua53_source(lines=700):
    body = []
    for i in range(lines):
        body.append("do")
        body.append("  local function f%d(x, y) return (x * %d + y) + %d end" % (i, i, i))
        body.append("  local t%d = { %d, %d, name = 'n%d' }" % (i, i, i + 1, i))
        body.append("  f%d(t%d[1], t%d[2])" % (i, i, i))
        body.append("end")
    return "\n".join(body) + "\nreturn 1\n"


def compile_chunk(src, dest, luac=None):
    sp = WORK / "src.lua"
    sp.write_text(src)
    exe = luac or shutil.which("luac_patched") or shutil.which("luac5.3") \
        or shutil.which("luac")
    if not exe:
        return None
    p = subprocess.run([exe, "-s", "-o", str(dest), str(sp)],
                       capture_output=True, timeout=120)
    return dest if p.returncode == 0 else None


def main():
    print("IkramTool — decompile safety suite")

    # ---------------------------------------------------------- transform
    print("\n[1] key transform is byte-identical to the original loop")
    rng = random.Random(1337)
    mism = 0
    combos = 0
    for size in (0, 1, 5, 63, 64, 65, 4096, 357954):
        buf = bytes(rng.randrange(256) for _ in range(size))
        for klen in range(1, 13):
            for mode in ("xor", "add"):
                key = bytes(rng.randrange(256) for _ in range(klen))
                combos += 1
                if lp._apply_key(buf, key, klen, mode) != \
                        reference_apply(buf, key, klen, mode):
                    mism += 1
    check("apply_key matches reference on %d combos" % combos, mism == 0,
          "%d mismatches" % mism)

    # A 12-byte key is fully determined by the known header, so the whole
    # transform must round-trip back to the original plaintext.
    probe = bytes(rng.randrange(256) for _ in range(5000))
    k12 = bytes(rng.randrange(256) for _ in range(12))
    enc = bytes(b ^ k12[i % 12] for i, b in enumerate(probe))
    check("apply_key round-trips xor(12)",
          lp._apply_key(enc, k12, 12, "xor") == probe)

    # ------------------------------------------------------------- sweep
    print("\n[2] key sweep is bounded and still recovers real keys")
    plain = compile_chunk(make_lua53_source(), WORK / "plain.luac")
    if not plain:
        check("built a lua53 chunk to sweep against", False, "no luac available")
    else:
        body = plain.read_bytes()
        recovered = 0
        for klen in range(1, 13):
            key = bytes(((i * 37) + 11) & 0xFF for i in range(klen))
            enc = bytes(b ^ key[i % klen] for i, b in enumerate(body))
            found, note = lp._xor_sweep(enc)
            if found and found[0][1][:12] == body[:12]:
                recovered += 1
        check("recovers xor keys of all 12 lengths", recovered == 12,
              "%d/12 recovered" % recovered)

    # The freeze itself: a large high-entropy file used to take minutes.
    big = WORK / "big.bin"
    big.write_bytes(os.urandom(357954))
    t0 = time.monotonic()
    found, note = lp._xor_sweep(big.read_bytes(), budget=45)
    sweep_s = time.monotonic() - t0
    check("357KB unknown sweep finishes under 20s", sweep_s < 20,
          "took %.1fs" % sweep_s)
    check("357KB unknown sweep reports a reason", bool(note), "empty note")
    check("357KB unknown sweep invents nothing", found == [], "found a key")

    # A tiny budget must cut the search short, not be ignored.
    t0 = time.monotonic()
    found2, note2 = lp._xor_sweep(big.read_bytes(), budget=0.0)
    check("zero budget returns immediately", time.monotonic() - t0 < 5,
          "%.1fs" % (time.monotonic() - t0))
    check("zero budget says so in the note", "budget" in note2, note2)

    for label, blob in (("empty", b""), ("4 bytes", b"\x1bLua"),
                        ("header only", b"\x1bLua\x53\x00\x19\x93")):
        try:
            f, n = lp._xor_sweep(blob)
            check("sweep survives %s input" % label, isinstance(n, str))
        except Exception as exc:
            check("sweep survives %s input" % label, False, repr(exc))

    # ---------------------------------------------------------------- ljd
    print("\n[3] ljd runs isolated and its timeout is real")
    worker = ROOT / "ljd_worker.py"
    check("ljd_worker.py ships with the tool", worker.is_file())

    # A missing deps/ljd must be a clean "engine not available", not a crash.
    real_ljd = lp.LJD_DIR
    try:
        lp.LJD_DIR = WORK / "no_such_ljd"
        check("ljd returns None when deps/ljd is absent",
              lp._ljd_decompile(b"\x1bLJ\x02" + os.urandom(64), timeout=10) is None)
    finally:
        lp.LJD_DIR = real_ljd

    for label, blob in (("empty", b""), ("garbage", os.urandom(4096))):
        try:
            r = lp._ljd_decompile(blob, timeout=20)
            check("ljd returns cleanly on %s" % label, r is None or bool(r))
        except Exception as exc:
            check("ljd returns cleanly on %s" % label, False, repr(exc))

    # The old bug: a worker that never returns used to freeze the tool
    # forever because ljd ran in-process. Now the parent must kill it.
    if worker.is_file():
        original = worker.read_bytes()
        hanger = WORK / "hang.py"
        hanger.write_text("import time\nwhile True:\n    time.sleep(1)\n")
        try:
            worker.write_bytes(hanger.read_bytes())
            t0 = time.monotonic()
            r = lp._ljd_decompile(os.urandom(2048), timeout=3)
            hung_s = time.monotonic() - t0
            check("a never-returning ljd worker is killed at the timeout",
                  r is None and hung_s < 15, "returned %r after %.1fs" % (r, hung_s))
        finally:
            worker.write_bytes(original)
        check("ljd_worker.py restored after the hang test",
              worker.read_bytes() == original)

    # ------------------------------------------------------------ pipeline
    print("\n[4] run() always answers and never hangs")

    class Prog:
        def __init__(self):
            self.seen = []

        def phase(self, msg):
            self.seen.append(str(msg))

    cases = []
    if plain:
        cases.append(("plain lua53", plain.read_bytes()))
    cases += [
        ("encrypted 357KB", os.urandom(357954)),
        ("tiny garbage", b"hello world this is not lua"),
        ("empty", b""),
        ("truncated header", b"\x1bLua\x53\x00\x19\x93\x0d"),
        ("luajit header junk", b"\x1bLJ\x02" + os.urandom(9000)),
    ]
    for name, blob in cases:
        f = WORK / ("case_%s.bin" % name.replace(" ", "_"))
        f.write_bytes(blob)
        out = WORK / ("out_%s" % name.replace(" ", "_"))
        t0 = time.monotonic()
        try:
            r = lp.run(f, out, progress=Prog())
            el = time.monotonic() - t0
            ok = (isinstance(r, dict) and "status" in r
                  and r["status"] in ("success", "disassembled", "failed"))
            check("run() answers on %s (%.1fs)" % (name, el), ok, repr(r)[:90])
        except Exception as exc:
            check("run() answers on %s" % name, False, repr(exc))

    # An unexpected error inside the cascade must become the normal honest
    # failure report, never a traceback that leaves the menu spinning.
    boom = RuntimeError("synthetic engine explosion")
    real_detect = lp.detect_report
    try:
        lp.detect_report = lambda data: (_ for _ in ()).throw(boom)
        r = lp.run(WORK / "case_tiny_garbage.bin", WORK / "out_boom", progress=None)
        check("a cascade exception becomes a failure report, not a crash",
              isinstance(r, dict) and r["ok"] is False
              and r["status"] == "failed", repr(r)[:90])
    except Exception as exc:
        check("a cascade exception becomes a failure report, not a crash",
              False, repr(exc))
    finally:
        lp.detect_report = real_detect

    # The whole-file budget has to surface as an honest note.
    real_budget = lp._CASCADE_BUDGET
    try:
        lp._CASCADE_BUDGET = 0.0
        blob = b"\x1bLJ\x02" + os.urandom(30000)
        f = WORK / "budget.bin"
        f.write_bytes(blob)
        r = lp.run(f, WORK / "out_budget", progress=None)
        labels = " ".join(a[0] for a in r.get("attempts", []))
        check("an exhausted time budget is reported, not hidden",
              "Time budget" in labels or r["status"] != "failed"
              or "Time budget" in " ".join(a[1] for a in r.get("attempts", [])),
              labels)
    except Exception as exc:
        check("an exhausted time budget is reported, not hidden", False, repr(exc))
    finally:
        lp._CASCADE_BUDGET = real_budget

    # ------------------------------------------- whole-request hard deadline
    print("\n[5] the time budget is a real ceiling, not just a check between tiers")
    import mega_lua as _ml

    check("mega_lua exposes a hard-deadline setter",
          hasattr(_ml, "set_hard_deadline")
          and hasattr(_ml, "clear_hard_deadline"))
    check("no deadline means the base timeout is untouched",
          _ml._scaled_timeout(180, 0) == 180)
    # 4 MB is 2 MB over the free allowance: 120 + 2*5 = 130
    check("size scaling still works with no deadline",
          _ml._scaled_timeout(120, 1 << 22) == 130)

    _ml.set_hard_deadline(time.monotonic() + 10000)
    try:
        check("a deadline far in the future does not shrink a small timeout",
              _ml._scaled_timeout(120, 0) == 120)
    finally:
        _ml.clear_hard_deadline()
    _ml.set_hard_deadline(time.monotonic() + 30)
    try:
        check("a 30s-left budget clamps a 120s engine timeout to the budget",
              1 <= _ml._scaled_timeout(120, 0) <= 30,
              "got %s" % _ml._scaled_timeout(120, 0))
        check("a clamped timeout is never zero (engine still runs)",
              _ml._scaled_timeout(120, 0) >= 1)
        _ml.set_hard_deadline(time.monotonic() - 1)
        check("an expired deadline still leaves 1s, never a broken timeout",
              _ml._scaled_timeout(120, 0) == 1)
    finally:
        _ml.clear_hard_deadline()
    check("clearing the deadline restores normal timeouts",
          _ml._scaled_timeout(120, 0) == 120)

    # run() must arm the deadline before the cascade and disarm it after, so a
    # long input cannot overshoot the budget by one whole engine run.
    armed, cleared = [], []
    real_set, real_clear = _ml.set_hard_deadline, _ml.clear_hard_deadline
    _ml.set_hard_deadline = lambda w: (armed.append(w), real_set(w))[1]
    _ml.clear_hard_deadline = lambda: (cleared.append(1), real_clear())[1]
    try:
        src_file = WORK / "budget_run.lua"
        src_file.write_bytes(b"\x1bLua" + os.urandom(200))
        lp.run(src_file, WORK / "budget_out")
        check("run() arms the engine deadline", len(armed) == 1)
        check("run() disarms the engine deadline afterwards", len(cleared) == 1)
    finally:
        _ml.set_hard_deadline = real_set
        _ml.clear_hard_deadline = real_clear

    # the sweep must report movement instead of showing one frozen line
    print("\n[6] the key sweep reports progress while it searches")
    seen = []

    class SweepProg:
        def phase(self, text):
            seen.append(text)

    class SweepProg2:
        def __init__(self, sink):
            self._sink = sink

        def phase(self, text):
            self._sink.append(text)

    lp._xor_sweep(bytes(rng.randrange(256) for _ in range(300000)),
                  progress=SweepProg(), budget=3.0)
    # How many offsets finish inside the budget depends on the phone's speed,
    # so only assert the contract: the sweep reports movement, every line names
    # the sweep, and each line carries a position. Counting lines was the one
    # assertion here that could fail on a slow device with nothing broken.
    check("a long sweep emits progress lines", len(seen) >= 1,
          "no progress at all")
    check("sweep progress names the sweep",
          seen and any("sweep" in s.lower() for s in seen))
    check("sweep progress carries a position",
          seen and any("offsets" in s for s in seen))

    print("\n[6b] an exhausted budget is reported honestly, not hidden")
    seen2 = []
    _sweep_found, note = lp._xor_sweep(
        bytes(rng.randrange(256) for _ in range(300000)),
        progress=SweepProg2(seen2), budget=0.0)
    check("a zero budget searches nothing at all", len(seen2) == 0,
          "%d progress line(s) for zero searched offsets" % len(seen2))
    check("a zero budget says the search was cut short",
          "stopped after 0/" in note and "budget" in note, "note=%r" % note)

    print("\n%d passed, %d failed" % (PASSES, len(FAILS)))
    if FAILS:
        for f in FAILS:
            print("  failed: %s" % f)
        return 1
    return 0


if __name__ == "__main__":
    try:
        code = main()
    finally:
        shutil.rmtree(WORK, ignore_errors=True)
    sys.exit(code)
