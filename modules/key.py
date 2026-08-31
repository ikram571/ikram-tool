import hashlib
import json
import os
from pathlib import Path

TOOL_ROOT = Path(__file__).resolve().parent.parent
KEY_FILE = TOOL_ROOT / 'ikram_key.json'
ACT_DIR = Path.home() / '.ikram_tool'
ACT_FILE = ACT_DIR / 'activated.json'

SALT = 'IKRAM_TOOL_SALT_v1'


def _hash(key: str) -> str:
    return hashlib.sha256((SALT + key.strip().lower()).encode()).hexdigest()


def load_config():
    if KEY_FILE.exists():
        try:
            return json.loads(KEY_FILE.read_text())
        except Exception:
            pass
    return {'tool': 'Ikram Tool', 'owner': 'ikram', 'key_hash': '', 'owner_hash': '', 'version': 2}


def is_activated() -> bool:
    cfg = load_config()
    if not cfg.get('key_hash'):
        return True
    if ACT_FILE.exists():
        try:
            return json.loads(ACT_FILE.read_text()).get('key_hash') == cfg['key_hash']
        except Exception:
            return False
    return False


def activate(key: str):
    cfg = load_config()
    if not cfg.get('key_hash'):
        return True
    if _hash(key) != cfg['key_hash']:
        return False
    ACT_DIR.mkdir(parents=True, exist_ok=True)
    ACT_FILE.write_text(json.dumps({'key_hash': cfg['key_hash']}))
    return True


def clear_activation():
    if ACT_FILE.exists():
        ACT_FILE.unlink()


def set_key(new_key: str, owner_pw: str = ''):
    cfg = load_config()
    if cfg.get('owner_hash') and not verify_owner(owner_pw):
        return False
    cfg['key_hash'] = _hash(new_key)
    KEY_FILE.write_text(json.dumps(cfg, indent=2))
    if ACT_FILE.exists():
        ACT_FILE.unlink()
    return True


def set_owner(owner_pw: str, current_pw: str = ''):
    cfg = load_config()
    if cfg.get('owner_hash') and not verify_owner(current_pw):
        return False
    cfg['owner_hash'] = _hash(owner_pw)
    KEY_FILE.write_text(json.dumps(cfg, indent=2))
    return True


def verify_owner(owner_pw: str) -> bool:
    cfg = load_config()
    if not cfg.get('owner_hash'):
        return True
    return _hash(owner_pw) == cfg['owner_hash']
