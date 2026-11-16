# DiscordVault

Encrypted file storage using Discord as a storage backend.

DiscordVault encrypts files locally with **AES-256-GCM**, splits the encrypted data into chunks, encodes the chunks as lossless PNGs, and stores them as Discord attachments.

> Experimental project for learning about cryptography, encrypted storage, chunking, and API-based storage backends.

---

## Architecture

```mermaid
flowchart LR
    A[File / Folder] --> B{Input Type}

    B -->|File| C[Read File]
    B -->|Folder| D[Create Temporary ZIP]

    C --> E[Generate AES-256 Key]
    D --> E

    E --> F[AES-256-GCM]
    F --> G[Encrypted Data]

    G --> H[Split into Chunks]
    H --> I[Encode as PNG]

    E --> J[X25519 Key Wrapping]
    J --> K[Wrapped File Key]

    I --> L[Encrypted Chunks]
    K --> M[Manifest]

    L --> N[Discord]
    M --> N

    N --> O[Download]
    O --> P[Decrypt + Verify]

    P --> Q{Original Type}
    Q -->|File| R[Restore File]
    Q -->|Folder| S[Extract ZIP]
    S --> T[Restore Folder]
````

### Upload / Restore Flow

```mermaid
sequenceDiagram
    participant User
    participant Vault as DiscordVault
    participant Discord

    User->>Vault: upload file/folder
    Vault->>Vault: Encrypt + chunk
    Vault->>Vault: Generate manifest
    Vault->>Discord: Upload manifest + chunks
    Discord-->>Vault: Upload complete
    Vault->>Vault: Delete temporary encrypted data

    User->>Vault: restore VAULT_ID
    Vault->>Discord: Download vault
    Discord-->>Vault: Manifest + encrypted chunks
    Vault->>Vault: Decrypt + verify SHA-256
    Vault-->>User: Restore to ./restored/
    Vault->>Vault: Delete temporary data
```

---

## Features

* AES-256-GCM authenticated encryption
* X25519-based key wrapping
* HKDF-SHA256 key derivation
* SHA-256 integrity verification
* Automatic chunking
* Lossless PNG encoding
* File and folder support
* Automatic ZIP handling for folders
* Discord bot/API storage
* Vault metadata listing
* Automatic temporary-file cleanup
* Local encryption/decryption
* File restoration

---

## How It Works

### Files

```text
file
 │
 ▼
AES-256-GCM
 │
 ▼
encrypted data
 │
 ▼
chunks
 │
 ▼
PNG images
 │
 ▼
Discord
```

### Folders

Folders are temporarily converted into a ZIP archive before encryption.

```text
my-project/
├── src/
├── tests/
└── README.md

       ↓

temporary ZIP
       ↓
AES-256-GCM
       ↓
encrypted chunks
       ↓
Discord
```

The temporary ZIP and encrypted chunks are automatically removed after a successful upload.

---

## CLI

### Upload

The normal workflow is a single command:

```bash
python -m src.main upload data/input/soloLeveling.mp4
```

For a folder:

```bash
python -m src.main upload ./my-project
```

DiscordVault internally:

1. Encrypts the input.
2. Creates the required chunks.
3. Uploads the manifest and chunks.
4. Removes the temporary encrypted data.

No manually created `data/output/` vault is required.

---

### List Vaults

```bash
python -m src.main list
```

Example:

```text
Vaults
────────────────────────────────────────────────

1. soloLeveling.mp4
   ID:       c326642e77664612924cb1746e879199
   Type:     file
   Size:     1.42 GB
   Chunks:   242
   Chunk:    6.07 MB
   SHA-256:  a1b2c3d4e5f6...

2. my-project
   ID:       91c8...
   Type:     directory
   Size:     8.42 MB
   Chunks:   2
   Chunk:    6.07 MB
   SHA-256:  f6e5d4c3b2a1...
```

The Discord message itself only contains the vault identifier and storage metadata. The detailed file information comes from the vault manifest.

---

### Restore

Restore using only the vault ID:

```bash
python -m src.main restore <VAULT_ID>
```

The file is automatically restored under:

```text
restored/
└── original-file-name
```

For example:

```text
restored/
└── soloLeveling.mp4
```

Folders are reconstructed automatically:

```text
restored/
└── my-project/
    ├── src/
    ├── tests/
    └── README.md
```

Temporary downloaded chunks are removed after the restore process finishes.

You can also specify an output path:

```bash
python -m src.main restore <VAULT_ID> ./my-output
```

If the vault ID is invalid, the CLI reports a clean error instead of exposing a Python traceback:

```text
Error: vault 'invalid-id' was not found.
```

---

### Local Encode / Decode

The lower-level commands are still available for development and testing.

```bash
python -m src.main encode input.bin vault/
```

```bash
python -m src.main decode vault/ recovered.bin
```

Normal users generally only need:

```text
upload
list
restore
```

---

## Encryption

Each vault receives a randomly generated AES-256 key.

```mermaid
flowchart TD
    A[Random AES-256 Key] --> B[AES-256-GCM]
    B --> C[Encrypted File Data]

    A --> D[X25519 + HKDF]
    D --> E[Wrapped File Key]

    C --> F[Discord]
    E --> F

    G[Local Private Key] --> D
```

The private key remains on the user's machine and is never uploaded to Discord.

SHA-256 is used for integrity verification of:

* Individual encrypted chunks
* The final reconstructed file

SHA-256 is **not** used as encryption.

### Keys and How They Fit Together

There are two layers: one key encrypts the data, and a separate keypair protects that key.

| Name | What it is | Algorithm | Lifetime | Where it lives |
| --- | --- | --- | --- | --- |
| key1 | Private key | X25519 | Permanent, created once | `.discord-vault/private.key` (local only) |
| key2 | Public key, derived from key1 | X25519 | Permanent | `.discord-vault/public.key` |
| key3 | File key: 32 random bytes from `secrets.token_bytes`. It encrypts every chunk of one vault | AES-256-GCM | One per upload | Never stored in plain form. Stored wrapped in `manifest.json` |
| key4 | Disposable keypair, created for each wrap | X25519 | One function call | Public half in `manifest.json`. Private half is deleted |
| wrapping key | Temporary key made from key4's private half and key2 | X25519, then HKDF-SHA256 | One function call | Never stored |
| wrapped file key | key3 encrypted with the wrapping key. It is ciphertext, not a usable key | AES-256-GCM | Kept with the vault | `manifest.json` |

#### Upload

```text
1. key3 = 32 random bytes                                   (the data key)
2. Every chunk is encrypted with key3 using AES-256-GCM.
   Each chunk gets a fresh random nonce, and its 128-byte header is
   authenticated as additional data (AAD).

To protect key3:
3. Create the disposable keypair (key4).
4. shared_secret    = X25519(key4_private, key2)
5. wrapping_key     = HKDF-SHA256(shared_secret)
6. wrapped_file_key = AES-256-GCM(wrapping_key, key3)
7. Delete key4_private and the wrapping key.
8. manifest.json stores: key4_public, nonce, wrapped_file_key
```

Two public keys cannot produce a shared secret. Step 4 needs one private key and the other side's public key. The disposable private key does that job once and is then discarded.

HKDF is used because the raw X25519 output is not safe to use directly as an AES key.

#### Restore

```text
1. shared_secret    = X25519(key1, key4_public)      (same value as upload step 4)
2. wrapping_key     = HKDF-SHA256(shared_secret)
3. key3             = AES-256-GCM decrypt(wrapping_key, wrapped_file_key)
4. key3 decrypts every chunk
```

#### Why two layers

* AES is fast, so it handles large data. X25519 only protects the small key.
* Each vault has its own key3, so one leaked key exposes one vault.
* Uploading needs only the public key (key2). Only restoring needs the private key (key1).
* The Discord bot token is separate. It grants channel access, not decryption.

Source: `src/crypto.py` (`generate_key`, `wrap_key`, `unwrap_key`, `derive_wrapping_key`), `src/key_manager.py`, and `encode_chunk` / `decode_chunk` in `src/vault.py`. For a full walkthrough, see [`learning/03-key-hierarchy.md`](learning/03-key-hierarchy.md) and [`learning/04-encryption-decryption-flow.md`](learning/04-encryption-decryption-flow.md).

---

## Project Structure

```text
discord-vault/
│
├── src/
│   ├── crypto.py
│   ├── discord_client.py
│   ├── key_manager.py
│   ├── main.py
│   └── vault.py
│
├── tests/
├── data/
│   └── input/
│
├── .discord-vault/
├── restored/
├── .env
├── .gitignore
├── requirements.txt
└── README.md
```

| Module              | Responsibility                          |
| ------------------- | --------------------------------------- |
| `crypto.py`         | Encryption and key wrapping             |
| `key_manager.py`    | Local key management                    |
| `vault.py`          | Encoding, chunking, manifests, decoding |
| `discord_client.py` | Discord API and storage operations      |
| `main.py`           | Command-line interface                  |

---

## Setup

```bash
git clone <repository-url>
cd discord-vault

python -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt
```

Configure the Discord bot:

```env
DISCORD_BOT_TOKEN=your_bot_token
DISCORD_CHANNEL_ID=your_channel_id
```

Generate the local encryption keypair using the project's key-management command.

Run the test suite:

```bash
python -m pytest
```

---

## Security Notes

Discord receives encrypted file data rather than the original plaintext.

However, Discord can still observe some operational metadata, including:

* Attachment sizes
* Timestamps
* Number of attachments
* Vault existence

The current manifest also contains file metadata.

The local private key is required to decrypt the vault.

**Never commit:**

```text
.env
.discord-vault/private.key
data/output/
generated vault data
```

Losing the private key can make encrypted vaults unrecoverable.

---

## Temporary Data

Normal uploads and restores use temporary directories.

```text
Upload:

Input
  ↓
Temporary encrypted vault
  ↓
Discord
  ↓
Temporary vault deleted


Restore:

Discord
  ↓
Temporary encrypted vault
  ↓
Decrypt + verify
  ↓
restored/
  ↓
Temporary vault deleted
```

This prevents encrypted PNG chunks and intermediate files from accumulating in the project directory.

---

## Tests

Run all tests with:

```bash
python -m pytest
```

The test suite covers the core cryptographic, encoding, chunking, and vault functionality.

---

## Future Improvements

* [ ] Encrypted manifests for stronger metadata privacy
* [ ] Resumable uploads/downloads
* [ ] Better Discord rate-limit handling
* [ ] Parallel chunk transfers
* [ ] Compression before encryption
* [ ] Deduplication
* [ ] Incremental backups
* [ ] Additional storage backends
* [ ] Improved progress reporting
* [ ] Vault deletion

---

## Disclaimer

DiscordVault is an experimental project and is not intended to replace dedicated backup or archival-storage systems.

Keep an independent backup of important data and the private encryption key.

## Star History

<a href="https://www.star-history.com/?repos=drunktrader%2Fdiscord-vault&type=date&legend=top-left">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/chart?repos=drunktrader/discord-vault&type=date&theme=dark&legend=top-left" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/chart?repos=drunktrader/discord-vault&type=date&legend=top-left" />
   <img alt="Star History Chart" src="https://api.star-history.com/chart?repos=drunktrader/discord-vault&type=date&legend=top-left" />
 </picture>
</a>
