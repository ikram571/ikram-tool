import struct
from hashlib import sha1
from pathlib import Path


MAGIC = 0x5A6F12E1
MAGIC_BYTES = b'\xe1\x12\x6f\x5a'


def align(x):
    return (x + 15) & ~15


def unpad(b, n=1):
    return b[:len(b) - n]


class Reader:
    def __init__(self, data, cursor=0):
        self.d = data
        self.c = cursor

    def u1(self):
        v = self.d[self.c]
        self.c += 1
        return v

    def u4(self):
        v = struct.unpack_from('<I', self.d, self.c)[0]
        self.c += 4
        return v

    def u8(self):
        v = struct.unpack_from('<Q', self.d, self.c)[0]
        self.c += 8
        return v

    def i4(self):
        v = struct.unpack_from('<i', self.d, self.c)[0]
        self.c += 4
        return v

    def raw(self, n):
        v = self.d[self.c:self.c + n]
        self.c += n
        return v

    def fstring(self):
        n = self.i4()
        if n == 0:
            return ''
        if n < 0:
            data = self.raw(-n * 2)
            return data.decode('utf-16-le', errors='replace').rstrip('\x00')
        return self.raw(n).rstrip(b'\x00').decode('utf-8', errors='replace')


class Writer:
    def __init__(self):
        self.out = bytearray()

    def u1(self, v):
        self.out += struct.pack('<B', v & 0xFF)

    def u4(self, v):
        self.out += struct.pack('<I', v & 0xFFFFFFFF)

    def u8(self, v):
        self.out += struct.pack('<Q', v)

    def raw(self, b):
        self.out += b

    def fstring(self, s):
        b = s.encode('utf-8') + b'\x00'
        self.out += struct.pack('<i', len(b))
        self.out += b


class Block:
    def __init__(self, start, end):
        self.start = start
        self.end = end


class Entry:
    def __init__(self, offset=0, compressed=0, uncompressed=0, compression_slot=None,
                 hash_val=None, blocks=None, flags=0, compression_block_size=0):
        self.offset = offset
        self.compressed = compressed
        self.uncompressed = uncompressed
        self.compression_slot = compression_slot
        self.hash = hash_val
        self.blocks = blocks
        self.flags = flags
        self.compression_block_size = compression_block_size

    def is_encrypted(self):
        return bool(self.flags & 1)

    def serialized_size(self, version, compression_u8):
        size = 24
        size += 1 if compression_u8 else 4
        size += 20
        if version == 1:
            size += 8
        if version >= 3 and self.compression_slot is not None:
            size += 4 + 16 * (len(self.blocks) if self.blocks else 0)
        if version >= 3:
            size += 1 + 4
        return size


def read_entry(r, version, compression_u8):
    offset = r.u8()
    compressed = r.u8()
    uncompressed = r.u8()
    if compression_u8:
        c = r.u1()
    else:
        c = r.u4()
    compression_slot = None if c == 0 else c - 1
    if version == 1:
        r.u8()
    hash_val = r.raw(20)
    blocks = None
    if version >= 3 and compression_slot is not None:
        count = r.u4()
        blocks = [Block(r.u8(), r.u8()) for _ in range(count)]
    flags = 0
    block_size = 0
    if version >= 3:
        flags = r.u1()
        block_size = r.u4()
    return Entry(offset, compressed, uncompressed, compression_slot,
                 hash_val, blocks, flags, block_size)


def write_entry(w, e, version, compression_u8, index):
    w.u8(e.offset if index else 0)
    w.u8(e.compressed)
    w.u8(e.uncompressed)
    if compression_u8:
        w.u1((e.compression_slot + 1) if e.compression_slot is not None else 0)
    else:
        w.u4((e.compression_slot + 1) if e.compression_slot is not None else 0)
    if version == 1:
        w.u8(0)
    w.raw(e.hash or b'\x00' * 20)
    if version >= 3:
        if e.compression_slot is not None:
            blocks = e.blocks or []
            w.u4(len(blocks))
            for b in blocks:
                w.u8(b.start)
                w.u8(b.end)
        w.u1(e.flags)
        w.u4(e.compression_block_size)


def read_encoded_entry(r, version):
    bits = r.u4()
    compression = None if ((bits >> 23) & 0x3f) == 0 else ((bits >> 23) & 0x3f) - 1
    encrypted = (bits & (1 << 22)) != 0
    block_count = (bits >> 6) & 0xffff
    block_size = bits & 0x3f
    if block_size == 0x3f:
        block_size = r.u4()
    else:
        block_size <<= 11

    def var_int(bit):
        if bits & (1 << bit):
            return r.u4()
        return r.u8()

    offset = var_int(31)
    uncompressed = var_int(30)
    compressed = uncompressed if compression is None else var_int(29)

    base = 8 + 8 + 8 + 4 + 20 + 4 + 16 * block_count + 1 + 4

    blocks = None
    if block_count == 1 and not encrypted:
        blocks = [Block(base, base + compressed)]
    elif block_count > 0:
        index = base
        blocks = []
        for _ in range(block_count):
            bs = r.u4()
            blocks.append(Block(index, index + bs))
            if encrypted:
                bs = align(bs)
            index += bs

    return Entry(offset, compressed, uncompressed, compression,
                 None, blocks, encrypted, block_size)


def find_magic(content):
    tail_start = max(0, len(content) - 4096)
    tail = bytes(content[tail_start:])
    pos = -1
    while True:
        i = tail.find(MAGIC_BYTES, pos + 1)
        if i == -1:
            break
        pos = i
    return None if pos == -1 else tail_start + pos


def aes_ecb_decrypt(data, key):
    from Crypto.Cipher import AES
    key = bytes.fromhex(key.replace('0x', '').replace(' ', ''))
    cipher = AES.new(key, AES.MODE_ECB)
    return cipher.decrypt(data)


class Ue4Pak:
    def __init__(self, file_path, aes_key=None):
        self.file_path = Path(file_path)
        self.aes_key = aes_key
        with open(self.file_path, 'rb') as f:
            self.content = f.read()
        self._parse_footer()
        self._parse_index()

    def _parse_footer(self):
        mp = find_magic(self.content)
        if mp is None:
            raise ValueError('Not a standard Unreal Engine pak (magic not found)')
        self.magic_pos = mp
        self.version = struct.unpack_from('<I', self.content, mp + 4)[0]
        if not (1 <= self.version <= 11):
            raise ValueError(f'Unsupported pak version: {self.version}')
        self.index_offset = struct.unpack_from('<Q', self.content, mp + 8)[0]
        self.index_size = struct.unpack_from('<Q', self.content, mp + 16)[0]
        self.index_hash = bytes(self.content[mp + 24:mp + 44])
        self.encrypted_index = self.version >= 4 and self.content[mp - 1] != 0
        footer_size = len(self.content) - (mp - 17)
        self.compression_u8 = (self.version == 8 and footer_size == 189)
        self.footer_size = footer_size
        if self.index_offset + self.index_size > len(self.content):
            raise ValueError('Invalid index offset/size')

    def _read_index_blob(self):
        data = self.content[self.index_offset:self.index_offset + self.index_size]
        if self.encrypted_index:
            if not self.aes_key:
                raise ValueError('Index encrypted — AES key chahiye')
            data = aes_ecb_decrypt(data, self.aes_key)
        return data

    def _parse_index(self):
        blob = self._read_index_blob()
        r = Reader(blob)
        self.mount_point = r.fstring()
        count = r.u4()
        self.entries = {}
        self.dirs = {}
        if self.version >= 10:
            r.u8()
            if r.u4() != 0:
                r.u8()
                r.u8()
                r.raw(20)
            fdi_off = None
            if r.u4() != 0:
                fdi_off = r.u8()
                fdi_size = r.u8()
                r.raw(20)
            encoded_size = r.u4()
            encoded_blob = r.raw(encoded_size)
            non_encoded_count = r.u4()
            non_encoded = [read_entry(r, self.version, self.compression_u8)
                           for _ in range(non_encoded_count)]
            if fdi_off is None:
                raise ValueError('v10+ pak without full directory index unsupported')
            self._parse_full_directory_index(fdi_off, fdi_size, non_encoded, encoded_blob)
            return
        for _ in range(count):
            name = r.fstring()
            self.entries[name] = read_entry(r, self.version, self.compression_u8)
        for name in self.entries:
            d = name.rsplit('/', 1)[0] if '/' in name else ''
            self.dirs.setdefault(d, []).append(name)

    def _parse_full_directory_index(self, fdi_off, fdi_size, non_encoded, encoded_blob):
        blob = self.content[fdi_off:fdi_off + fdi_size]
        r = Reader(blob)
        dir_count = r.u4()
        for _ in range(dir_count):
            dir_name = r.fstring()
            file_count = r.u4()
            for _ in range(file_count):
                file_name = r.fstring()
                encoded_offset = struct.unpack_from('<i', blob, r.c)[0]
                r.c += 4
                path = (dir_name.strip('/') + file_name)
                if encoded_offset == -2147483648:
                    continue
                if encoded_offset >= 0:
                    er = Reader(encoded_blob, encoded_offset)
                    self.entries[path] = read_encoded_entry(er, self.version)
                else:
                    self.entries[path] = non_encoded[(-encoded_offset) - 1]
        for name in self.entries:
            d = name.rsplit('/', 1)[0] if '/' in name else ''
            self.dirs.setdefault(d, []).append(name)

    def files(self):
        return sorted(self.entries)

    def read_file(self, path):
        e = self.entries.get(path)
        if e is None:
            return None
        off = e.offset
        if off + e.serialized_size(self.version, self.compression_u8) > len(self.content):
            return None
        data_off = off + e.serialized_size(self.version, self.compression_u8)
        total = align(e.compressed) if e.is_encrypted() else e.compressed
        raw = self.content[data_off:data_off + total]
        if e.is_encrypted():
            if not self.aes_key:
                raise ValueError(f'Encrypted data — AES key chahiye ({path})')
            raw = aes_ecb_decrypt(raw, self.aes_key)[:e.compressed]
        if e.compression_slot is None:
            return raw
        comp = self._compression_method(e.compression_slot)
        if e.blocks:
            out = bytearray()
            for b in e.blocks:
                bs = b.end - b.start
                block_off = off + b.start
                piece = self.content[block_off:block_off + bs]
                out += self._decompress(piece, comp)
            return bytes(out)
        return self._decompress(raw, comp)

    def _compression_method(self, slot):
        default = ['zlib', 'gzip', 'oodle', 'zstd', 'lz4']
        if self.version < 8:
            return default[slot] if slot < 3 else 'none'
        off = self.magic_pos + 44
        slots = 4 if self.compression_u8 else 5
        for i in range(slots):
            name = bytes(self.content[off + i * 32:off + i * 32 + 32]).split(b'\x00')[0].decode(errors='ignore')
            if i == slot:
                return name.lower() if name else (default[slot] if slot < len(default) else 'none')
        return 'none'

    def _decompress(self, data, comp):
        if comp == 'zlib':
            import zlib
            return zlib.decompress(data)
        if comp == 'gzip':
            import gzip
            return gzip.decompress(data)
        if comp == 'zstd':
            import zstandard
            return zstandard.ZstdDecompressor().decompress(data)
        if comp == 'lz4':
            import lz4.block
            return lz4.block.decompress(data)
        raise ValueError(f'Unsupported compression: {comp}')

    def extract_all(self, out_dir):
        out = Path(out_dir)
        n = 0
        for path in self.files():
            safe = path.strip('/').lstrip('.')
            safe = safe.replace('..', '__')
            dst = out / safe
            dst.parent.mkdir(parents=True, exist_ok=True)
            data = self.read_file(path)
            if data is not None:
                dst.write_bytes(data)
                n += 1
        return n

    def repack(self, out_path, replacements=None, add_files=None, delete=None):
        if self.version >= 10:
            raise ValueError('v10+ repack abhi supported nahi (sirf extract)')
        replacements = replacements or {}
        add_files = add_files or {}
        delete = delete or set()

        out = bytearray()
        new_entries = {}
        order = list(self.files()) + [p for p in add_files if p not in self.entries]

        def write_data_record(data):
            e = Entry(offset=0, compressed=len(data), uncompressed=len(data),
                      compression_slot=None, hash_val=sha1(data).digest(),
                      blocks=None, flags=0, compression_block_size=0)
            nonlocal out
            record_start = len(out)
            w = Writer()
            write_entry(w, e, self.version, self.compression_u8, index=False)
            out += w.out
            out += data
            e.offset = record_start
            return e

        for path in order:
            if path in delete:
                continue
            if path in replacements:
                data = replacements[path]
            elif path in add_files:
                data = add_files[path]
            else:
                data = self.read_file(path)
                if data is None:
                    continue
            new_entries[path] = write_data_record(data)

        index_offset = len(out)
        w = Writer()
        w.fstring(self.mount_point)
        w.u4(len(new_entries))
        for path in sorted(new_entries):
            w.fstring(path)
            write_entry(w, new_entries[path], self.version, self.compression_u8, index=True)
        index_buf = bytes(w.out)
        index_hash = sha1(index_buf).digest()
        out += index_buf

        fw = Writer()
        if self.version >= 7:
            fw.u8(0)
        if self.version >= 4:
            fw.u1(0)
        fw.u4(MAGIC)
        fw.u4(self.version)
        fw.u8(index_offset)
        fw.u8(len(index_buf))
        fw.raw(index_hash)
        if self.version == 9:
            fw.u1(0)
        if self.version >= 8:
            slots = 4 if self.compression_u8 else 5
            for _ in range(slots):
                fw.raw(b'\x00' * 32)
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        Path(out_path).write_bytes(bytes(out) + bytes(fw.out))
        return len(new_entries)
