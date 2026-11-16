# DiscordVault: Technical Deep Dive

This document explains how DiscordVault works from the bottom up: the cryptography, the on-disk and on-wire formats, the Discord integration, the CLI, the tests, and the engineering decisions behind each. It also lists the known weaknesses, since a reviewer will ask about them.

It describes the code as of `main` at commit `3acb26a`. Line references are approximate and refer to the files under `src/`.

---

## Table of contents

1. [What the project is](#1-what-the-project-is)
2. [Repository layout and module responsibilities](#2-repository-layout-and-module-responsibilities)
3. [End-to-end flow](#3-end-to-end-flow)
4. [Cryptography in detail](#4-cryptography-in-detail)
5. [Key management](#5-key-management)
6. [Chunk binary format](#6-chunk-binary-format)
7. [PNG codec](#7-png-codec)
8. [The manifest](#8-the-manifest)
9. [Encoding a file or folder (`encode_file`)](#9-encoding-a-file-or-folder-encode_file)
10. [Decoding and verification (`decode_file`)](#10-decoding-and-verification-decode_file)
11. [Discord client](#11-discord-client)
12. [CLI](#12-cli)
13. [Tests](#13-tests)
14. [Threat model](#14-threat-model)
15. [Known limitations and bugs](#15-known-limitations-and-bugs)
16. [Design decisions and trade-offs (interview Q&A)](#16-design-decisions-and-trade-offs-interview-qa)
17. [Possible improvements](#17-possible-improvements)
18. [Cheat sheet](#18-cheat-sheet)

---

## 1. What the project is

DiscordVault is a command-line tool that uses a private Discord text channel as encrypted file storage.

- The user runs `upload <path>`. The tool encrypts the file (or a ZIP of the folder) locally, splits the ciphertext into fixed-size chunks, writes each chunk as a 1920x1080 PNG, and posts the PNGs as message attachments through a Discord bot.
- The user runs `restore <vault_id>`. The tool pages through the channel, downloads the manifest and the chunk PNGs, decrypts and verifies everything, and rebuilds the original file or folder.

Discord only ever receives ciphertext plus a manifest. The decryption key never leaves the user's machine.

Stack: Python 3.13 (the code uses `X | None` type syntax, so 3.10+), `cryptography` (AES-GCM, X25519, HKDF), `Pillow` (PNG), `requests` (Discord REST API), `python-dotenv` (config), `pytest`.

The project is explicitly experimental. Its stated purpose is learning about cryptography, chunking and API-backed storage.

---

## 2. Repository layout and module responsibilities

```text
discord-vault/
├── src/
│   ├── crypto.py          # Primitives: AES-256-GCM, X25519 key wrap, HKDF
│   ├── key_manager.py     # Persistent X25519 keypair on disk
│   ├── vault.py           # Chunk format, PNG codec, manifest, encode/decode, ZIP
│   ├── discord_client.py  # Discord REST client: upload, list, download
│   └── main.py            # argparse CLI
├── tests/
│   ├── test_crypto.py     # 5 tests: AES-GCM behavior
│   └── test_vault.py      # 10 tests: header, chunk, tamper detection, round trip
├── .env.example           # DISCORD_BOT_TOKEN, DISCORD_CHANNEL_ID
├── requirements.txt       # Pinned dependencies
├── CLAUDE.md, README.md
```

The dependency direction is one-way:

```text
main.py ──► discord_client.py          (network only; knows nothing about crypto)
   │
   └──────► vault.py ──► crypto.py     (pure primitives; no I/O)
                 │
                 └─────► key_manager.py (key file I/O)
```

Why this split matters:

- `crypto.py` has no file or network I/O, so it is trivially unit-testable and could be audited alone.
- `discord_client.py` never touches key material. It moves opaque files and reads message text. Replacing Discord with S3 or a local disk would only mean replacing this one module.
- `vault.py` is the "format" layer. It is the only place that knows how a chunk or manifest is laid out.
- `main.py` is orchestration. It owns temporary directories and user-facing error messages.

---

## 3. End-to-end flow

### Upload

```text
path ──► [folder? ──► temp ZIP] ──► source file
                                         │
        generate random 32-byte file_key │  (one per vault)
        wrap file_key with user's X25519 public key ──► wrapped_file_key (goes in manifest)
                                         │
        read 6,220,656 bytes at a time ──┤
             for each chunk:             ▼
               nonce = random 12 bytes
               header (128 B) built; header contains SHA-256 of the plaintext
               ciphertext = AES-256-GCM(file_key, nonce, plaintext, AAD = header)
               write PNG = header ‖ ciphertext ‖ zero padding  (1920x1080 RGB)
                                         │
        write manifest.json (metadata, wrapped key, per-chunk hashes, whole-file hash)
                                         │
        Discord: post manifest.json, then chunk_000000.png ... chunk_N.png
        (temp directory deleted automatically)
```

### Restore

```text
Discord ──► page through every message in the channel
        ──► keep messages whose content contains "vault=<id>"
        ──► download manifest.json, then chunk_000000.png ... chunk_N.png into a temp dir

manifest ──► unwrap file_key with local X25519 private key
for each chunk, in order:
     PNG ──► raw bytes ──► header ──► AES-GCM decrypt (AAD = header) ──► verify sizes, IDs, SHA-256
     append plaintext to output
verify total size and whole-file SHA-256
if directory: extract the ZIP safely
temp directory deleted automatically
```

---

## 4. Cryptography in detail

All primitives come from the `cryptography` library (OpenSSL-backed). Nothing is hand-rolled. The file is `src/crypto.py`.

### 4.1 Two-level key hierarchy (envelope encryption)

```text
                 user's long-term X25519 keypair (on disk, never uploaded)
                 ┌───────────────┐
                 │ private key   │  decrypts the wrapped key
                 │ public key    │  encrypts (wraps) the file key
                 └───────────────┘
                         │
                         ▼
  per-vault random 32-byte file_key  ◄── "data encryption key" (DEK)
                         │
                         ▼
        AES-256-GCM encrypts every chunk of that vault
```

- **Data key (file key):** a fresh random 32-byte AES key per upload, from `secrets.token_bytes(32)` (the OS CSPRNG).
- **Key-encryption mechanism:** the file key is "wrapped" for the user's X25519 public key, and the wrapped form is stored in the manifest on Discord.

Why two levels instead of encrypting directly with a long-term key?

1. **Blast radius.** Each vault has its own key. Compromising one file key does not expose other vaults.
2. **Public-key upload.** Encrypting needs only the public key. The upload machine does not need the private key at all. Only restore needs it.
3. **Key rotation and sharing.** The bulk data never has to be re-encrypted to change who can read it. Only the small wrapped key changes. (Not implemented, but the format permits it.)
4. **Nonce safety.** Using a fresh key per vault limits how many messages are encrypted under one key (see 4.3).

### 4.2 AES-256-GCM (bulk encryption)

`encrypt(data, key, aad=None, nonce=None) -> (ciphertext, nonce)`
`decrypt(ciphertext, key, nonce, aad=None) -> plaintext`

- AES-256 in Galois/Counter Mode is an AEAD cipher: it gives confidentiality and integrity in one primitive.
- Key size 32 bytes, nonce size 12 bytes (the standard GCM size), tag 16 bytes appended to the ciphertext by the library. Both `encrypt` and `decrypt` validate key and nonce lengths and raise `ValueError` otherwise.
- If a nonce is not supplied, a random one is generated and returned. `vault.py` generates the nonce itself, because the nonce has to be written into the header before encryption (the header is the AAD). It then checks that the nonce returned equals the one passed (`encode_chunk`), as a sanity assertion.
- Any modification of ciphertext, nonce, AAD or key makes decryption raise `cryptography.exceptions.InvalidTag`. The tests exercise this directly.

**AAD (additional authenticated data).** Each chunk's entire 128-byte header is passed as AAD. The header is stored unencrypted but authenticated. Flipping a bit in the chunk index, file ID, total chunk count, plaintext size, nonce or hash makes the GCM tag check fail. This stops an attacker from silently reordering, swapping or splicing chunks and from lying about sizes, even without knowing the key.

**Why GCM and not CBC/CTR plus HMAC?** GCM is a single well-reviewed AEAD construction with hardware support (AES-NI). It avoids the classic mistakes of encrypt-and-MAC composition and padding oracles. ChaCha20-Poly1305 would be an equally defensible choice.

### 4.3 Nonce handling

- Every chunk gets its own random 96-bit nonce (`secrets.token_bytes(12)`).
- GCM is catastrophically broken if a (key, nonce) pair is reused: it leaks the XOR of plaintexts and allows forgery.
- With random 96-bit nonces the collision probability becomes non-negligible around 2^32 messages under one key (birthday bound; NIST SP 800-38D limits random-nonce use to 2^32 invocations per key). At ~6 MB per chunk, 2^32 chunks is tens of exabytes, so a per-vault key makes this irrelevant in practice. This is a concrete reason why the per-vault key matters.
- A counter-based nonce (chunk index) would remove the probabilistic risk entirely. Random nonces were chosen because they are simpler and the key is never reused across vaults.

### 4.4 X25519 key wrapping (ECIES-style)

`wrap_key(file_key, recipient_public_key) -> {ephemeral_public_key, nonce, encrypted_file_key}`
`unwrap_key(envelope, recipient_private_key) -> file_key`

This is an ECIES/HPKE-like construction, close in spirit to libsodium's `crypto_box_seal` or `age`:

Wrapping:

1. Generate a fresh **ephemeral** X25519 keypair for this one file key.
2. Compute the Diffie-Hellman shared secret: `ephemeral_private x recipient_public`.
3. Derive a 32-byte **wrapping key** with HKDF-SHA256 from the shared secret (`info = b"discord-vault-key-wrapping-v1"`, `salt = None`).
4. Encrypt the file key with AES-256-GCM using the wrapping key and a random 12-byte nonce (no AAD).
5. Output: ephemeral public key (32 B), nonce (12 B), encrypted file key (32 + 16 tag = 48 B). The ephemeral private key is discarded.

Unwrapping:

1. Load the ephemeral public key from the envelope.
2. Compute `recipient_private x ephemeral_public`. By the DH property this equals the same shared secret.
3. HKDF to the same wrapping key, AES-GCM decrypt, get the file key.

Why this design:

- **Ephemeral key per wrap** gives each envelope a unique shared secret. The sender needs no long-term secret and the wrapping key is never reused.
- **HKDF step.** A raw DH output is not uniformly random and must not be used directly as a cipher key. HKDF extracts and expands it into a proper key. The `info` string gives domain separation: the same shared secret could never be accepted for a different protocol or version (`-v1`).
- **X25519** is a modern, fast, constant-time curve with 32-byte keys and no parameter or point-validation pitfalls like NIST curves. The `cryptography` library rejects low-order points.
- **Authenticated wrap.** Because the file key is encrypted with GCM, a modified envelope fails to unwrap rather than yielding a wrong key.

Why not RSA? Larger keys, slower, and OAEP padding is easier to misuse. Why not a password-derived key (scrypt/Argon2)? It would be a reasonable alternative that removes the key file, but it ties security to password strength. The keypair approach was chosen so the secret is a full-entropy 256-bit value.

### 4.5 What SHA-256 is for

SHA-256 is used only for integrity and consistency checks, never as encryption or key derivation (HKDF uses it internally as its hash). Three levels:

1. **Per-chunk hash inside the header** (hash of the plaintext chunk). It is authenticated by GCM through the AAD.
2. **Per-chunk hash in the manifest** (also of the plaintext).
3. **Whole-file hash in the manifest** (`file_sha256`, computed over the pre-chunking source, which is the ZIP for directories).

GCM already guarantees each chunk was not modified. The hashes add defense in depth and catch logic errors (wrong chunk order, truncation, a chunk replaced by a valid chunk from another vault). The whole-file hash is the only thing that proves the reassembled result is correct end to end.

---

## 5. Key management

File: `src/key_manager.py`. Run once with `python -m src.key_manager`.

- Location: `<project root>/.discord-vault/private.key` and `public.key`. The root is computed from `__file__`, so keys are tied to the repo directory, not the current working directory.
- Format: raw 32-byte values (`Encoding.Raw`, `PrivateFormat.Raw`, `NoEncryption`). No PEM, no passphrase.
- Permissions: private key `0600`, public key `0644`.
- `generate_keypair()` refuses to overwrite an existing private key (`FileExistsError`). This is a deliberate guard, because overwriting would make every existing vault permanently unreadable.
- `load_private_key()` / `load_public_key()` read the raw bytes and construct key objects.
- `.discord-vault/`, `*.key`, `*.pem`, `*.der` and `.env` are in `.gitignore`.

Consequences to be able to explain:

- **Losing `private.key` means losing all data.** There is no recovery path. The README warns about this.
- **The private key is stored unencrypted.** Anyone who can read the file can decrypt the vaults. The mitigation is filesystem permissions and full-disk encryption only. A stronger design would encrypt the key at rest with a passphrase (scrypt/Argon2 plus AES-GCM) or use the OS keyring/TPM/hardware token.
- **Small permission race.** `write_bytes` creates the file with the default umask and `chmod(0o600)` happens afterwards, so there is a brief window where it may be group/world readable. Creating it with `os.open(..., 0o600)` removes the window.
- **Upload needs only the public key**, restore needs the private key. This asymmetry is the main point of using X25519 instead of a symmetric master key.

---

## 6. Chunk binary format

File: `src/vault.py`. Each chunk is one PNG whose pixel bytes are:

```text
offset  size  field
0       4     magic            b"DVLT"
4       1     version          1
5       1     flags            0 (reserved, unused)
6       2     header_size      128
8       16    file_id          UUID4 bytes (vault identifier, same for all chunks)
24      8     chunk_index      uint64, zero-based
32      8     total_chunks     uint64
40      8     plaintext_size   uint64, bytes of plaintext in this chunk
48      12    nonce            AES-GCM nonce
60      8     payload_size     uint64, ciphertext length = plaintext_size + 16
68      32    sha256           SHA-256 of this chunk's plaintext
100     28    reserved         zero bytes
128     ...   ciphertext       AES-256-GCM output, including 16-byte tag
...     ...   zero padding     up to the image capacity
```

`struct` format string: `"<4sBBH16sQQQ12sQ32s"`.

- `<` = little-endian with **no alignment padding**. This is essential for a stable binary format. Native alignment would insert padding and differ across platforms.
- The base struct is 100 bytes. 28 bytes are reserved and zero-filled to reach a fixed 128-byte header. Two `assert`s check `BASE_HEADER_SIZE == 100` and `RESERVED_SIZE == 28` at import time.
- Fixed-size header, `magic` and `version` follow standard file-format practice. They allow fast rejection of garbage input (`Invalid magic`) and future format changes (`Unsupported version`). The `header_size` field and reserved bytes are room to grow.

### Chunk size

```text
IMAGE_CAPACITY = 1920 x 1080 x 3 channels = 6,220,800 bytes
CHUNK_SIZE     = IMAGE_CAPACITY - HEADER_SIZE (128) - GCM_TAG_SIZE (16) = 6,220,656 bytes
```

The plaintext per chunk is chosen so that header + ciphertext (plaintext + tag) fills the image exactly. Full chunks have no padding. Only the last chunk is smaller and padded with zeros.

Number of chunks: `ceil(file_size / CHUNK_SIZE)`. A 1.42 GB file is about 245 chunks.

Why ~6.2 MB? One full-HD RGB image is the unit of capacity, which gives a tidy, fixed, easy-to-reason-about size. It also stays below Discord's attachment size limit for regular uploads (historically 8 MB; the limit has changed over time, so check the current number). Larger chunks mean fewer messages and API calls, smaller chunks mean cheaper retries.

### Authentication of header fields

Because the header bytes are the AAD of the GCM call:

- Changing any header byte (chunk index, nonce, size, hash, file ID) breaks the tag.
- The `sha256` field is bound to the ciphertext.
- Chunks cannot be moved between vaults, because `file_id` is authenticated.
- Chunks within one vault cannot be reordered unnoticed because `chunk_index` is authenticated and also compared against the manifest position.

Tests exist for tampering with: ciphertext, nonce, SHA-256 field, chunk index, plaintext size.

---

## 7. PNG codec

```python
bytes_to_png(data, output)   # pad to IMAGE_CAPACITY with zeros, Image.frombytes("RGB", (1920,1080), padded), save as PNG
png_to_bytes(path)           # check size == (1920, 1080), convert("RGB"), tobytes()
```

- The data is treated as raw RGB pixel bytes: three bytes per pixel, row by row. There is no steganography and no visual meaning. An image of encrypted data looks like colored static.
- PNG is **lossless**. JPEG or WebP-lossy would corrupt the data. If Discord re-encoded an image, decryption would fail. PNG round-trips exactly.
- Image dimensions are checked on decode. A mismatch is rejected.
- Because ciphertext is random, PNG's DEFLATE cannot compress it. The file size is about the same as the raw data (a little larger due to PNG headers and filters). Only the zero padding of the last chunk compresses.
- The zero padding of the final chunk is stripped by using `payload_size` from the header, not by scanning for the end.

Honest assessment: wrapping data in PNGs is not required for storage, since Discord accepts arbitrary attachments. It makes the data look like an image upload and keeps a uniform, fixed chunk unit. It costs CPU for encoding and a small size overhead. In an interview, say it is a design choice for uniformity and image-typed attachments, and that dropping it to upload raw `.bin` chunks would be simpler and faster.

---

## 8. The manifest

`manifest.json` is created next to the chunks and is uploaded to Discord as the first message of the vault. It is plaintext JSON.

```json
{
  "version": 1,
  "file_id": "<32 hex chars = UUID4>",
  "filename": "soloLeveling.mp4",
  "source_type": "file",                  // or "directory"
  "archive_format": null,                 // "zip" for directories
  "file_size": 1523456789,                // size of the encrypted source (ZIP for directories)
  "file_sha256": "<hex>",                 // whole-source hash
  "chunk_size": 6220656,
  "total_chunks": 245,
  "encryption": {
    "algorithm": "AES-256-GCM",
    "key_wrap": "X25519-HKDF-SHA256-AES-256-GCM"
  },
  "wrapped_file_key": {
    "ephemeral_public_key": "<base64, 32 bytes>",
    "nonce": "<base64, 12 bytes>",
    "encrypted_file_key": "<base64, 48 bytes>"
  },
  "chunks": [
    {"index": 0, "size": 6220656, "sha256": "<hex>", "image": "chunk_000000.png"}
  ]
}
```

Why the manifest exists: it holds everything needed to restore except the private key (the wrapped key, chunk list, hashes, original name and type), and `list` can read it without downloading chunks.

What is exposed by it (it is not encrypted): filename, original size, type, chunk count, per-chunk and whole-file SHA-256 hashes, and the key envelope. The envelope is safe to expose because it is useless without the private key. The hashes reveal plaintext fingerprints: someone who has the same file can confirm that you stored it. The README lists encrypted manifests as future work.

---

## 9. Encoding a file or folder (`encode_file`)

`encode_file(input_path, output_dir)` in `vault.py`:

1. **Validate** the input exists and create `output_dir`.
2. **Folder handling.** If the input is a directory, `archive_directory` creates a ZIP (DEFLATE level 6) inside a `tempfile.mkdtemp` directory, with paths stored relative to the folder. It raises on symlinks (they could point outside the tree and leak files) and skips non-files. Entries are sorted, so the archive is deterministic in file order. The temp dir is removed in a `finally` block even if encoding fails.
3. **Compute sizes**: `total_chunks = ceil(size / CHUNK_SIZE)`.
4. **Create identifiers and keys**: `file_id = uuid4().bytes`, `file_key = generate_key()`, then `wrap_key(file_key, load_public_key())`.
5. **Stream chunks.** The source file is read `CHUNK_SIZE` bytes at a time (memory use is a few chunk-sized buffers, not the whole file). For each chunk, `encode_chunk` builds the header, encrypts with the header as AAD, checks the nonce and ciphertext length, and writes the PNG as `chunk_<6-digit index>.png`.
6. **Hash and write the manifest.** `sha256_file` re-reads the source in 1 MiB pieces to compute `file_sha256`. Binary fields are base64-encoded for JSON.

Note that compression only happens for folders (ZIP). Single files are not compressed before encryption. Compressing after encryption is useless, because ciphertext does not compress. Compressing before encryption is possible but has known side-channel concerns (CRIME/BREACH-style) when attacker-controlled data is mixed with secrets, and it is listed as a future improvement.

Chunk encryption is independent per chunk, so chunks are random-access verifiable, damage in one chunk affects only that chunk, and the process could be parallelized.

---

## 10. Decoding and verification (`decode_file`)

`decode_file(input_dir, output_file)`:

1. Load and parse `manifest.json`. Reject unknown `version`.
2. **Unwrap the file key** with the local private key. A wrong private key makes AES-GCM raise `InvalidTag`.
3. Validate `len(chunks) == total_chunks` and `source_type in {file, directory}`.
4. Decide the write target. For a file, write directly to `output_file`. For a directory, write to a temporary `restore.zip`.
5. For each chunk, in manifest order, check:
   - `chunk_info["index"]` equals its position,
   - the PNG exists,
   - `decode_chunk` succeeds: PNG size OK, magic and version OK, ciphertext length matches `payload_size`, **GCM tag verifies with the header as AAD**, plaintext length matches `plaintext_size`, SHA-256 matches the header,
   - `header.file_id` equals the manifest `file_id`,
   - `header.chunk_index` equals the index,
   - `header.total_chunks` equals the manifest total,
   - the plaintext length equals the manifest size and the plaintext SHA-256 equals the manifest hash,
   - then append the plaintext to the output.
6. **Final checks.** Total size equals `file_size`, and the SHA-256 of the whole output equals `file_sha256`.
7. For directories, `extract_zip_safely` extracts the ZIP and the temp directory is removed in `finally`.

`extract_zip_safely` resolves each member path against the resolved output directory and rejects anything that falls outside it ("Zip Slip" protection). This matters because the ZIP content is restored from a downloaded source, and a malicious ZIP could contain `../../.bashrc`.

Because every layer is checked (GCM tag, header consistency, per-chunk hash, manifest consistency, whole-file hash), a single bit flip, a missing, duplicated, reordered or replaced chunk, or the wrong key are all detected and produce an exception.

---

## 11. Discord client

File: `src/discord_client.py`. A thin wrapper over the Discord REST API v10 using `requests`. It does not use `discord.py` or a gateway connection. There is no event loop, no websocket, and the bot never needs to be "online". It is a plain authenticated HTTP client, which is simpler and sufficient for batch upload/download.

### Setup and auth

- `load_dotenv()` runs at module import. `DISCORD_BOT_TOKEN` is read from the environment, and `ValueError` is raised if missing. `DISCORD_CHANNEL_ID` is read in `main.py`.
- A `requests.Session` carries `Authorization: Bot <token>` and a `User-Agent` in Discord's required `DiscordBot (url, version)` form. A session reuses TCP/TLS connections across many requests.
- The bot needs, in the target channel, permissions to View Channel, Send Messages, Attach Files, and Read Message History (to list and download).

### `_request` with rate-limit handling

Discord answers `429 Too Many Requests` with a JSON body containing `retry_after` (seconds). `_request` loops up to `MAX_RETRIES = 5` times: on 429 it reads `retry_after` (falling back to the `Retry-After` header, then 1 second), sleeps, and retries. Any non-OK final response raises `DiscordError` containing the status and body.

### Upload

`upload_file` posts `multipart/form-data` to `POST /channels/{id}/messages`: a `payload_json` field carrying the message content and `files[0]` carrying the PNG with content type `image/png`.

`upload_vault`:

1. Reads the manifest to get `file_id`.
2. Uploads `manifest.json` first with message text `DiscordVault vault=<id> type=manifest`.
3. Checks the number of `chunk_*.png` files equals `total_chunks`.
4. Uploads each chunk (sorted by name) with text `DiscordVault vault=<id> type=chunk index=<n>`.

The message text is the **index of the vault**: it is how the channel is searched without any database. The channel itself is the database.

### Listing and download

- `list_messages` paginates `GET /channels/{id}/messages?limit=100&before=<id>`. Discord returns newest first, so the last message's ID is the cursor for the next page. It stops when a page is empty or short. There is no page cap, so a large channel is fully walked.
- `list_vaults` keeps only messages that start with `DiscordVault`, parse into `key=value` pairs, and are `type=manifest`. For each one it downloads the manifest attachment into memory and extracts name, type, size, chunk count, chunk size and hash. A failure on one vault prints a warning and continues.
- `download_vault` filters the messages whose content contains `vault=<id>`, picks out `manifest.json` and `chunk_<n>.png` attachments, downloads the manifest, verifies its `file_id` equals the requested one, then downloads each chunk by index. A missing chunk raises `DiscordError`.
- `download_attachment` streams the CDN URL in 1 MiB pieces to disk, with a text progress bar based on the attachment's size field. Attachment CDN URLs do not need the bot token (they are signed URLs), so plain `requests.get` is used.

### Design points

- **Manifest first** means a vault is discoverable as soon as its first message is posted, and `restore` can learn `total_chunks` up front.
- **Filename convention `chunk_<6-digit index>.png`** gives lexicographic order that equals numeric order, and lets the downloader parse the index from the name.
- **Stateless:** no local database. All state is in the channel.

---

## 12. CLI

File: `src/main.py`, using `argparse` subparsers. Run as `python -m src.main <command>` (the relative imports require running as a module from the repo root).

| Command | What it does |
| --- | --- |
| `upload <path>` | Encrypt into a `TemporaryDirectory`, upload the manifest and chunks, and let the temp dir be deleted on exit. |
| `list` | Print every vault found in the channel: name, ID, type, size, chunks, chunk size, SHA-256. |
| `restore <vault_id> [output]` | Download into a `TemporaryDirectory`, decode to `output` (default `restored/<original filename>`). |
| `encode <input> <dir>` | Local-only encryption into a vault directory. Developer command. |
| `decode <dir> <output>` | Local-only decryption of a vault directory. Developer command. |

Design points:

- Context managers (`with tempfile.TemporaryDirectory`) guarantee cleanup of encrypted intermediates, including after exceptions.
- `restore` wraps the download in `try/except DiscordError` and prints `Error: vault '<id>' was not found.` rather than a traceback. The decode step is also wrapped, printing `Error: restore failed: <reason>`.
- `format_size` renders sizes in binary units (1024).
- `encode`/`decode` exist so the crypto and format layers can be exercised without a network.

---

## 13. Tests

Run from the repo root with `python -m pytest` (tests import `src.*`). The suite has 15 tests.

`tests/test_crypto.py` (5):
- round trip of encrypt and decrypt,
- ciphertext differs from plaintext and nonce is 12 bytes,
- the same plaintext encrypted twice gives a different nonce and ciphertext,
- a flipped ciphertext bit raises `InvalidTag`,
- a wrong key raises `InvalidTag`.

`tests/test_vault.py` (10):
- header pack/unpack round trip,
- secure chunk round trip through a real PNG,
- wrong key fails,
- tampering with the ciphertext, nonce, SHA-256 field, chunk index and plaintext size are each detected,
- complete file round trip through `encode_file` and `decode_file` (about 2.8 MB),
- `CHUNK_SIZE` plus header plus tag equals the image capacity.

**Gaps worth knowing:**

- `test_complete_file_roundtrip` calls `load_public_key()`, so it **requires `.discord-vault/` keys to exist**. On a fresh checkout it fails with `FileNotFoundError` until `python -m src.key_manager` has been run (I observed 14 pass, 1 fail on a clean clone). A better test would generate a temporary keypair and monkeypatch the key paths.
- There are no tests for `wrap_key`/`unwrap_key`, the ZIP functions (including Zip Slip), the multi-chunk path, the manifest checks, or the Discord client (which would need `responses`/`requests-mock`).

---

## 14. Threat model

What is protected:

| Threat | Defense |
| --- | --- |
| Discord (or anyone with channel access) reading file contents | AES-256-GCM, key never uploaded in usable form |
| Someone altering a chunk | GCM tag (ciphertext and header), per-chunk and whole-file hashes |
| Reordering, duplicating or dropping chunks | Authenticated `chunk_index`/`total_chunks`, manifest checks, whole-file hash |
| Swapping in chunks from another vault | Authenticated `file_id` plus checks against the manifest |
| Stolen manifest | Only the wrapped key, useless without the private key |
| Malicious ZIP on restore | `extract_zip_safely` path check, symlink rejection on archive |
| Leftover plaintext/ciphertext on disk | Temp directories deleted in `finally`/context managers |
| Secrets in git | `.gitignore` for `.env`, `.discord-vault/`, `*.key` |

What is **not** protected:

- **Metadata:** Discord sees attachment sizes, timestamps, counts, and the vault IDs. The manifest exposes the filename, size, type and plaintext hashes.
- **Compromise of the local machine or private key.** The key is unencrypted at rest.
- **Authenticity of the uploader.** The public key is public, so anyone with it (and write access to the channel) can create a valid vault that the owner will accept as genuine. This is anonymous-sender encryption like `crypto_box_seal`. The scheme gives confidentiality and tamper detection against outsiders who lack the file key, not sender authentication. An attacker who can post to the channel could add a forged vault.
- **Availability.** Anyone with channel access can delete messages, so the data can be destroyed. The bot token gives full control of the bot's channel access.
- **Platform risk.** Discord can remove content or accounts, change limits or expire CDN links. Using it as a storage layer may also violate Discord's terms of service. This is a learning project, not a backup system (the README says so).
- **Traffic analysis.** File size is inferable from the chunk count.

---

## 15. Known limitations and bugs

Being upfront about these is better than having them discovered in the interview.

Security:

1. Private key stored unencrypted. Brief permission race when it is created (`write_bytes` then `chmod`).
2. Manifest is plaintext and unauthenticated. It is not covered by any MAC or signature, so someone with channel write access could replace the manifest of a vault (a legitimate-looking one wrapping their own key is accepted, because the file key is wrapped to the public key). Chunk-level AAD detects most tampering, but the manifest itself is trusted for `filename`, `source_type` and the chunk list.
3. **Path traversal through the manifest filename.** `cmd_restore` builds the default output path as `Path("restored") / manifest["filename"]` without sanitizing. A manipulated manifest with a name like `../../x` would write outside `restored/`. A fix is to use `Path(name).name` and reject path separators.
4. No sender authentication (see Threat model).
5. The wrapped-key envelope does not bind the ephemeral public key into the HKDF `info` or the AAD (HPKE/age do). It is not an exploitable weakness here, but it is a known hardening step.
6. HKDF uses `salt=None`. This is acceptable since the input is a high-entropy DH output and the `info` string is set.

Robustness:

7. **No resume, no atomicity.** The upload posts the manifest and then the chunks one by one. If it fails halfway, the vault is left partial in the channel (`list` shows it, `restore` fails with a missing chunk). There is no cleanup and no delete command (`delete_message` is not implemented).
8. Rate limiting only handles 429 on the retry path, with at most 5 attempts. There is no handling of 5xx or network errors, and **no request timeouts** (`requests` waits forever by default).
9. `restore` maps *any* `DiscordError` (including network problems, auth failures, a missing chunk) to "vault not found". The exit code is 0 even on failure, so scripts cannot detect errors.
10. For files, `decode_file` writes directly to the final output path. If verification fails, a bad file remains at that path. Writing to a temp file and renaming after the final hash check would be safer.
11. Everything is sequential: no parallel upload or download, and the whole channel history is scanned for every `list`/`restore`. This is O(messages in channel).
12. Vault lookup uses a substring match on `vault=<id>`. It works because IDs are 32-hex UUIDs, but a prefix of the ID could match several. Message content is also user-writable text (an attacker with channel access could post fake messages).
13. Directory ZIPs do not preserve empty directories, permissions or symlinks (symlinks are rejected). Empty file edge case: a 0-byte file produces 0 chunks.
14. `encode_file` re-reads the source to hash it (one extra pass), and prints progress with `print` rather than `logging`.
15. Tests: the end-to-end test depends on local keys (see 13). `requirements.txt` pins a long list of transitive dependencies (e.g. `certifi`, `cffi`), which is good for reproducibility.

---

## 16. Design decisions and trade-offs (interview Q&A)

**Why Discord as storage?** It is a learning project. Discord offers free, high-availability blob storage via attachments and a message list that works as an index. The goal was practicing crypto, chunking and API clients, not building production backup. The trade-offs are limits on attachment size, rate limits, ToS risk, and no durability guarantees.

**Why envelope encryption (a file key wrapped by X25519) and not just one master key?** Per-vault keys limit damage and nonce-reuse risk, uploading needs only the public key, and the bulk data does not need re-encryption if the access mechanism changes.

**Why X25519 + HKDF + AES-GCM instead of RSA?** Small keys, fast, constant-time implementations, hard to misuse. HKDF turns the raw DH output into a uniform key and provides domain separation. This mirrors accepted designs (ECIES, HPKE, libsodium sealed boxes, age).

**Why an ephemeral keypair for each wrap?** It gives a unique shared secret per envelope and means the sender holds no long-term secret. The ephemeral private key is discarded immediately.

**Why use the header as GCM AAD?** The header must be readable before decryption (to get nonce, sizes and ID) but must not be modifiable. AAD gives integrity without encrypting it.

**Why per-chunk encryption instead of encrypting the whole file and then splitting?** Constant memory (streaming), independent verification and retry of each chunk, damage isolation, and the possibility of parallelism and partial restore. The cost is one nonce and tag per chunk (28 bytes plus a 128-byte header per ~6 MB, about 0.0025%) and the need to authenticate ordering and completeness, which the header and manifest do.

**Why random nonces?** Simple and safe given a unique key per vault and a 2^32-message bound that cannot be reached. Counter nonces would be the alternative.

**Why three levels of SHA-256 on top of GCM?** GCM proves a chunk was not changed under this key. The hashes verify structural correctness (right chunk, right place, nothing missing) and the final reconstructed file. It is defense in depth.

**Why PNG?** Lossless, standard, and gives a fixed chunk size from the image capacity. It is not required technically, and it adds CPU time and slight size overhead.

**Why REST with `requests` instead of `discord.py`?** There is no need for a gateway connection or events. A few HTTP calls are all that is required, which keeps dependencies and complexity down.

**Why is the manifest uploaded in plaintext?** It was simpler and lets `list` work without the private key or downloading chunks. It is a known privacy tradeoff and the first improvement in the README. A fix is to encrypt the manifest body with the file key (except `file_id` and the key envelope) or with a key derived from the private key.

**Why `struct` and a fixed header?** Deterministic binary layout, cheap to parse, versionable, with reserved space. `<` forces little-endian and no padding for portability.

**Why `tempfile` and context managers?** So that encrypted intermediates never accumulate and cleanup happens on error paths.

**What happens if one chunk is deleted from Discord?** `restore` raises `Missing chunk N`. Data in other chunks is intact, but the file is not recoverable since there is no erasure coding or redundancy.

**What would you change first?** (1) Encrypt the key at rest and the manifest. (2) Fix the filename path traversal. (3) Add timeouts, retry for 5xx and a resume/verify mode. (4) Atomic output via temp file and rename. (5) Make the end-to-end test generate its own keypair. (6) Parallel transfers, using a local index instead of scanning the whole channel.

---

## 17. Possible improvements

- Passphrase-protect the private key (scrypt/Argon2id + AES-GCM) or use the OS keyring.
- Encrypt the manifest and make it authenticated (for example, encrypt it with the file key and bind it to the chunks).
- Sign vaults (Ed25519) for sender authenticity.
- Bind the ephemeral public key into HKDF info/AAD, and multi-recipient wrapping (several envelopes per manifest).
- Resumable upload/download with a state file, 5xx and network retry with backoff, timeouts.
- Parallel transfers with bounded concurrency while respecting rate-limit buckets.
- Local SQLite index of vaults to avoid scanning the channel.
- Compression before encryption for single files (with the side-channel caveat).
- Deduplication and incremental backups (content-defined chunking).
- Redundancy such as Reed-Solomon parity chunks to survive deletions.
- Vault deletion (`DELETE /channels/{id}/messages/{id}`), pluggable storage backends, structured logging, proper exit codes.

---

## 18. Cheat sheet

| Item | Value |
| --- | --- |
| Bulk cipher | AES-256-GCM, 32-byte key, 12-byte random nonce, 16-byte tag |
| Key wrap | Ephemeral X25519 + HKDF-SHA256 (`info=discord-vault-key-wrapping-v1`, no salt) + AES-256-GCM |
| File key | 32 random bytes per vault (`secrets`) |
| Long-term key | X25519, raw 32 bytes, `.discord-vault/private.key` (0600), unencrypted |
| AAD | The 128-byte chunk header |
| Header | 128 bytes, magic `DVLT`, version 1, little-endian `struct` `<4sBBH16sQQQ12sQ32s` + 28 reserved |
| Image | 1920x1080 RGB PNG = 6,220,800 bytes |
| Chunk plaintext | 6,220,656 bytes (image - 128 - 16) |
| Integrity | GCM tag + per-chunk SHA-256 (header and manifest) + whole-file SHA-256 |
| Vault ID | UUID4 (32 hex), appears in message text `vault=<id>` |
| Discord messages | `DiscordVault vault=<id> type=manifest` / `type=chunk index=<n>` |
| Discord API | REST v10, `Bot` token, multipart upload, `before=` pagination, 429 retry (5 attempts) |
| Folders | Temporary ZIP (DEFLATE 6), symlinks rejected, Zip Slip checked on restore |
| Tests | 15 (5 crypto, 10 vault); end-to-end test needs a generated keypair |
| Run | `python -m src.key_manager`, then `python -m src.main upload\|list\|restore\|encode\|decode` |
