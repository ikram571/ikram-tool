// auto-generated fast pak cipher (game SM4 variant)
#include <stdint.h>
#include <stddef.h>

static const uint8_t SBOX[256] = { 52, 102, 37, 116, 137, 120, 228, 169, 90, 65, 188, 122, 214, 22, 33, 35, 77, 97, 218, 148, 155, 223, 19, 60, 105, 58, 49, 10, 95, 215, 153, 149, 241, 174, 114, 61, 7, 96, 36, 182, 152, 238, 196, 162, 45, 136, 221, 141, 4, 234, 187, 17, 202, 62, 93, 161, 246, 63, 176, 151, 128, 71, 43, 166, 230, 247, 217, 177, 89, 192, 124, 190, 84, 40, 183, 126, 79, 248, 67, 110, 160, 80, 14, 245, 144, 184, 251, 163, 123, 98, 25, 70, 3, 42, 185, 143, 159, 119, 180, 91, 131, 135, 8, 235, 226, 30, 66, 240, 15, 232, 113, 106, 117, 173, 85, 31, 181, 171, 51, 250, 127, 21, 189, 133, 216, 6, 104, 179, 82, 48, 72, 11, 0, 237, 239, 178, 87, 142, 231, 108, 213, 229, 46, 83, 130, 5, 249, 129, 244, 86, 191, 140, 75, 227, 219, 74, 145, 76, 44, 211, 64, 41, 78, 32, 20, 54, 121, 9, 111, 209, 55, 224, 57, 12, 138, 146, 56, 18, 53, 109, 225, 253, 147, 154, 23, 212, 201, 156, 107, 132, 38, 157, 175, 118, 193, 158, 208, 150, 197, 203, 233, 115, 73, 210, 205, 100, 195, 199, 1, 125, 243, 172, 252, 222, 164, 68, 50, 27, 194, 186, 28, 2, 198, 39, 69, 139, 242, 24, 167, 16, 81, 29, 200, 207, 99, 255, 47, 13, 88, 206, 101, 165, 220, 26, 59, 134, 254, 34, 92, 168, 94, 103, 170, 236, 112, 204 };
static const uint32_t FK[4] = { 0x46970e9c, 0x4bc0685e, 0x59056186, 0xbca2491e };
static const uint32_t CK[32] = { 0xeb92b, 0x3a0ae783, 0x9e3b5c67, 0xaddbdabf, 0x7b7484cb, 0x49156c63, 0xc79ab5e7, 0x79ec9cff, 0x1725beab, 0x2fb89ca3, 0x24808ad7, 0xddd28b1f, 0x4740da4b, 0xbbc3ea73, 0x247b30e7, 0x91be385f, 0x401248b, 0x45fcd3a3, 0x530b4ce7, 0xc68dd35f, 0xe3d16c2b, 0x4f698c13, 0x6b92c747, 0x769efb1f, 0x4c73be9b, 0xc942b193, 0xad80d827, 0x372fb33f, 0x13cb6aab, 0x2bdc0aa3, 0x17a4a247, 0xd5e96caf };

static inline uint32_t rotl(uint32_t x, int n){ return (x << n) | (x >> (32 - n)); }
static inline uint32_t load_be(const uint8_t* p){ return ((uint32_t)p[0]<<24)|((uint32_t)p[1]<<16)|((uint32_t)p[2]<<8)|(uint32_t)p[3]; }
static inline void store_be(uint8_t* p, uint32_t v){ p[0]=(uint8_t)(v>>24); p[1]=(uint8_t)(v>>16); p[2]=(uint8_t)(v>>8); p[3]=(uint8_t)v; }
static inline uint32_t sb(uint32_t x){ return ((uint32_t)SBOX[(x>>24)&0xff]<<24)|((uint32_t)SBOX[(x>>16)&0xff]<<16)|((uint32_t)SBOX[(x>>8)&0xff]<<8)|(uint32_t)SBOX[x&0xff]; }
static inline uint32_t t0(uint32_t x){ x = sb(x); return x ^ rotl(x,2) ^ rotl(x,10) ^ rotl(x,18) ^ rotl(x,24); }
static inline uint32_t t1(uint32_t x){ x = sb(x); return x ^ rotl(x,13) ^ rotl(x,23); }

static void expand(const uint8_t* key, uint32_t rk[32]){
    uint32_t k0 = load_be(key) ^ FK[0];
    uint32_t k1 = load_be(key+4) ^ FK[1];
    uint32_t k2 = load_be(key+8) ^ FK[2];
    uint32_t k3 = load_be(key+12) ^ FK[3];
    for (int i = 0; i < 32; i++){
        k0 ^= t1(k1 ^ k2 ^ k3 ^ CK[i]); rk[i] = k0;
        k1 ^= t1(k2 ^ k3 ^ k0 ^ CK[++i]); rk[i] = k1;
        k2 ^= t1(k3 ^ k0 ^ k1 ^ CK[++i]); rk[i] = k2;
        k3 ^= t1(k0 ^ k1 ^ k2 ^ CK[++i]); rk[i] = k3;
    }
}

static void crypt_block(const uint8_t* in, uint8_t* out, const uint32_t* rk){
    uint32_t x0 = load_be(in);
    uint32_t x1 = load_be(in+4);
    uint32_t x2 = load_be(in+8);
    uint32_t x3 = load_be(in+12);
    for (int i = 0; i < 32; i += 4){
        x0 ^= t0(x1 ^ x2 ^ x3 ^ rk[i]);
        x1 ^= t0(x2 ^ x3 ^ x0 ^ rk[i+1]);
        x2 ^= t0(x3 ^ x0 ^ x1 ^ rk[i+2]);
        x3 ^= t0(x0 ^ x1 ^ x2 ^ rk[i+3]);
    }
    store_be(out, x3); store_be(out+4, x2); store_be(out+8, x1); store_be(out+12, x0);
}

void sm4_ecb(const uint8_t* key, const uint8_t* in, uint8_t* out, size_t len, int encrypt){
    uint32_t rk[32];
    expand(key, rk);
    if (!encrypt){
        for (int i = 0; i < 16; i++){ uint32_t tmp = rk[i]; rk[i] = rk[31-i]; rk[31-i] = tmp; }
    }
    for (size_t off = 0; off < len; off += 16){
        crypt_block(in + off, out + off, rk);
    }
}