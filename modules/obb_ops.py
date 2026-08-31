import shutil
import zipfile
from pathlib import Path


def unpack_obb(obb_path, out_dir, log=None):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    total = 0
    with zipfile.ZipFile(obb_path) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            target = out / info.filename
            if '..' in Path(info.filename).parts or target.resolve() not in out.resolve().parents and target.resolve() != out.resolve():
                if log:
                    log(f'  [X] skip unsafe path: {info.filename}')
                continue
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as src, open(target, 'wb') as dst:
                    shutil.copyfileobj(src, dst, 1024 * 1024)
                total += 1
                if log:
                    log(f'  {info.filename}  ({info.file_size} bytes)')
            except Exception as e:
                if log:
                    log(f'  [X] {info.filename}: {e}')
    return total


def repack_obb(in_dir, obb_path, log=None):
    root = Path(in_dir)
    if not root.is_dir():
        raise ValueError(f'Not a directory: {in_dir}')
    obb = Path(obb_path)
    obb.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    with zipfile.ZipFile(obb, 'w', zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(root.rglob('*')):
            if p.is_file():
                zf.write(p, p.relative_to(root))
                total += 1
                if log:
                    log(f'  {p.relative_to(root)}')
    return total
