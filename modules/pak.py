import mmap
import os
import shutil
import struct
from hashlib import sha1
from pathlib import Path, PurePath

from . import pakcrypto as pc
from .pakcrypto import CM_NONE


class Reader:
    def __init__(self, buffer, cursor=0):
        self._buffer = buffer
        self._cursor = cursor

    def u1(self):
        v = struct.unpack_from('<B', self._buffer, self._cursor)[0]
        self._cursor += 1
        return v

    def u4(self):
        v = struct.unpack_from('<I', self._buffer, self._cursor)[0]
        self._cursor += 4
        return v

    def u8(self):
        v = struct.unpack_from('<Q', self._buffer, self._cursor)[0]
        self._cursor += 8
        return v

    def i4(self):
        v = struct.unpack_from('<i', self._buffer, self._cursor)[0]
        self._cursor += 4
        return v

    def s(self, n):
        v = struct.unpack_from(f'{n}s', self._buffer, self._cursor)[0]
        self._cursor += n
        return v

    def string(self):
        length = self.i4()
        if length <= 0:
            return ''
        return self.s(length).rstrip(b'\x00').decode('utf-8')


class TencentPakInfo:
    def __init__(self, buffer, keystream):
        self._keystream = keystream
        tail = buffer[-45:]
        r = Reader(tail)
        self.index_encrypted = (r.u1() ^ (keystream[3] & 0xFF)) == 1
        self.magic = r.u4() ^ keystream[2]
        self.version = r.u4()
        h_key = struct.pack('<5I', *keystream[4:9])
        self.index_hash = bytes(a ^ b for a, b in zip(r.s(20), h_key))
        self.index_size = r.u8() ^ (keystream[10] << 32 | keystream[11])
        self.index_offset = r.u8() ^ (keystream[0] << 32 | keystream[1])
        if self.version <= 3:
            self.index_encrypted = False
        self.unk1 = bytes()
        self.packed_key = bytes()
        self.packed_iv = bytes()
        self.packed_index_hash = bytes()
        self.stem_hash = 0
        self.unk2 = 0
        self.content_org_hash = bytes()
        r = Reader(buffer[-self._mem_size(self.version):])
        if self.version >= 7:
            key = struct.pack('<8I', *keystream[7:15])
            self.unk1 = bytes(a ^ b for a, b in zip(r.s(32), key))
        if self.version >= 8:
            self.packed_key = r.s(256)
            self.packed_iv = r.s(256)
            self.packed_index_hash = r.s(256)
            self.stem_hash = r.u4() ^ keystream[8]
        if self.version >= 9:
            self.unk2 = r.u4() ^ keystream[9]
        if self.version >= 12:
            self.content_org_hash = r.s(20)

    @staticmethod
    def _mem_size(version):
        size = 45
        if version >= 7:
            size += 32
        if version >= 8:
            size += 768
        if version >= 9:
            size += 8
        if version >= 12:
            size += 20
        return size

    def footer_size(self):
        return self._mem_size(self.version)


class PakCompressedBlock:
    def __init__(self, start=0, end=0):
        self.start = start
        self.end = end


class TencentPakEntry:
    def __init__(self, reader: Reader, version: int):
        self.content_hash = reader.s(20)
        if version <= 1:
            reader.u8()
        self.offset = reader.u8()
        self.uncompressed_size = reader.u8()
        self.compression_method = reader.u4() & 15
        self.size = reader.u8()
        self.unk1 = reader.u1() if version >= 5 else 0
        self.unk2 = reader.s(20) if version >= 5 else bytes()
        if self.compression_method != CM_NONE and version >= 3:
            self.compressed_blocks = [PakCompressedBlock(reader.u8(), reader.u8()) for _ in range(reader.u4())]
        else:
            self.compressed_blocks = []
        self.compression_block_size = reader.u4() if version >= 4 else 0
        self.encrypted = reader.u1() == 1 if version >= 4 else False
        self.encryption_method = reader.u4() if version >= 12 else 0
        self.index_new_sep = reader.u4() if version >= 12 else 0
        self.stem = ''

    def clone(self):
        ne = TencentPakEntry.__new__(TencentPakEntry)
        ne.content_hash = self.content_hash
        ne.offset = self.offset
        ne.uncompressed_size = self.uncompressed_size
        ne.compression_method = self.compression_method
        ne.size = self.size
        ne.unk1 = self.unk1
        ne.unk2 = self.unk2
        ne.compressed_blocks = [PakCompressedBlock(b.start, b.end) for b in self.compressed_blocks]
        ne.compression_block_size = self.compression_block_size
        ne.encrypted = self.encrypted
        ne.encryption_method = self.encryption_method
        ne.index_new_sep = self.index_new_sep
        ne.stem = self.stem
        return ne


def parse_index_data(data: bytes, version: int):
    r = Reader(data)
    mount_point = r.string()
    num_files = r.u4()
    files = [TencentPakEntry(r, version) for _ in range(num_files)]
    dirs = {}
    for _ in range(r.u8()):
        dp = r.string()
        cnt = r.u8()
        dirs[dp] = {r.string(): files[~r.i4()] for _ in range(cnt)}
    for dp, items in dirs.items():
        for name, entry in items.items():
            entry.stem = PurePath(name).stem
    return mount_point, files, dirs


def pw_string(s: str) -> bytes:
    if not s:
        return struct.pack('<i', 0)
    b = s.encode('utf-8') + b'\x00'
    return struct.pack('<i', len(b)) + b


def pw_entry(e: TencentPakEntry, v: int) -> bytes:
    w = bytearray(e.content_hash)
    w += struct.pack('<Q', e.offset)
    w += struct.pack('<Q', e.uncompressed_size)
    w += struct.pack('<I', e.compression_method)
    w += struct.pack('<Q', e.size)
    if v >= 5:
        w += bytes([e.unk1])
        w += e.unk2
    if e.compression_method != CM_NONE and v >= 3:
        w += struct.pack('<I', len(e.compressed_blocks))
        for b in e.compressed_blocks:
            w += struct.pack('<QQ', b.start, b.end)
    if v >= 4:
        w += struct.pack('<I', e.compression_block_size)
        w += bytes([1 if e.encrypted else 0])
    if v >= 12:
        w += struct.pack('<II', e.encryption_method, e.index_new_sep)
    return bytes(w)


class PakReader:
    def __init__(self, file_path):
        self.file_path = Path(file_path)
        self._keystream = pc.zuc_keystream()
        with open(self.file_path, 'rb') as f:
            try:
                self._mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
                self.content = memoryview(self._mm)
            except Exception:
                self._mm = None
                self.content = memoryview(f.read())
        self.info = TencentPakInfo(self.content, self._keystream)
        self.fsize = os.path.getsize(self.file_path)
        self.mount_point, self.files, self.dirs = self._load_index()
        self._zstd_dict = None
        self._load_zstd_dict()

    def _load_index(self):
        raw = bytes(self.content[self.info.index_offset:][:self.info.index_size])
        if self.info.index_encrypted:
            raw = pc.decrypt_index(raw, self.info)
        return parse_index_data(raw, self.info.version)

    def _load_zstd_dict(self):
        for dp, files in self.dirs.items():
            if Path(dp).name == 'zstddic' and len(files) == 1:
                entry = next(iter(files.values()))
                data = self.read_entry(entry)
                r = Reader(data)
                dict_size = r.u8()
                r.u4()
                if dict_size == r.u4():
                    import zstandard
                    self._zstd_dict = zstandard.ZstdCompressionDict(r.s(dict_size))
                return

    def read_entry(self, entry: TencentPakEntry) -> bytes:
        method = entry.encryption_method
        enc = entry.encrypted
        if entry.compression_method == CM_NONE:
            total = pc.align_encrypted_size(entry.size, method) if enc else entry.size
            if entry.offset + total > self.fsize:
                return b''
            data = bytes(self.content[entry.offset:][:total])
            if enc:
                data = pc.decrypt_block(data, entry.stem, method)
            return data[:entry.size]
        if not entry.compressed_blocks:
            total = pc.align_encrypted_size(entry.size, method) if enc else entry.size
            if entry.offset + total > self.fsize:
                return b''
            data = bytes(self.content[entry.offset:][:total])
            if enc:
                data = pc.decrypt_block(data, entry.stem, method)
            return pc.decompress_block(data, self._zstd_dict, entry.compression_method)
        block_size = entry.compression_block_size if entry.compression_block_size > 0 else 65536
        out = bytearray(entry.uncompressed_size)
        nblocks = len(entry.compressed_blocks)
        order = self._block_order(nblocks, method) if enc else range(nblocks)
        for k, pos in enumerate(order):
            if not isinstance(pos, int) or pos < 0 or pos >= nblocks:
                continue
            block = entry.compressed_blocks[pos]
            if block.start >= self.fsize or block.end > self.fsize:
                continue
            total = pc.align_encrypted_size(block.end - block.start, method) if enc else block.end - block.start
            raw = bytes(self.content[block.start:][:total])
            if enc:
                raw = pc.decrypt_block(raw, entry.stem, method)
            data = pc.decompress_block(raw, self._zstd_dict, entry.compression_method)
            out[k * block_size:k * block_size + len(data)] = data
        return bytes(out)

    def _block_order(self, n, method):
        if not pc.is_sm4(method):
            return list(range(n))
        mask32 = 0xFFFFFFFF

        def wrap(x):
            x &= mask32
            return x if x < 0x80000000 else x - 0x100000000

        state = n
        permutation = []
        while len(permutation) != n:
            x1 = wrap(1103515245 * state)
            state = wrap(x1 + 12345)
            x2 = wrap(x1 + 77880) if state < 0 else state
            x = ((x2 >> 16) & mask32) % 32767
            v = x % n
            if v not in permutation:
                permutation.append(v)
        inverse = [0] * n
        for i, v in enumerate(permutation):
            inverse[v] = i
        return inverse

    def full_paths(self):
        result = {}
        for dp, files in self.dirs.items():
            for name, entry in files.items():
                fp = str(PurePath(dp) / name).replace('\\', '/')
                result[fp] = entry
        return result

    def close(self):
        self.content = None
        if self._mm is not None:
            self._mm.close()
            self._mm = None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


class PakWriter:
    def __init__(self, pak: PakReader):
        self.pak = pak
        self.info = pak.info
        self.keystream = pak._keystream

    def inject_files(self, edits, output_path, force_add=False, target_path=None):
        pak = self.pak
        version = self.info.version
        original_footer = bytes(pak.content[-self.info.footer_size():])
        all_dirs = {dp: dict(f) for dp, f in pak.dirs.items()}
        all_files = list(pak.files)
        existing = pak.full_paths()

        edited_entries = {}
        for fp, (data, template, stem) in edits:
            fp = fp.replace('\\', '/')
            entry = existing.get(fp)
            if entry is not None:
                ne = entry.clone()
                cm = template.compression_method if template else entry.compression_method
                em = template.encryption_method if template else entry.encryption_method
                enc = template.encrypted if template else entry.encrypted
                ne.content_hash = sha1(data).digest()
                ne.uncompressed_size = len(data)
                ne.compression_method = cm
                ne.encryption_method = em
                ne.encrypted = enc
                ne.unk1 = template.unk1 if template else entry.unk1
                ne.index_new_sep = template.index_new_sep if template else entry.index_new_sep
                ne.unk2 = sha1((pak.mount_point + fp).lower().encode('utf-8')).digest()
                ne.stem = stem or entry.stem
                edited_entries[fp] = (ne, data)
                all_files[all_files.index(entry)] = ne
            elif force_add:
                template = None
                for name, e in existing.items():
                    if Path(name).suffix.lower() == Path(fp).suffix.lower():
                        template = e
                        break
                if template is None and existing:
                    template = next(iter(existing.values()))
                if template is None:
                    continue
                ne = template.clone()
                ne.content_hash = sha1(data).digest()
                ne.uncompressed_size = len(data)
                ne.compression_method = template.compression_method
                ne.encryption_method = template.encryption_method
                ne.encrypted = template.encrypted
                ne.unk1 = template.unk1
                ne.index_new_sep = template.index_new_sep
                ne.unk2 = sha1((pak.mount_point + fp).lower().encode('utf-8')).digest()
                ne.stem = stem or PurePath(fp).stem
                edited_entries[fp] = (ne, data)
                all_files.append(ne)
                dp = str(PurePath(fp).parent)
                if dp == '.':
                    dp = ''
                if dp and not dp.endswith('/'):
                    dp += '/'
                all_dirs.setdefault(dp, {})
                all_dirs[dp][PurePath(fp).name] = ne

        tmp = Path(str(output_path) + '.tmp')
        try:
            with open(tmp, 'wb') as out_fh:
                current_offset = 0
                for dp, dir_files in all_dirs.items():
                    for name, entry in dir_files.items():
                        fp = str(PurePath(dp) / name).replace('\\', '/')
                        if fp in edited_entries:
                            ne, data = edited_entries[fp]
                            cipher = self._encode(data, ne, current_offset)
                            ne.offset = ne.compressed_blocks[0].start if ne.compressed_blocks else current_offset
                            if ne.compression_method == CM_NONE:
                                ne.size = len(data)
                            else:
                                ne.size = sum(b.end - b.start for b in ne.compressed_blocks)
                            out_fh.write(cipher)
                            current_offset += len(cipher)
                        else:
                            orig = existing.get(fp)
                            if orig is None:
                                continue
                            src_off = orig.offset
                            read_sz = orig.size
                            if orig.encrypted:
                                read_sz = pc.align_encrypted_size(read_sz, orig.encryption_method)
                            if orig.compression_method != CM_NONE and orig.compressed_blocks:
                                read_sz = sum(
                                    pc.align_encrypted_size(b.end - b.start, orig.encryption_method) if orig.encrypted else b.end - b.start
                                    for b in orig.compressed_blocks)
                            entry.offset = current_offset
                            if entry.compressed_blocks:
                                delta = current_offset - src_off
                                for b in entry.compressed_blocks:
                                    b.start += delta
                                    b.end += delta
                            self._copy_stream(out_fh, src_off, read_sz)
                            current_offset += read_sz

                # dir index me edited files ke NAYE entries ho (purane nahi)
                for dp, dir_files in all_dirs.items():
                    for name, e in list(dir_files.items()):
                        fp2 = str(PurePath(dp) / name).replace('\\', '/')
                        if fp2 in edited_entries:
                            dir_files[name] = edited_entries[fp2][0]

                idx = bytearray(pw_string(pak.mount_point))
                idx += struct.pack('<I', len(all_files))
                for e in all_files:
                    idx += pw_entry(e, version)
                idx += struct.pack('<Q', len(all_dirs))
                for dp, dir_files in all_dirs.items():
                    idx += pw_string(dp)
                    idx += struct.pack('<Q', len(dir_files))
                    for name, e in dir_files.items():
                        idx += pw_string(name)
                        try:
                            idx += struct.pack('<i', ~all_files.index(e))
                        except ValueError:
                            idx += struct.pack('<i', -1)

                index_plain = bytes(idx)
                new_sha1 = sha1(index_plain).digest()
                if self.info.index_encrypted:
                    from Crypto.Cipher import AES
                    key = pc.rsa_extract(self.info.packed_key, pc.RSA_MOD_1)
                    iv = pc.rsa_extract(self.info.packed_iv, pc.RSA_MOD_1)
                    aes = AES.new(key, AES.MODE_CBC, iv[:16])
                    pad = (-len(index_plain)) % 16 or 16
                    index_bytes = aes.encrypt(index_plain + bytes([pad] * pad))
                else:
                    index_bytes = index_plain

                orig_size = os.path.getsize(pak.file_path)
                footer_sz = self.info.footer_size()
                total = current_offset + len(index_bytes) + footer_sz
                if total < orig_size:
                    out_fh.write(b'\x00' * (orig_size - total))
                    current_offset += orig_size - total

                new_idx_offset = current_offset
                new_idx_size = len(index_bytes)
                out_fh.write(index_bytes)

                new_footer = bytearray(original_footer)
                h_key = struct.pack('<5I', *self.keystream[4:9])
                new_footer[-36:-16] = bytes(a ^ b for a, b in zip(new_sha1, h_key))
                new_footer[-16:-8] = (new_idx_size ^ (self.keystream[10] << 32 | self.keystream[11])).to_bytes(8, 'little')
                new_footer[-8:] = (new_idx_offset ^ (self.keystream[0] << 32 | self.keystream[1])).to_bytes(8, 'little')
                out_fh.write(new_footer)
        finally:
            pak.close()

        if os.path.exists(output_path):
            os.remove(output_path)
        shutil.move(str(tmp), str(output_path))
        return len(edited_entries)

    def _encode(self, data, entry, current_offset):
        if entry.compression_method == CM_NONE:
            if entry.encrypted:
                return pc.encrypt_block(data, entry.stem, entry.encryption_method)
            return data
        cs = entry.compression_block_size if entry.compression_block_size > 0 else 65536
        blocks = []
        out = bytearray()
        offset = current_offset
        for i in range(0, len(data), cs):
            chunk = data[i:i + cs]
            comp = pc.best_compress(chunk, entry.compression_method, self.pak._zstd_dict)
            if entry.encrypted:
                comp = pc.encrypt_block(comp, entry.stem, entry.encryption_method)
            blocks.append(PakCompressedBlock(offset, offset + len(comp)))
            out += comp
            offset += len(comp)
        entry.compressed_blocks = blocks
        return bytes(out)

    def _copy_stream(self, out_fh, offset, length):
        with open(self.pak.file_path, 'rb') as src:
            src.seek(offset)
            remaining = length
            while remaining > 0:
                data = src.read(min(16 * 1024 * 1024, remaining))
                if not data:
                    break
                out_fh.write(data)
                remaining -= len(data)


def _safe_mount_point(mp: str) -> str:
    parts = [p for p in PurePath(mp).parts if p not in ('..', '')]
    return str(PurePath(*parts)) if parts else ''


def unpack_pak(pak_path, out_dir, log=None):
    with PakReader(pak_path) as pak:
        total = 0
        base = Path(out_dir) / _safe_mount_point(pak.mount_point)
        base.mkdir(parents=True, exist_ok=True)
        for dp, files in pak.dirs.items():
            for name, entry in files.items():
                rel = Path(*[p for p in PurePath(dp).parts if p not in ('..', '')])
                target = base / rel / name
                target.parent.mkdir(parents=True, exist_ok=True)
                data = pak.read_entry(entry)
                target.write_bytes(data)
                total += 1
                if log:
                    log(f'  {str(PurePath(dp) / name).replace("\\\\", "/")}  ({len(data)} bytes)')
        return total
