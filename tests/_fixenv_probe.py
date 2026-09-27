"""Isolated _fix_env() driver for the release gates.

update._fix_env() resolves everything from Path.home() and touches the real
filesystem, so the gates cannot call it in-process without rewriting the
harness around it. This child process gets a fake $HOME and nothing else.
"""
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("upd_probe", ROOT / "update.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
mod._fix_env()
print("FIX_ENV_DONE")
sys.exit(0)
