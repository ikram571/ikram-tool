# Phase 4 — Security / Secrets / Licensing / Telemetry Audit

Scope: what secrets exist, what the license gate actually enforces, what
leaves the device, and which hardcoded constants are format-required.

## S-001 — Telegram telemetry (shipped, compiled, owner-only)

Source: telemetry.pyc (no plaintext twin). Disassembly (analysis/pyc_dump/telemetry/).

Triggers:
  - send_login(): fires once on every successful key activation, immediately
    after the compiled UI prints "Key valid. Tool unlocked!" (ikram.py line
    ~1758 L13: `telemetry.send_login()`).
  - send_error(): fired on raised exceptions from the compiled core (menu
    flows / report_error) and, via univ.py / _notify_failure(), on graceful
    (non-raising) compile/decompile failures — the overlay hooks that the
    compiled UI never reported.

Payload (verified):
  - Device: `getprop ro.product.model` (device_name()) — model string only.
  - Time: local timestamp, `%Y-%m-%d %H:%M:%S`.
  - Version: VERSION file content.
  - Error path: operation label + truncated message (<=800 chars from
    overlay; compiled path truncates to Telegram's 4096 limit).
  - NO user files, NO keys, NO IP/geo, NO token/path contents.

Endpoint/channel:
  - BOT_TOKEN = "8704316836:AAHWrtG6pDeI4j6tRy02ryEPESDhp5iEYY0" (hardcoded)
  - CHAT_ID   = "5625387502"
  - POST json to https://api.telegram.org/bot<token>/sendMessage
  - threaded, failure-swallowed.

Assessment:
  - It is the OWNER's own callback channel ("login hone par device naam +
    time Telegram par bhejta hai taake owner ko pata chale ki kaun is tool
    ko use kar raha hai"). Designed behaviour, not hidden exfil.
  - Risk: hardcoded token in a public tool = anyone can spam the owner's bot.
    sendMessage-only blast radius; no admin rights are reachable via it.
  - Decision: KEEP AS-IS (behavior preservation mandate). The token cannot be
    changed without recompiling telemetry.pyc, which is out of scope. Document
    only. Overlay layer (univ.py) already matches the same channel.

## S-002 — License model: offline hash gate (NOT a real DRM)

Source: key.pyc (analysis/pyc_dump/key/). Verified constants:

  - _hash(s)      = sha256( s.strip().upper().encode() ).hexdigest()   # unsalted
  - FREETOOL gate = sha256("FREETOOL") = 7360b6c497b3f043eb4d74ae1100f8681b6a968719135cd6de7b58f3363d5c36
  - current_version() reads TOOL_DIR/VERSION file (content "V111", stripped)
  - make_key(KEY)  -> ikram_key.json {version, key_hash}; preserves owner_hash
  - _activate(KEY) -> TOOL_DIR/.ikram_tool/activated.json
                      {version: current_version(), key_hash: _hash(KEY)}
  - is_activated():
       1. activated.json exists?
       2. activated['version'] != current_version()  -> False   (VERSION-tie)
       3. activated['key_hash'] != ikram_key.json['key_hash'] -> False
       4. True

  owner_hash is never read by the gate — owner-side marker only.

Discrepancy #1 resolution (from Phase 1): bundled ikram_key.json carries
version "V110" while VERSION says "V111". TWO gates read it: entry-point
key.check() compares ikram_key.json['version'] to current_version() and
rejects on mismatch (REAL bug — fresh V111 install said "Invalid key");
is_activated() (post-activation note) never reads it. FIXED in F-003: bundled
version restamped V110->V111, key_hash untouched (same free key). Verified:
tree boot "✔ Key valid. Tool unlocked!" + menu + exit 0.

## S-003 — Hardcoded crypto material (format-required, keep)

  - pakcrypto.pyc: base64 string ("Q0hVTKey$as*1ZFlQCiA") used in the Tencent
    CHUNK derive path. Required on-disk constant of the TenCRYPT pak layout;
    shipped by every BGMI tool. Not author-generated entropy.
  - engines.py DEFAULT_UE4_KEYS[0] = "8A75AFDF...A0" — the well-known public
    PUBG/BGMI global UE4 AES key. Public knowledge, needed for standard-UE4
    paks. Overlay stores it outside the compiled module + persists working
    keys in ~/.config/ikramtool/pak_keys.json (never wiped by clean-replace).
  - ikram_sm4_fast.so = "CHEN custom SM4" chip variant (custom SBOX/FK/CK).
    sm4_custom.pyc embeds the C source and regenerates the .so at runtime —
    self-repair verified (Phase 2). The chip constants are the transport
    cipher of the pak format, not a licensing secret.

## S-004 — Network surface (all owner-authorized, all documented)

  - update.py: api.github.com/repos/ikram571/ikram-tool/releases/latest
    (User-Agent ikram-tool) + downloads the release zip from
    github.com/ikram571/ikram-tool/releases/latest/download/IkramTool.zip.
  - univ.py/telemetry.pyc: the S-001 Telegram channel.
  - No other sockets, no install-time callbacks, no phone-home caches.

## Decisions for the rebuild (P4)

  1. Keep telemetry as-is (owner design); document only. No recompile.
  2. Keep license gate as-is; V110 stamp F-003 = cosmetic, do not modify the
     shipped ikram_key.json.
  3. Keep all cryptographic constants (S-003) — they are format materials.
  4. update.py endpoint verified reachable (Phase 0: 302 -> V111 zip).