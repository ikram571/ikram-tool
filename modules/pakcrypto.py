import ctypes
import struct
import subprocess
import zlib
from hashlib import sha1
from pathlib import Path

ZUC_KEY = bytes.fromhex('01010101010101010101010101010101')
ZUC_IV = bytes.fromhex('FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF')

RSA_MOD_1 = bytes.fromhex('CBE8B9F2504050EF9831B719E9A6249A6D238505ADE909BDE78C180DED6072A0C3347B8AF4780E1F212D952D82D4BF7F233C1ECA499E1F9D9A85B4FAD759F54BABC1666C5DE411EA9E4B2374425DD6C6F54333BBC8F2610FE6063E4D0D6C21A671A8F7C3740555E5DC06D4E1691C456DB4116C0C012BF7B206E8311AAAEC689952BF804EF638F09D5822B4117B114208F14DEB459E80CB770E5B0D7978E21F5E6CED4999D3583108221A7AB28B960277ADB5690A332784019D9C195BE4EA9EA0A09459010F236465DE0D59C3EF7324E954E1118D93EE19F299760C2CDB963CE87973EA5ECC9BBE81C27D4C7C8572AC07E9BCEAC9BD72AB7A56A3C0AD736ABCE4')

SIMPLE1_KEY = 121
SIMPLE2_KEY = bytes.fromhex('E55B4ED1')
SIMPLE2_BLOCK = 16

SM4_SECRET_2 = 'Q0hVTKey$as*1ZFlQCiA'
SM4_SECRET_4 = 'eb691efea914241317a8'
SM4_SECRET_NEW = [
    'xG2qW5lP7lV2iN5fN5pG', 'xT1cJ6dL5wC0kK1rB4dK',
    'qC4jS5bZ6fL5xE6nD4zA', 'gD4jQ2aL3bS3lC3xT0iW',
    'xU1yQ8wE9zY3gZ3bT5aE', 'uQ3cO2dX7xY4xU7gH7iS',
    'gW1fR0jK6wQ4oN0oK1kZ', 'aJ4pV7iZ7pU4wP2aC2cZ',
    'cX6jT3cM2oT3vK0kJ1qN', 'iT2vS0cS6yT6cZ1sE1lO',
    'hM1pH9iY8wM9hT4lN5uJ', 'kG6bC8jK0fL0dE4sH4mL',
    'dB6lB3vE0eZ8wM8rI0aC', 'tP7sP7nI9rA2vQ4cV5yQ',
    'aT0cL1yN4pT3sZ7eM2vY', 'uV6fU8fC9zN3mP5dH8mN',
    'rT6aQ6oZ1yM0gO5tO1aN', 'jU5bH7lQ0fM9hK2kI0oF',
    'iQ0eM0mJ7uT0kV6kL5zY',
]

EM_SIMPLE1 = 1
EM_SIMPLE2 = 16
EM_SM4_2 = 2
EM_SM4_4 = 4
EM_SM4_NEW_BASE = 31
EM_SM4_NEW_MASK = ~EM_SM4_NEW_BASE
EM_UNKNOWN_17 = 17

CM_NONE = 0
CM_ZLIB = 1
CM_ZSTD = 6
CM_ZSTD_DICT = 8
CM_MASK = 15


def zuc_keystream(n=32):
    from gmalg.zuc import ZUC
    z = ZUC(ZUC_KEY, ZUC_IV)
    return [struct.unpack('>I', z.generate())[0] for _ in range(n)]


def _hashhash(data: bytes, n: int) -> bytes:
    result = b''
    while len(result) < n:
        result += sha1(data).digest()
    return result[:n]


def _safe_unpad(x: bytes) -> bytes:
    try:
        skip = 1 + next(i for i in range(len(x)) if x[i] != 0)
        return x[skip:]
    except StopIteration:
        return x.strip(b'\x00')


def rsa_extract(signature: bytes, modulus: bytes) -> bytes:
    c = int.from_bytes(signature, 'little')
    n = int.from_bytes(modulus, 'little')
    m = pow(c, 65537, n).to_bytes(256, 'little').rstrip(b'\x00')
    if len(m) < 43:
        return b''
    x1 = m[1:][:20]
    x2 = m[21:]
    x1 = bytes(a ^ b for a, b in zip(x1, _hashhash(x2, len(x1))))
    x2 = bytes(a ^ b for a, b in zip(x2, _hashhash(x1, len(x2))))
    part1, rest = x2[:20], x2[20:]
    if part1 != sha1(b'\x00' * 20).digest():
        return b''
    return _safe_unpad(rest)


def decrypt_index(ciphertext: bytes, pak_info) -> bytes:
    if pak_info.version > 7:
        key = rsa_extract(pak_info.packed_key, RSA_MOD_1)
        iv = rsa_extract(pak_info.packed_iv, RSA_MOD_1)
        if len(key) != 32 or len(iv) != 32:
            return ciphertext
        from Crypto.Cipher import AES
        aes = AES.new(key, AES.MODE_CBC, iv[:16])
        decrypted = aes.decrypt(ciphertext)
        try:
            from Crypto.Util.Padding import unpad
            return unpad(decrypted, 16)
        except Exception:
            last = decrypted[-1]
            if 1 <= last <= 16 and decrypted.endswith(bytes([last]) * last):
                return decrypted[:-last]
            return decrypted.rstrip(b'\x00')
    return bytes(b ^ SIMPLE1_KEY for b in ciphertext)


def is_simple1(m):
    return m == EM_SIMPLE1


def is_simple2(m):
    return m == EM_SIMPLE2 or m == EM_UNKNOWN_17


def is_sm4(m):
    return m == EM_SM4_2 or m == EM_SM4_4 or (m & EM_SM4_NEW_MASK) != 0


def align_encrypted_size(n, method):
    if is_simple2(method):
        return (n + SIMPLE2_BLOCK - 1) // SIMPLE2_BLOCK * SIMPLE2_BLOCK
    if is_sm4(method):
        return (n + 15) // 16 * 16
    return n


def derive_sm4_key(stem: str, method: int) -> bytes:
    if method == EM_SM4_2:
        secret = SM4_SECRET_2
    elif method == EM_SM4_4:
        secret = SM4_SECRET_4
    else:
        index = (method - EM_SM4_NEW_BASE) % len(SM4_SECRET_NEW)
        secret = f'{SM4_SECRET_NEW[index]}{method}'
    return sha1((stem.lower() + secret).encode()).digest()[:16]


class SM4Custom:
    """PUBG/BGMI pak block cipher (SM4-structure, game-specific tables)."""
    _S_BOX = bytes([
        52, 102, 37, 116, 137, 120, 228, 169, 90, 65, 188, 122, 214, 22, 33, 35,
        77, 97, 218, 148, 155, 223, 19, 60, 105, 58, 49, 10, 95, 215, 153, 149,
        241, 174, 114, 61, 7, 96, 36, 182, 152, 238, 196, 162, 45, 136, 221, 141,
        4, 234, 187, 17, 202, 62, 93, 161, 246, 63, 176, 151, 128, 71, 43, 166,
        230, 247, 217, 177, 89, 192, 124, 190, 84, 40, 183, 126, 79, 248, 67, 110,
        160, 80, 14, 245, 144, 184, 251, 163, 123, 98, 25, 70, 3, 42, 185, 143,
        159, 119, 180, 91, 131, 135, 8, 235, 226, 30, 66, 240, 15, 232, 113, 106,
        117, 173, 85, 31, 181, 171, 51, 250, 127, 21, 189, 133, 216, 6, 104, 179,
        82, 48, 72, 11, 0, 237, 239, 178, 87, 142, 231, 108, 213, 229, 46, 83,
        130, 5, 249, 129, 244, 86, 191, 140, 75, 227, 219, 74, 145, 76, 44, 211,
        64, 41, 78, 32, 20, 54, 121, 9, 111, 209, 55, 224, 57, 12, 138, 146,
        56, 18, 53, 109, 225, 253, 147, 154, 23, 212, 201, 156, 107, 132, 38, 157,
        175, 118, 193, 158, 208, 150, 197, 203, 233, 115, 73, 210, 205, 100, 195, 199,
        1, 125, 243, 172, 252, 222, 164, 68, 50, 27, 194, 186, 28, 2, 198, 39,
        69, 139, 242, 24, 167, 16, 81, 29, 200, 207, 99, 255, 47, 13, 88, 206,
        101, 165, 220, 26, 59, 134, 254, 34, 92, 168, 94, 103, 170, 236, 112, 204
    ])
    _FK = [1184304796, 1270900830, 1493524870, 3164752158]
    _CK = [964907, 973793155, 2654690407, 2916866751, 2071233739, 1226140771, 3348805095, 2045549823, 388349611, 800627875, 612403927, 3721562911, 1195432523, 3150178931, 612053223, 2445162591, 67183755, 1174197155, 1393249511, 3331183455, 3822152747, 1332317203, 1804781383, 1990130463, 1282653851, 3376591251, 2910902311, 925872959, 332098219, 735840931, 396665415, 3588844719]

    _T_TABLES = None

    @staticmethod
    def _rol32(x, n):
        return (x << n) & 0xFFFFFFFF | (x >> (32 - n))

    @classmethod
    def _make_t_tables(cls):
        S = cls._S_BOX
        rol = cls._rol32

        def L(y):
            return y ^ rol(y, 2) ^ rol(y, 10) ^ rol(y, 18) ^ rol(y, 24)

        T0 = [0] * 256; T1 = [0] * 256; T2 = [0] * 256; T3 = [0] * 256
        for i in range(256):
            s = S[i]
            T0[i] = L(s << 24)
            T1[i] = L(s << 16)
            T2[i] = L(s << 8)
            T3[i] = L(s)
        return (T0, T1, T2, T3)

    def __init__(self, key: bytes):
        if len(key) != 16:
            raise ValueError('Key must be 16 bytes')
        self._key = key
        if SM4Custom._T_TABLES is None:
            SM4Custom._T_TABLES = SM4Custom._make_t_tables()
        self._rkey = [0] * 32
        self._key_expand(key, self._rkey)

    @classmethod
    def _key_expand(cls, key: bytes, rkey: list):
        CK = cls._CK
        FK = cls._FK

        def t1(x):
            x = int.from_bytes(cls._S_BOX[(x >> 24) & 255:((x >> 24) & 255) + 1] +
                               cls._S_BOX[(x >> 16) & 255:((x >> 16) & 255) + 1] +
                               cls._S_BOX[(x >> 8) & 255:((x >> 8) & 255) + 1] +
                               cls._S_BOX[x & 255:(x & 255) + 1], 'big')
            return x ^ cls._rol32(x, 13) ^ cls._rol32(x, 23)

        k0 = int.from_bytes(key[0:4], 'big') ^ FK[0]
        k1 = int.from_bytes(key[4:8], 'big') ^ FK[1]
        k2 = int.from_bytes(key[8:12], 'big') ^ FK[2]
        k3 = int.from_bytes(key[12:16], 'big') ^ FK[3]
        for i in range(0, 32, 4):
            k0 ^= t1(k1 ^ k2 ^ k3 ^ CK[i]); rkey[i] = k0
            k1 ^= t1(k2 ^ k3 ^ k0 ^ CK[i + 1]); rkey[i + 1] = k1
            k2 ^= t1(k3 ^ k0 ^ k1 ^ CK[i + 2]); rkey[i + 2] = k2
            k3 ^= t1(k0 ^ k1 ^ k2 ^ CK[i + 3]); rkey[i + 3] = k3

    def _bulk(self, data: bytes, rk) -> bytes:
        n = len(data)
        out = bytearray(n)
        T0, T1, T2, T3 = self._T_TABLES
        unpack_from = struct.unpack_from
        pack_into = struct.pack_into
        idx = 0
        while idx < n:
            x0, x1, x2, x3 = unpack_from('>IIII', data, idx)
            for i in range(0, 32, 4):
                t = x1 ^ x2 ^ x3 ^ rk[i]
                x0 ^= T0[t >> 24] ^ T1[t >> 16 & 255] ^ T2[t >> 8 & 255] ^ T3[t & 255]
                t = x2 ^ x3 ^ x0 ^ rk[i + 1]
                x1 ^= T0[t >> 24] ^ T1[t >> 16 & 255] ^ T2[t >> 8 & 255] ^ T3[t & 255]
                t = x3 ^ x0 ^ x1 ^ rk[i + 2]
                x2 ^= T0[t >> 24] ^ T1[t >> 16 & 255] ^ T2[t >> 8 & 255] ^ T3[t & 255]
                t = x0 ^ x1 ^ x2 ^ rk[i + 3]
                x3 ^= T0[t >> 24] ^ T1[t >> 16 & 255] ^ T2[t >> 8 & 255] ^ T3[t & 255]
            pack_into('>IIII', out, idx, x3, x2, x1, x0)
            idx += 16
        return bytes(out)

    def encrypt_bulk(self, data: bytes) -> bytes:
        lib = _load_fast_sm4()
        if lib is not None:
            n = len(data)
            inbuf = ctypes.create_string_buffer(bytes(data), n)
            outbuf = ctypes.create_string_buffer(n)
            lib.sm4_ecb(ctypes.create_string_buffer(self._key), inbuf, outbuf, n, 1)
            return outbuf.raw
        return self._bulk(data, self._rkey)

    def decrypt_bulk(self, data: bytes) -> bytes:
        lib = _load_fast_sm4()
        if lib is not None:
            n = len(data)
            inbuf = ctypes.create_string_buffer(bytes(data), n)
            outbuf = ctypes.create_string_buffer(n)
            lib.sm4_ecb(ctypes.create_string_buffer(self._key), inbuf, outbuf, n, 0)
            return outbuf.raw
        return self._bulk(data, self._rkey[::-1])


_FAST_SM4_LIB = None
_FAST_SM4_TRIED = False


def _sm4_c_source() -> str:
    sbox = SM4Custom._S_BOX
    fk = SM4Custom._FK
    ck = SM4Custom._CK
    L = []
    L.append('// auto-generated fast pak cipher (game SM4 variant)')
    L.append('#include <stdint.h>')
    L.append('#include <stddef.h>')
    L.append('')
    L.append('static const uint8_t SBOX[256] = { ' + ', '.join(str(x) for x in sbox) + ' };')
    L.append('static const uint32_t FK[4] = { ' + ', '.join(hex(x) for x in fk) + ' };')
    L.append('static const uint32_t CK[32] = { ' + ', '.join(hex(x) for x in ck) + ' };')
    L.append('')
    L.append('static inline uint32_t rotl(uint32_t x, int n){ return (x << n) | (x >> (32 - n)); }')
    L.append('static inline uint32_t load_be(const uint8_t* p){ return ((uint32_t)p[0]<<24)|((uint32_t)p[1]<<16)|((uint32_t)p[2]<<8)|(uint32_t)p[3]; }')
    L.append('static inline void store_be(uint8_t* p, uint32_t v){ p[0]=(uint8_t)(v>>24); p[1]=(uint8_t)(v>>16); p[2]=(uint8_t)(v>>8); p[3]=(uint8_t)v; }')
    L.append('static inline uint32_t sb(uint32_t x){ return ((uint32_t)SBOX[(x>>24)&0xff]<<24)|((uint32_t)SBOX[(x>>16)&0xff]<<16)|((uint32_t)SBOX[(x>>8)&0xff]<<8)|(uint32_t)SBOX[x&0xff]; }')
    L.append('static inline uint32_t t0(uint32_t x){ x = sb(x); return x ^ rotl(x,2) ^ rotl(x,10) ^ rotl(x,18) ^ rotl(x,24); }')
    L.append('static inline uint32_t t1(uint32_t x){ x = sb(x); return x ^ rotl(x,13) ^ rotl(x,23); }')
    L.append('')
    L.append('static void expand(const uint8_t* key, uint32_t rk[32]){')
    L.append('    uint32_t k0 = load_be(key) ^ FK[0];')
    L.append('    uint32_t k1 = load_be(key+4) ^ FK[1];')
    L.append('    uint32_t k2 = load_be(key+8) ^ FK[2];')
    L.append('    uint32_t k3 = load_be(key+12) ^ FK[3];')
    L.append('    for (int i = 0; i < 32; i++){')
    L.append('        k0 ^= t1(k1 ^ k2 ^ k3 ^ CK[i]); rk[i] = k0;')
    L.append('        k1 ^= t1(k2 ^ k3 ^ k0 ^ CK[++i]); rk[i] = k1;')
    L.append('        k2 ^= t1(k3 ^ k0 ^ k1 ^ CK[++i]); rk[i] = k2;')
    L.append('        k3 ^= t1(k0 ^ k1 ^ k2 ^ CK[++i]); rk[i] = k3;')
    L.append('    }')
    L.append('}')
    L.append('')
    L.append('static void crypt_block(const uint8_t* in, uint8_t* out, const uint32_t* rk){')
    L.append('    uint32_t x0 = load_be(in);')
    L.append('    uint32_t x1 = load_be(in+4);')
    L.append('    uint32_t x2 = load_be(in+8);')
    L.append('    uint32_t x3 = load_be(in+12);')
    L.append('    for (int i = 0; i < 32; i += 4){')
    L.append('        x0 ^= t0(x1 ^ x2 ^ x3 ^ rk[i]);')
    L.append('        x1 ^= t0(x2 ^ x3 ^ x0 ^ rk[i+1]);')
    L.append('        x2 ^= t0(x3 ^ x0 ^ x1 ^ rk[i+2]);')
    L.append('        x3 ^= t0(x0 ^ x1 ^ x2 ^ rk[i+3]);')
    L.append('    }')
    L.append('    store_be(out, x3); store_be(out+4, x2); store_be(out+8, x1); store_be(out+12, x0);')
    L.append('}')
    L.append('')
    L.append('void sm4_ecb(const uint8_t* key, const uint8_t* in, uint8_t* out, size_t len, int encrypt){')
    L.append('    uint32_t rk[32];')
    L.append('    expand(key, rk);')
    L.append('    if (!encrypt){')
    L.append('        for (int i = 0; i < 16; i++){ uint32_t tmp = rk[i]; rk[i] = rk[31-i]; rk[31-i] = tmp; }')
    L.append('    }')
    L.append('    for (size_t off = 0; off < len; off += 16){')
    L.append('        crypt_block(in + off, out + off, rk);')
    L.append('    }')
    L.append('}')
    return '\n'.join(L)


def _load_fast_sm4():
    """Load (or build) the C accelerator. Returns ctypes lib or None."""
    global _FAST_SM4_LIB, _FAST_SM4_TRIED
    if _FAST_SM4_TRIED:
        return _FAST_SM4_LIB
    _FAST_SM4_TRIED = True
    try:
        import ctypes
        src_path = Path(__file__).resolve().parent / 'sm4_fast.c'
        so_path = Path(__file__).resolve().parent / 'sm4_fast.so'
        c_src = _sm4_c_source()
        try:
            if not src_path.exists() or src_path.read_text() != c_src:
                src_path.write_text(c_src)
            recompile = (not so_path.exists()) or (so_path.stat().st_mtime < src_path.stat().st_mtime)
        except OSError:
            cache = Path.home() / '.ikram_tool'
            cache.mkdir(parents=True, exist_ok=True)
            src_path = cache / 'sm4_fast.c'
            so_path = cache / 'sm4_fast.so'
            if not src_path.exists() or src_path.read_text() != c_src:
                src_path.write_text(c_src)
            recompile = (not so_path.exists()) or (so_path.stat().st_mtime < src_path.stat().st_mtime)
        if recompile:
            for cc in ('gcc', 'cc', 'clang'):
                try:
                    r = subprocess.run([cc, '-O2', '-shared', '-fPIC', str(src_path), '-o', str(so_path)],
                                       capture_output=True, timeout=120)
                    if r.returncode == 0 and so_path.exists():
                        break
                except Exception:
                    continue
        if not so_path.exists():
            return None
        lib = ctypes.CDLL(str(so_path))
        lib.sm4_ecb.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p, ctypes.c_size_t, ctypes.c_int]
        lib.sm4_ecb.restype = None
        _FAST_SM4_LIB = lib
        return lib
    except Exception:
        return None


_SM4_CTX_CACHE = {}


def _sm4_ctx(key: bytes) -> SM4Custom:
    ctx = _SM4_CTX_CACHE.get(key)
    if ctx is None:
        ctx = SM4Custom(key)
        if len(_SM4_CTX_CACHE) > 64:
            _SM4_CTX_CACHE.clear()
        _SM4_CTX_CACHE[key] = ctx
    return ctx


def sm4_decrypt_block(data: bytes, key: bytes) -> bytes:
    return _sm4_ctx(key).decrypt_bulk(data)


def sm4_encrypt_block(data: bytes, key: bytes) -> bytes:
    return _sm4_ctx(key).encrypt_bulk(data)


def decrypt_block(ciphertext: bytes, stem: str, method: int) -> bytes:
    if is_simple1(method):
        return bytes(b ^ SIMPLE1_KEY for b in ciphertext)
    if is_simple2(method):
        rolling = struct.unpack('<I', SIMPLE2_KEY)[0]
        out = bytearray()
        for x in struct.unpack(f'<{len(ciphertext) // 4}I', ciphertext):
            rolling ^= x
            out += struct.pack('<I', rolling)
        return bytes(out)
    if is_sm4(method):
        return sm4_decrypt_block(ciphertext, derive_sm4_key(stem, method))
    raise ValueError(f'Unknown encryption method: {method}')


def encrypt_block(plaintext: bytes, stem: str, method: int) -> bytes:
    if is_simple1(method):
        return bytes(b ^ SIMPLE1_KEY for b in plaintext)
    if is_simple2(method):
        pad = (-len(plaintext)) % SIMPLE2_BLOCK or SIMPLE2_BLOCK
        plaintext = plaintext + b'\x00' * pad
        rolling = struct.unpack('<I', SIMPLE2_KEY)[0]
        out = bytearray()
        for x in struct.unpack(f'<{len(plaintext) // 4}I', plaintext):
            c = rolling ^ x
            out += struct.pack('<I', c)
            rolling ^= c
        return bytes(out)
    if is_sm4(method):
        pad = (-len(plaintext)) % 16 or 16
        plaintext = plaintext + b'\x00' * pad
        return sm4_encrypt_block(plaintext, derive_sm4_key(stem, method))
    raise ValueError(f'Unknown encryption method: {method}')


def best_compress(chunk: bytes, cm: int, zstd_dict=None, fast=False) -> bytes:
    if cm == CM_ZLIB:
        return zlib.compress(chunk, 1 if fast else 9)
    if cm in (CM_ZSTD, CM_ZSTD_DICT):
        import zstandard
        zd = zstd_dict if cm == CM_ZSTD_DICT else None
        levels = (6, 3, 1) if fast else (22, 19, 16, 13, 10, 7, 4, 1)
        for lvl in levels:
            try:
                return zstandard.ZstdCompressor(level=lvl, dict_data=zd).compress(chunk)
            except Exception:
                continue
    return chunk


def decompress_block(block: bytes, zstd_dict, cm: int) -> bytes:
    if cm == CM_NONE:
        return bytes(block)
    if cm == CM_ZLIB:
        try:
            return zlib.decompress(block)
        except Exception:
            return bytes(block)
    if cm in (CM_ZSTD, CM_ZSTD_DICT):
        import zstandard
        for d in (zstd_dict if cm == CM_ZSTD_DICT else None, None):
            try:
                return zstandard.ZstdDecompressor(dict_data=d).decompress(block)
            except Exception:
                continue
        try:
            return zlib.decompress(block)
        except Exception:
            return bytes(block)
    return bytes(block)
