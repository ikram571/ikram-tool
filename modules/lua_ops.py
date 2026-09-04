import os
import subprocess
import tempfile
from pathlib import Path

LUA_VERSION_HINTS = {
    b'\x1bLua\x51': 'Lua 5.1',
    b'\x1bLua\x52': 'Lua 5.2',
    b'\x1bLua\x53': 'Lua 5.3',
    b'\x1bLua\x54': 'Lua 5.4',
    b'\x1bLJ': 'LuaJIT',
}


def detect_lua(path) -> str:
    with open(path, 'rb') as f:
        head = f.read(5)
    if head.startswith(b'\x1bLua'):
        return LUA_VERSION_HINTS.get(head, f'unknown (0x{head.hex()})')
    if head.startswith(b'\x1bLJ'):
        return 'LuaJIT'
    try:
        text = open(path, 'r', encoding='utf-8', errors='strict').read(200)
        if 'function' in text or '--' in text or 'end' in text:
            return 'text (plain lua source)'
    except Exception:
        pass
    return 'unknown'


def compile_lua(src_path, out_path, lua_bin='luac') -> str:
    cmd = [lua_bin, '-o', str(out_path), str(src_path)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        return proc.stderr.strip() or 'compile failed'
    return None


def decompile_lua(src_path, out_path, unluac_jar=None) -> str:
    jar = unluac_jar or find_unluac_jar()
    if not jar or not os.path.exists(jar):
        return f'unluac.jar not found at {jar}'
    java = 'java'
    proc = subprocess.run([java, '-jar', jar, str(src_path)], capture_output=True)
    if proc.returncode != 0:
        return proc.stderr.decode(errors='replace').strip() or 'decompile failed'
    Path(out_path).write_bytes(proc.stdout)
    return None


def compile_batch(src_dir, out_dir, lua_bin='luac') -> (int, list):
    src_dir, out_dir = Path(src_dir), Path(out_dir)
    errors = []
    ok = 0
    for p in sorted(src_dir.rglob('*.lua')):
        rel = p.relative_to(src_dir).with_suffix('.luac')
        target = out_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        err = compile_lua(p, target, lua_bin)
        if err:
            errors.append(f'{p.name}: {err}')
        else:
            ok += 1
    return ok, errors


def find_unluac_jar():
    tool_dir = Path(__file__).resolve().parent.parent
    candidates = list(dict.fromkeys([
        str(tool_dir / 'unluac.jar'),
        str(Path(__file__).resolve().parent / 'unluac.jar'),
        str(Path.home() / 'CHETAN_TOOL' / 'LUA_TOOL' / 'unluac.jar'),
        str(Path.home() / 'unluac.jar'),
    ]))
    for c in candidates:
        if os.path.exists(c):
            return c
    return None
