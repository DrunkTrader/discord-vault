# 02. Cryptography Fundamentals (as used in DiscordVault)

Only primitives that appear in the source are treated as "used". Concepts from your checklist that are absent are listed at the end so you know what is not here.

Related: key inventory in [03](03-key-hierarchy.md), byte-level flow in [04](04-encryption-decryption-flow.md).

## Vocabulary first

| Term | Plain meaning |
| --- | --- |
| Plaintext / ciphertext | Readable data / scrambled data |
| Key | A secret number that controls a cipher |
| Symmetric | The same key locks and unlocks |
| Asymmetric | A public key locks (or helps), a private key unlocks |
| Nonce | "Number used once". A value that must never repeat for the same key |
| Tag | A short authenticity check value appended to ciphertext |
| AAD | Additional Authenticated Data. Not encrypted, but covered by the tag |
| Encoding | A reversible format change with no secret (base64, PNG pixels) |
| Hash | A one-way fingerprint with no key |
| CSPRNG | Cryptographically secure random number generator |

Encryption, hashing and encoding are different things. Encryption needs a key and is reversible with it. A hash has no key and is not reversible. Encoding has no key and is trivially reversible. DiscordVault uses all three: AES-GCM (encrypt), SHA-256 (hash), base64 and PNG (encode).

---

## 1. Secure randomness (CSPRNG)

- **What:** random bytes that an attacker cannot predict, taken from the operating system.
- **Why:** every secret starts as randomness. A predictable key means no security regardless of the cipher.
- **Where:** `secrets.token_bytes` in `generate_key` (`src/crypto.py:16-17`), nonces (`src/crypto.py:31`, `src/vault.py:224`), wrap nonce (`src/crypto.py:111`). `uuid.uuid4()` for `file_id` (`src/vault.py:80`; UUID4 uses `os.urandom`). `X25519PrivateKey.generate()` for the keypair.
- **Goes wrong when:** you use `random.random()` (a predictable Mersenne Twister), seed from time, or hardcode. None of these appear in the code. Confirmed: there is no `import random`.

## 2. AES-256-GCM (symmetric authenticated encryption)

- **What:** AES is a block cipher that scrambles 16-byte blocks under a 256-bit key. GCM (Galois/Counter Mode) turns it into a stream-like cipher and adds an authentication tag. Together this is AEAD: Authenticated Encryption with Associated Data.
- **How it works internally:**
  1. Counter mode: AES encrypts a sequence `nonce || counter` (1, 2, 3 ...) to produce a keystream. The keystream is XORed with the plaintext.
  2. GHASH: a polynomial hash over GF(2^128) of the AAD and ciphertext, keyed by `H = AES_K(0)`, is XORed with an AES-encrypted counter block to produce the 16-byte tag.
- **Intuition:** XOR with a random-looking keystream hides the data. The tag works like a tamper-evident seal over the ciphertext and the AAD. Change one bit and the seal no longer matches.
- **Why DiscordVault uses it:** one primitive gives secrecy and tamper detection, it is fast with hardware support, and the `cryptography` library makes it hard to misuse.
- **Where:** `encrypt` / `decrypt` (`src/crypto.py:20-66`), called per chunk in `encode_chunk` / `decode_chunk` (`src/vault.py:251`, `:317`), and for the key wrap (`src/crypto.py:111-119`, `:151-156`).
- **Properties:** confidentiality, integrity and authenticity for ciphertext and AAD (given a secret key). The library appends the 16-byte tag to the ciphertext, which is why `ciphertext_size = len(plaintext) + GCM_TAG_SIZE` (`src/vault.py:228`).
- **Goes wrong when:**
  - A (key, nonce) pair is reused: an attacker can XOR two ciphertexts to get the XOR of plaintexts and can forge tags. This is the classic fatal GCM mistake.
  - The tag is ignored or truncated.
  - Too many messages are encrypted with one key using random nonces (96-bit random nonce collision risk rises near 2^32 messages).
  - Decrypted data is used before the tag is verified (the library prevents this: it raises `InvalidTag` and returns nothing).

**Nonce handling in this project (verified):** each chunk gets `secrets.token_bytes(12)` (`src/vault.py:224`). The wrap uses a separate random nonce (`src/crypto.py:111`). Keys are per vault, so collisions would need billions of chunks under one key. No reuse found. See [07](07-security-audit.md).

## 3. X25519 (elliptic-curve Diffie-Hellman)

- **What:** a key-agreement function on Curve25519. Two parties each have a private scalar `a`, `b` and a public point `A = aG`, `B = bG`. Each side can compute the same shared secret `abG` using only its own private key and the other's public key.
- **Intuition:** mixing paint. Everyone knows the starting colour (the base point G). You mix in a secret colour and publish the result. Mixing is easy, un-mixing is infeasible (the elliptic-curve discrete logarithm problem). If I mix my secret into your published colour, and you mix yours into mine, we get the identical final colour, and an observer cannot.
- **Why DiscordVault uses it:** to let the uploader lock the file key with only your public key. Keys are 32 bytes, operations are fast and constant-time, and there are no curve parameter choices to get wrong.
- **Where:** keypair creation `src/key_manager.py:29-31`; ephemeral key and `exchange` in `wrap_key` (`src/crypto.py:95-103`); `exchange` in `unwrap_key` (`src/crypto.py:143`).
- **Properties:** shared secret derivation. It does not authenticate who the other party is.
- **Goes wrong when:** the raw shared secret is used directly as a cipher key (it is not uniformly random; this project avoids that with HKDF), low-order points are accepted (the library rejects them), or a long-term key is reused where an ephemeral one is needed.

## 4. HKDF-SHA256 (key derivation function)

- **What:** HMAC-based Extract-and-Expand Key Derivation Function. It converts input keying material into one or more proper keys. Extract compresses the input with `HMAC(salt, secret)`. Expand stretches it into the requested length, mixing in an `info` label.
- **Intuition:** a blender that turns lumpy-but-secret material (the Diffie-Hellman output) into uniform key material, labelled for a specific purpose.
- **Why used here:** the X25519 output has structure and must be processed before it is an AES key. `info=b"discord-vault-key-wrapping-v1"` provides domain separation, so the same secret could not accidentally be valid in another context.
- **Where:** `derive_wrapping_key` (`src/crypto.py:69-80`; HKDF call at `:73-78`): `HKDF(algorithm=SHA256, length=32, salt=None, info=b"discord-vault-key-wrapping-v1")`.
- **Properties:** uniform output key, deterministic (both sides derive the same key).
- **Goes wrong when:** you use it for low-entropy passwords (HKDF is fast, so it does not resist guessing; that needs Argon2/scrypt), or you forget context labels. `salt=None` is acceptable here because the input is a high-entropy DH output.

## 5. Envelope encryption and key wrapping

- **What:** encrypt data with a random data key, then encrypt (wrap) that small key with another key or public key.
- **Why:** AES handles gigabytes quickly. Public-key operations handle only small secrets. Separate keys per vault limit damage if one leaks. Uploads need only the public key.
- **Where:** `wrap_key` / `unwrap_key` (`src/crypto.py:83-156`), called from `encode_file` (`src/vault.py:477-482`) and `decode_file` (`src/vault.py:735-740`).
- **Construction (ECIES-like):** ephemeral X25519 keypair, DH with the recipient public key, HKDF to a wrapping key, AES-256-GCM of the file key. Output: ephemeral public key (32 B), nonce (12 B), encrypted key (32 + 16 B tag = 48 B).
- **Goes wrong when:** the wrap is not authenticated (here it is, via GCM), or the recipient is not authenticated (here nobody is authenticated; see [07](07-security-audit.md)).

## 6. SHA-256 (hash function)

- **What:** maps any input to a 32-byte fingerprint. Collisions and preimages are computationally infeasible.
- **Why used here:** integrity and consistency checks only. It is not encryption and is never used as a key (HKDF uses SHA-256 internally as its HMAC hash).
- **Where:**
  - per chunk, stored in the header (`calculate_sha256`, `src/vault.py:83`, `:233`),
  - per chunk, stored in the manifest (`src/vault.py:513`),
  - whole source file (`sha256_file`, `src/vault.py:345`, `:549`, `:873`).
- **Properties:** detects changes. It cannot prove who made the data (no key).
- **Goes wrong when:** a plain hash is treated as a MAC, or stored publicly for a guessable file, because it then confirms the file's contents. The manifest does exactly this (see [07](07-security-audit.md)).

The comparisons `calculated_hash != header.sha256` (`src/vault.py:333`) compare public integrity values, not secrets, so constant-time comparison is not required there.

## 7. Authenticated header as AAD

The 128-byte chunk header is stored in clear but passed as `aad` to AES-GCM (`src/vault.py:251-256`, `:317-322`). The tag covers it. Changing the chunk index, nonce, sizes, hash, file ID, reserved bytes or any other header byte makes decryption fail with `InvalidTag`. This binds each ciphertext to its position and vault.

## 8. Encoding layers (not cryptography)

- **Base64** for binary fields inside JSON (`src/vault.py:565-584`).
- **PNG pixels** as a lossless container (`src/vault.py:168-208`). Not steganography, no secrecy.
- **ZIP/DEFLATE** for folders (`src/vault.py:371-376`). Compression happens before encryption, only for directories.

## Concepts in your checklist that are NOT in the code

| Concept | Status |
| --- | --- |
| RSA | absent |
| ChaCha20-Poly1305 | absent (AES-GCM is used) |
| SHA-512 | absent |
| Argon2, PBKDF2, scrypt | absent (no passwords) |
| Standalone HMAC | absent (HMAC only inside HKDF) |
| Digital signatures (Ed25519, ECDSA) | absent |
| Password-based encryption | absent |
| Session keys | absent |

Next: [03-key-hierarchy.md](03-key-hierarchy.md).
