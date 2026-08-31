#!/usr/bin/env python3
import os
import sys
import json
import shutil
import urllib.request
import subprocess
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.prompt import Prompt
from rich.box import DOUBLE, HEAVY, ROUNDED
from rich import print as rprint

from modules import pak as pakmod
from modules import ue4 as ue4mod
from modules import obb_ops
from modules import lua_ops
from modules import key as keymod

console = Console()

BRAND = '#989cff'
ACCENT = '#63c8ff'
SUCCESS = '#63c8ff'
WARN = '#e8c06a'
ERROR = '#e07a7a'
BORDER = '#767bd8'
MUTED = '#9b95ad'
TITLE = '#c3b8ff'
EXAMPLE = '#b8e6c8'
EXAMPLE_LABEL = '#7fd9a5'
EXAMPLE_BORDER = '#4f9e78'

HOME = Path.home()
TOOL_DIR = Path(__file__).parent
RESULT = TOOL_DIR / 'RESULT'

DROP = TOOL_DIR / 'DROP'
DROP_PAK = DROP / 'pak'
DROP_LUA = DROP / 'lua'
DROP_OBB = DROP / 'obb'
DROP_INJ = DROP / 'inject'

for d in (RESULT, DROP, DROP_PAK, DROP_LUA, DROP_OBB, DROP_INJ):
    d.mkdir(parents=True, exist_ok=True)

DOWNLOADS = Path('/storage/emulated/0/Download')

BANNER = f'''[bold {BRAND}]  ╔══════════════════════════════════════════════════╗
  ║  [bold {TITLE}]I K R A M   T O O L[/]  [dim]·[/]  [bold {ACCENT}]PAK[/] [dim]·[/] [bold {SUCCESS}]LUA[/] [dim]·[/] [bold {WARN}]OBB[/]        ║
  ╚══════════════════════════════════════════════════╝
  [dim {MUTED}]version 1.0  ·  fresh code  ·  by ikram[/]'''

UNLUAC = lua_ops.find_unluac_jar()

TOOL_VERSION = '1.0.3'
GITHUB_REPO = 'ikram571/ikram-tool'
GITHUB_API = f'https://api.github.com/repos/{GITHUB_REPO}/releases/latest'


def clear_screen():
    os.system('clear' if os.name != 'nt' else 'cls')


def check_for_updates(silent=False):
    try:
        req = urllib.request.Request(GITHUB_API, headers={'User-Agent': 'ikram-tool'})
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.loads(r.read().decode())
        latest = str(data.get('tag_name', '')).lstrip('v')
        if not latest:
            return
        if [int(x) for x in latest.split('.')] > [int(x) for x in TOOL_VERSION.split('.')]:
            console.print(f'[bold {SUCCESS}]Update available: v{latest} (aapke paas v{TOOL_VERSION})[/]')
            console.print(f'[dim {MUTED}]Downloading...[/dim {MUTED}]')
            _download_and_apply(data)
            return True
        if not silent:
            console.print(f'[dim {MUTED}]Already latest: v{TOOL_VERSION}[/dim {MUTED}]')
    except Exception:
        pass
    return False


def _download_and_apply(data):
    try:
        asset = next((a for a in data.get('assets', [])
                      if a.get('name', '').endswith('.zip')), None)
        if not asset:
            console.print(f'[bold {WARN}]No zip asset in release — kuch download nahi hua.[/]')
            return
        zip_url = asset['browser_download_url']
        zip_path = Path.home() / '.ikram_tool_update.zip'
        urllib.request.urlretrieve(zip_url, zip_path)
        import zipfile
        target = Path.home() / 'Ikram_Tool'
        tmp = Path.home() / '.ikram_tool_update'
        shutil.rmtree(tmp, ignore_errors=True)
        tmp.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(tmp)
        src = tmp
        nested = [p for p in tmp.iterdir() if p.is_dir()]
        if len(nested) == 1 and (nested[0] / 'ikram.py').exists():
            src = nested[0]
        for f in src.iterdir():
            dst = target / f.name
            if f.is_dir():
                shutil.rmtree(dst, ignore_errors=True)
                shutil.copytree(f, dst)
            else:
                shutil.copy2(f, dst)
        shutil.rmtree(tmp, ignore_errors=True)
        zip_path.unlink(missing_ok=True)
        console.print(f'[bold {SUCCESS}]Update installed — tool restart ho raha hai.[/]')
        os.execv(sys.executable, [sys.executable, __file__])
    except Exception as e:
        console.print(f'[bold {ERROR}]Update fail hua: {e}[/]')


def show_error(msg):
    console.print(Panel(f'[bold #ff9a9a]✘ {msg}[/]',
                        box=ROUNDED, border_style=ERROR, padding=(0, 2)))


def show_success(msg):
    console.print(f'[bold {SUCCESS}][OK] {msg}[/]')


def panel(content, title=None, style=BORDER, box=DOUBLE, subtitle=None):
    return Panel(content, title=f'[bold {TITLE}]{title}[/]' if title else None,
                 subtitle=f'[dim {MUTED}]{subtitle}[/]' if subtitle else None,
                 border_style=style, box=box)


def detail_box(desc):
    lines = []
    for line in desc.split('\n'):
        if ':' in line:
            label, rest = line.split(':', 1)
            lines.append(f'[bold {EXAMPLE_LABEL}]{label}:[{EXAMPLE}]{rest}[/]')
        else:
            lines.append(f'[{EXAMPLE}]{line}[/]')
    return Panel('\n'.join(lines), box=ROUNDED, border_style=EXAMPLE_BORDER,
                 padding=(0, 2))


def io_box():
    def sh(p):
        s = str(p)
        home = str(Path.home())
        return s.replace(home, '~')
    return Panel(
        f'[bold {EXAMPLE_LABEL}]INPUT FILES:[/] [{EXAMPLE}]{sh(DROP)} (pak, lua, obb, inject)[/]\n'
        f'[bold {EXAMPLE_LABEL}]OUTPUT:[/] [{EXAMPLE}]{sh(RESULT)}[/]',
        box=ROUNDED, border_style=EXAMPLE_BORDER, padding=(0, 2))


def build_menu_table(opts):
    t = Table(show_header=False, box=None, pad_edge=False)
    for num, name, desc in opts:
        t.add_row(f'  [bold {ACCENT}]{num}[/]  [bold bright_white]{name}[/]')
        if desc:
            t.add_row(detail_box(desc))
        t.add_row('')
    return t


def detect_pak_type(path):
    try:
        with open(path, 'rb') as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 4096))
            tail = f.read(4096)
    except Exception:
        return None
    if b'\xe1\x12\x6f\x5a' in tail:
        return 'ue4'
    if size >= 45:
        import struct
        magic = struct.unpack_from('<I', tail[-44:-40])[0] if len(tail) >= 44 else 0
        if magic ^ pakmod.pc.zuc_keystream()[2] == 0x4C515443:
            return 'tencent'
    return None


def safe_input(prompt: str = '') -> str:
    try:
        if prompt:
            console.print(prompt, end='')
        return input().strip()
    except (EOFError, KeyboardInterrupt):
        return ''


def friendly_error(e):
    if isinstance(e, FileNotFoundError):
        return 'File or folder not found.'
    if isinstance(e, PermissionError):
        return 'Access denied (permission).'
    if isinstance(e, (IsADirectoryError, NotADirectoryError)):
        return 'Confused file with folder — check the path.'
    msg = str(e).lower()
    if 'permission' in msg or 'denied' in msg:
        return 'Access denied (permission). Did you grant Download folder access?'
    if 'not found' in msg or 'no such file' in msg:
        return 'File or folder not found.'
    if 'unknown' in msg and 'pak' in msg:
        return 'This pak format is not supported.'
    if 'aes key' in msg:
        return 'This pak is encrypted — AES key required.'
    if 'compression' in msg and 'unsupported' in msg:
        return 'This file uses an unsupported compression type.'
    if 'corrupt' in msg or 'invalid' in msg or 'magic' in msg:
        return 'File is corrupt or in a wrong format.'
    if 'luac' in msg or 'not found' in msg:
        return 'luac not found. It is needed for Lua compile.'
    return f'Something went wrong ({type(e).__name__})'


def report_error(e):
    show_error(friendly_error(e))
    if os.environ.get('IKRAM_DEBUG'):
        console.print(f'[dim {MUTED}]{type(e).__name__}: {e}[/dim]')


def pick_file(folder, title, exts=None):
    folder = Path(folder)
    if not folder.exists():
        show_error(f'Folder not found: {folder}')
        return None
    items = sorted([p for p in folder.rglob('*') if p.is_file()])
    if exts:
        items = [p for p in items if p.suffix.lower() in exts]
    if not items:
        show_error(f'Koi file nahi mili in {folder} — sahi file daal kar dobara choose karo.')
        return None
    t = Table(box=ROUNDED, show_header=False, pad_edge=False, border_style=BORDER)
    t.add_column(justify='right', style=f'bold {ACCENT}', width=4)
    t.add_column(style='bright_white')
    t.add_column(justify='right', style=f'dim {MUTED}', width=10)
    for i, p in enumerate(items, 1):
        rel = str(p).replace(str(folder), '.')
        size = p.stat().st_size
        if size >= 1048576:
            sz = f'{size/1048576:.1f} MB'
        elif size >= 1024:
            sz = f'{size/1024:.1f} KB'
        else:
            sz = f'{size} B'
        t.add_row(f'{i}', f'  {rel}', sz)
    console.print(panel(t, title=title, box=ROUNDED))
    console.print(f'[dim {MUTED}]0 = cancel[/dim {MUTED}]')
    choice = safe_input(f'[bold {ACCENT}]-> Select number: [/]')
    try:
        idx = int(choice)
        if 1 <= idx <= len(items):
            return items[idx - 1]
    except ValueError:
        pass
    return None


def main_menu():
    clear_screen()
    opts = [
        ('1', 'PAK TOOL', 'unpack, inject, repack pak files'),
        ('2', 'LUA TOOL', 'compile / decompile lua files'),
        ('3', 'OBB TOOL', 'unpack / repack obb files'),
        ('4', 'REFRESH', 'refresh tool'),
        ('0', 'EXIT', 'close the tool'),
    ]
    t = build_menu_table(opts)
    console.print(BANNER)
    console.print(panel(t, title='◈ IKRAM TOOL — Main Menu ◈', subtitle='choose a number to proceed'))
    choice = safe_input(f'[bold {ACCENT}]-> Select: [/]')
    return choice


def refresh_tool():
    check_for_updates(silent=False)
    try:
        src = Path.home() / 'opencode' / 'Ikram_Tool'
        here = Path(__file__).resolve().parent
        if src.exists() and src.resolve() != here.resolve():
            for p in src.rglob('*.py'):
                dst = here / p.relative_to(src)
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(p, dst)
            console.print(f'[bold {SUCCESS}]Update done: latest files copied to {here}[/]')
    except Exception as e:
        console.print(f'[dim {MUTED}]Update copy failed ({e}) — continuing.[/dim {MUTED}]')
    keymod.clear_activation()
    os.execv(sys.executable, [sys.executable, __file__])


def pause():
    safe_input(f'\n[dim {MUTED}]Enter dabao continue karne ke liye...[/dim {MUTED}]')


def invalid_choice():
    show_error('Galat option choose kiya — upar diye gaye numbers me se sahi number choose karo.')


def pak_tool_menu():
    while True:
        clear_screen()
        opts = [
            ('[1]', 'Unpack PAK',
             'WORK: pak file kholo, saari files folder me nikal lo.\n'
             'INPUT: pak file -> DROP/pak\n'
             'OUTPUT: RESULT/extracted/'),
            ('[2]', 'Inject Lua',
             'WORK: ek lua file pak ke andar daalo.\n'
             'INPUT: lua -> DROP/lua  +  pak -> DROP/pak\n'
             'OUTPUT: RESULT/injected/*_injected.pak'),
            ('[3]', 'Inject File',
             'WORK: koi bhi file (uasset, png, json...) pak ke andar daalo.\n'
             'INPUT: pak -> DROP/pak  +  file -> DROP/inject\n'
             'OUTPUT: RESULT/injected/*_injected.pak'),
             ('[4]', 'Repack PAK',
              'WORK: pehle unpack karo, files edit karo, phir\n'
              '      edit wali files se wapas naya pak banao.\n'
              'INPUT: original pak -> DROP/pak\n'
              '      phir edited files wale folder ka path batao\n'
              '      (ENTER = RESULT/extracted khud le lega)\n'
              'OUTPUT: RESULT/repacked/*_repacked.pak'),
            ('[5]', 'REFRESH', 'refresh tool'),
            ('[0]', 'Back', 'back to main menu'),
        ]
        t = build_menu_table(opts)
        console.print(panel(t, title='◈ PAK TOOL ◈'))
        c = safe_input(f'[bold {ACCENT}]-> Select: [/]')
        if c == '1':
            pak_extract()
        elif c == '2':
            pak_inject_lua()
        elif c == '3':
            pak_inject_file()
        elif c == '4':
            pak_repack_folder()
        elif c == '5':
            refresh_tool()
        elif c == '0':
            return
        else:
            invalid_choice()


def drop_files(folder, exts):
    return sorted([p for p in Path(folder).rglob('*') if p.is_file() and p.suffix.lower() in exts])


def ensure_input_folder():
    if drop_files(DROP_PAK, ['.pak', '.obb']):
        return pick_file(DROP_PAK, f'Choose a PAK file [dim](DROP/pak)[/dim]', ['.pak', '.obb'])
    f = pick_file(DOWNLOADS if DOWNLOADS.exists() else HOME, 'Choose a PAK file', ['.pak', '.obb'])
    return f


def pak_extract():
    pakf = ensure_input_folder()
    if not pakf:
        return
    kind = detect_pak_type(pakf)
    out = RESULT / 'extracted' / pakf.stem
    console.print(f'[bold {ACCENT}]Detect: [bold bright_white]{kind or "unknown"}[/][/]')
    try:
        if kind == 'tencent':
            n = pakmod.unpack_pak(pakf, out, log=lambda s: console.print(s))
        elif kind == 'ue4':
            key = safe_input('-> AES key (leave blank if not encrypted): ')
            p = ue4mod.Ue4Pak(pakf, aes_key=key or None)
            n = p.extract_all(out)
        else:
            show_error('This pak type is not supported.')
            return
        show_success(f'Done: {n} files -> {out}')
    except Exception as e:
        report_error(e)
    pause()


def _pak_paths(pakf, kind):
    paths = set()
    try:
        if kind == 'tencent':
            with pakmod.PakReader(pakf) as pak:
                paths.update(k.strip('/') for k in pak.full_paths())
        elif kind == 'ue4':
            p = ue4mod.Ue4Pak(pakf)
            paths.update(k.strip('/') for k in p.files())
    except Exception:
        return []
    return sorted(paths)


def _unique_folders(paths):
    folders = set()
    for p in paths:
        parts = p.split('/')
        for i in range(1, len(parts)):
            folders.add('/'.join(parts[:i]))
    return sorted(folders)


def pick_pak_folder(pakf, kind):
    paths = _pak_paths(pakf, kind)
    if not paths:
        show_error('Pak ki files read nahi hui (galat/encrypted pak ho sakta hai).')
        return None
    folders = _unique_folders(paths)
    if not folders:
        console.print('[bold]Pak me koi subfolder nahi — root me hi files hain. Full path daalo.[/]')
        return safe_input('-> Pak ke andar full folder path (e.g. Content/LuaScripts): ').strip()
    base = ''
    while True:
        level = []
        for f in folders:
            if base:
                if not f.startswith(base + '/'):
                    continue
                rest = f[len(base) + 1:]
            else:
                rest = f
            parts = rest.split('/')
            if len(parts) == 1:
                level.append(parts[0])
        level = sorted(set(level))
        t = Table(box=ROUNDED, show_header=False, pad_edge=False, border_style=BORDER)
        t.add_column(justify='right', style=f'bold {ACCENT}', width=4)
        t.add_column(style='bright_white')
        for i, d in enumerate(level, 1):
            t.add_row(f'{i}', f'  [bold {SUCCESS}]▸ {d}/[/]')
        console.print(panel(t, title=f'Select folder [dim]— {base or "root"}[/]', box=ROUNDED))
        console.print(f'[dim {MUTED}]number = andar jao  ·  [bold]u[/] = upar  ·  [bold]this[/] = ye folder choose  ·  0 = cancel[/dim {MUTED}]')
        choice = safe_input(f'[bold {ACCENT}]-> Choose: [/]').strip().lower()
        if choice == '0':
            return None
        if not choice:
            continue
        if choice == 'u':
            if '/' in base:
                base = base.rsplit('/', 1)[0]
            else:
                base = ''
            continue
        if choice == 'this':
            return base
        try:
            idx = int(choice)
            if 1 <= idx <= len(level):
                base = f'{base}/{level[idx - 1]}'.strip('/')
                continue
        except ValueError:
            pass
        show_error('Galat choice — number, u, this ya 0 dalo.')


def _inject_into_pak(pakf, target_path, data):
    kind = detect_pak_type(pakf)
    target_path = target_path.strip('/').replace('\\', '/')
    out = RESULT / 'injected' / f'{pakf.stem}_injected.pak'
    out.parent.mkdir(parents=True, exist_ok=True)
    console.print(f'[bold {ACCENT}]Detect: [bold bright_white]{kind or "unknown"}[/] — injecting...[/]')
    if kind == 'tencent':
        with pakmod.PakReader(pakf) as pak:
            existing = pak.full_paths()
            force = target_path.lower() not in {k.strip('/').lower() for k in existing}
            n = pakmod.PakWriter(pak).inject_files(
                [(target_path, (data, None, Path(target_path).stem))], out,
                force_add=force, target_path=str(Path(target_path).parent))
        return n
    if kind == 'ue4':
        p = ue4mod.Ue4Pak(pakf)
        if target_path in p.files():
            n = p.repack(out, replacements={target_path: data})
        else:
            n = p.repack(out, add_files={target_path: data})
        return n
    raise ValueError('Unknown pak type')


def pak_inject_lua():
    lf = pick_file(DROP_LUA, 'Choose a Lua file', ['.lua', '.luac'])
    if not lf:
        return
    pakf = ensure_input_folder()
    if not pakf:
        return
    data = lf.read_bytes()
    console.print(f'[bold {ACCENT}]Lua detect: [bold bright_white]{lua_ops.detect_lua(lf)}[/][/]')
    kind = detect_pak_type(pakf)
    folder = pick_pak_folder(pakf, kind)
    if folder is None:
        console.print('[yellow]Cancelled[/yellow]')
        return
    name = safe_input(f'-> Lua ka naam (ENTER = {lf.name}): ').strip() or lf.name
    target_path = f'{folder}/{name}'.strip('/')
    try:
        n = _inject_into_pak(pakf, target_path, data)
        show_success(f'Done: {n} file -> {RESULT / "injected" / (pakf.stem + "_injected.pak")}')
        console.print(f'[dim {MUTED}]Injected at: {target_path}[/dim {MUTED}]')
        if n == 0:
            console.print('[yellow]No file found at that path and add failed too.[/yellow]')
    except Exception as e:
        report_error(e)
    pause()


def pak_inject_file():
    pakf = ensure_input_folder()
    if not pakf:
        return
    if drop_files(DROP_INJ, []):
        f = pick_file(DROP_INJ, 'Choose the file to inject', None)
    else:
        f = pick_file(DOWNLOADS if DOWNLOADS.exists() else HOME, 'Choose the file to inject', None)
    if not f:
        return
    data = f.read_bytes()
    target_path = safe_input('-> Target path inside pak (e.g. Content/X.uasset): ')
    if not target_path:
        return
    try:
        n = _inject_into_pak(pakf, target_path, data)
        console.print(f'[green]Done: {n} file -> {RESULT / "injected" / (pakf.stem + "_injected.pak")}[/green]')
    except Exception as e:
        report_error(e)
    pause()


def pak_repack_folder():
    pakf = ensure_input_folder()
    if not pakf:
        return
    edit_dir = Path(safe_input('-> Edited files folder (ENTER = RESULT/extracted): ') or (RESULT / 'extracted'))
    if not edit_dir.is_dir():
        show_error(f'Folder not found: {edit_dir}')
        return
    out = RESULT / 'repacked' / f'{pakf.stem}_repacked.pak'
    out.parent.mkdir(parents=True, exist_ok=True)
    console.print('[bold {WARN}]Repacking... (this can take a while on big paks)[/]')
    try:
        kind = detect_pak_type(pakf)
        if kind == 'tencent':
            with pakmod.PakReader(pakf) as pak:
                existing = pak.full_paths()
                edits = []
                for p in sorted(edit_dir.rglob('*')):
                    if not p.is_file() or p.name.startswith('.'):
                        continue
                    target = None
                    rel = str(p.relative_to(edit_dir)).replace('\\', '/')
                    for fp in existing:
                        if fp.lower() == rel.lower():
                            target = fp
                            break
                    if target is None:
                        for fp in existing:
                            if Path(fp).name.lower() == p.name.lower():
                                target = fp
                                break
                    if target is None:
                        target = rel
                    edits.append((target, (p.read_bytes(), None, p.stem)))
                n = pakmod.PakWriter(pak).inject_files(edits, out, force_add=True)
        elif kind == 'ue4':
            p = ue4mod.Ue4Pak(pakf)
            existing = p.files()
            repl, adds = {}, {}
            for fp in sorted(edit_dir.rglob('*')):
                if not fp.is_file() or fp.name.startswith('.'):
                    continue
                rel = str(fp.relative_to(edit_dir)).replace('\\', '/')
                data = fp.read_bytes()
                if rel in existing:
                    repl[rel] = data
                else:
                    adds[rel] = data
            n = p.repack(out, replacements=repl, add_files=adds)
        else:
            raise ValueError('Unknown pak type')
        show_success(f'Done: {n} files repacked -> {out}')
    except Exception as e:
        report_error(e)
    pause()


def lua_tool_menu():
    while True:
        clear_screen()
        opts = [
            ('[1]', 'Compile Lua',
             'WORK: source .lua ko bytecode .luac banao (game ke liye).\n'
             'INPUT: .lua file -> DROP/lua\n'
             'OUTPUT: RESULT/lua/*.luac'),
            ('[2]', 'Decompile Lua',
             'WORK: .luac bytecode ko readable source .lua banao.\n'
             'INPUT: .luac file -> DROP/lua\n'
             'OUTPUT: RESULT/lua/*_decompiled.lua'),
            ('[3]', 'Compile Folder',
             'WORK: ek folder ke saare .lua ek saath compile karo.\n'
             'INPUT: folder ka path batao\n'
             'OUTPUT: RESULT/lua_compiled/'),
            ('[4]', 'REFRESH', 'refresh tool'),
            ('[0]', 'Back', 'back to main menu'),
        ]
        t = build_menu_table(opts)
        console.print(panel(t, title='◈ LUA TOOL ◈'))
        c = safe_input(f'[bold {ACCENT}]-> Select: [/]')
        if c == '1':
            lua_compile_one()
        elif c == '2':
            lua_decompile_one()
        elif c == '3':
            lua_compile_folder()
        elif c == '4':
            refresh_tool()
        elif c == '0':
            return
        else:
            invalid_choice()


def lua_compile_one():
    src = pick_file(DROP_LUA, 'Lua source file', ['.lua'])
    if not src:
        return
    out = RESULT / 'lua' / f'{src.stem}.luac'
    out.parent.mkdir(parents=True, exist_ok=True)
    console.print('[bold {ACCENT}]Compiling with luac 5.3...[/]')
    err = lua_ops.compile_lua(src, out)
    if err:
        show_error(err)
    else:
        show_success(f'Compiled -> {out} ({out.stat().st_size} B)')
    pause()


def lua_decompile_one():
    src = pick_file(DROP_LUA, 'Lua bytecode file', ['.luac', '.lua'])
    if not src:
        return
    if not UNLUAC:
        show_error('unluac.jar not found — check the LUA_TOOL folder.')
        pause()
        return
    out = RESULT / 'lua' / f'{src.stem}_decompiled.lua'
    out.parent.mkdir(parents=True, exist_ok=True)
    console.print('[bold {ACCENT}]Decompiling with unluac...[/]')
    err = lua_ops.decompile_lua(src, out, UNLUAC)
    if err:
        show_error(err)
    else:
        show_success(f'Decompiled -> {out}')
    pause()


def lua_compile_folder():
    src_dir = Path(safe_input('-> Lua source folder (ENTER = DROP/lua): ') or DROP_LUA)
    if not src_dir.is_dir():
        show_error(f'Folder not found: {src_dir}')
        return
    out = RESULT / 'lua_compiled'
    ok, errors = lua_ops.compile_batch(src_dir, out)
    show_success(f'Compiled {ok} files -> {out}')
    for e in errors[:20]:
        console.print(f'[bold {WARN}]  - {e}[/]')
    pause()


def obb_tool_menu():
    while True:
        clear_screen()
        opts = [
            ('[1]', 'Unpack OBB',
             'WORK: obb file kholo, uski files folder me nikalo.\n'
             'INPUT: .obb file -> DROP/obb\n'
             'OUTPUT: RESULT/obb/'),
            ('[2]', 'Repack OBB',
             'WORK: folder ki files se wapas naya .obb banao.\n'
             'INPUT: unpack wale folder ka path batao\n'
             'OUTPUT: RESULT/*.obb'),
            ('[3]', 'REFRESH', 'refresh tool'),
            ('[0]', 'Back', 'back to main menu'),
        ]
        t = build_menu_table(opts)
        console.print(panel(t, title='◈ OBB TOOL ◈'))
        c = safe_input(f'[bold {ACCENT}]-> Select: [/]')
        if c == '1':
            obb_unpack()
        elif c == '2':
            obb_repack()
        elif c == '3':
            refresh_tool()
        elif c == '0':
            return
        else:
            invalid_choice()


def obb_unpack():
    if drop_files(DROP_OBB, ['.obb', '.zip']):
        f = pick_file(DROP_OBB, 'Choose an OBB file [dim](DROP/obb)[/dim]', ['.obb', '.zip'])
    else:
        f = pick_file(DOWNLOADS if DOWNLOADS.exists() else HOME, 'Choose an OBB file', ['.obb', '.zip'])
    if not f:
        return
    out = RESULT / 'obb' / f.stem
    console.print('[bold {ACCENT}]Unpacking...[/]')
    try:
        n = obb_ops.unpack_obb(f, out, log=lambda s: console.print(s))
        show_success(f'Done: {n} files -> {out}')
    except Exception as e:
        report_error(e)
    pause()


def obb_repack():
    src = Path(safe_input(f'-> Folder path (ENTER = {RESULT / "obb"}): ') or (RESULT / 'obb'))
    if not src.is_dir():
        show_error(f'Folder not found: {src}')
        return
    out = RESULT / f'{src.name}.obb'
    out.parent.mkdir(parents=True, exist_ok=True)
    console.print('[bold {ACCENT}]Repacking...[/]')
    try:
        n = obb_ops.repack_obb(src, out, log=lambda s: console.print(s))
        show_success(f'Done: {n} files -> {out}')
    except Exception as e:
        report_error(e)
    pause()


def check_key():
    if keymod.is_activated():
        return True
    clear_screen()
    console.print(BANNER)
    console.print(panel('[bold bright_white]Key Required — Tool Locked[/]\n\n[dim ' + MUTED + ']No key? Contact the owner. Authorized users only.[/dim ' + MUTED + ']', title='KEY LOCK'))
    key = Prompt.ask(f'[bold {ACCENT}]Enter your Ikram Tool key[/]').strip()
    if keymod.activate(key):
        clear_screen()
        console.print(f'[bold {SUCCESS}]✔ KEY VALID — UNLOCKED![/]')
        return True
    clear_screen()
    console.print(f'[bold {ERROR}]✘ INVALID KEY — TOOL LOCKED[/]')
    return False

def main():
    clear_screen()
    if len(sys.argv) > 1 and sys.argv[1] == '--setkey':
        new_key = sys.argv[2].strip()
        owner_pw = Prompt.ask('[bold blue]Owner password:[/]', password=True).strip()
        if not keymod.set_key(new_key, owner_pw):
            console.print(f'[bold {ERROR}]Wrong owner password. Key not changed.[/]')
            return
        console.print(f'[bold {SUCCESS}]New master key set. All old keys are now invalid.[/]')
        console.print(f'[bold {WARN}]New key:[/] ' + new_key)
        return
    if len(sys.argv) > 1 and sys.argv[1] == '--setowner':
        new_pw = Prompt.ask('[bold blue]New owner password:[/]', password=True).strip()
        cur_pw = Prompt.ask('[bold blue]Current owner password (ENTER = first time):[/]', password=True).strip()
        if not keymod.set_owner(new_pw, cur_pw):
            console.print(f'[bold {ERROR}]Wrong current password. Owner password not changed.[/]')
            return
        console.print(f'[bold {SUCCESS}]Owner password set/changed.[/]')
        return
    console.print(BANNER)
    console.print(io_box())
    if UNLUAC:
        console.print(f'[dim {MUTED}]unluac.jar: found[/dim {MUTED}]')
    else:
        console.print(f'[bold {WARN}]unluac.jar not found — check the LUA_TOOL folder[/bold {WARN}]')
    if not check_key():
        console.print(f'[bold {ERROR}]Locked. Contact the owner for the correct key.[/]')
        return
    check_for_updates(silent=True)
    while True:
        try:
            c = main_menu()
            if c == '1':
                pak_tool_menu()
            elif c == '2':
                lua_tool_menu()
            elif c == '3':
                obb_tool_menu()
            elif c == '4':
                refresh_tool()
            elif c == '0':
                console.print(f'[bold {SUCCESS}]Bye![/]')
                break
            else:
                invalid_choice()
        except (KeyboardInterrupt, EOFError):
            console.print('\n[dim]bye[/]')
            break


if __name__ == '__main__':
    main()