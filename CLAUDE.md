# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working in this repository.

DiscordVault encrypts files locally with AES-256-GCM, splits them into chunks, encodes the chunks as lossless PNGs, and stores them as Discord attachments in a bot-owned text channel. Folders are first archived into a temporary ZIP.

## Commands

Python 3.13, virtualenv at `.venv` (already created). Use it explicitly — `python` is not on PATH in this environment.

```bash
.venv/bin/python -m pytest          # full test suite (15 tests)
.venv/bin/python -m pytest tests/test_vault.py -q   # single test file
.venv/bin/python -m pytest tests/test_vault.py::test_header_roundtrip -q   # single test
```

CLI entry point (run from repo root):

```bash
.venv/bin/python -m src.main upload data/input/soloLeveling.mp4   # file or folder
.venv/bin/python -m src.main list                                # list vaults on Discord
.venv/bin/python -m src.main restore <VAULT_ID> [output_path]    # download + restore
.venv/bin/python -m src.main encode input.bin vault/             # local encrypt only
.venv/bin/python -m src.main decode vault/ recovered.bin         # local decrypt only
```

Key management — run once to create the local X25519 keypair:

```bash
.venv/bin/python -m src.key_manager
```

It writes `.discord-vault/private.key` (mode 0600) and `.discord-vault/public.key`. The private key never leaves the machine and is required to decrypt any vault.

Configuration via `.env` (copy from `.env.example`): `DISCORD_BOT_TOKEN`, `DISCORD_CHANNEL_ID`. `python-dotenv` loads `.env` at import time in `discord_client.py`.

## Architecture

`src/` is a package; `main.py` is the CLI dispatcher. Data flows `input → encrypt → chunk → PNG → Discord`, and reverses on restore.

- **`crypto.py`** — primitives. `generate_key` (32-byte AES key), `encrypt`/`decrypt` (AES-256-GCM, 12-byte nonce, optional AAD), `wrap_key`/`unwrap_key` (X25519 ephemeral keypair + HKDF-SHA256 to derive a wrapping key, then AES-256-GCM). Constants: `KEY_SIZE=32`, `NONCE_SIZE=12`.
- **`key_manager.py`** — generates and loads the persistent X25519 keypair from `.discord-vault/`. Raw serialization, no encryption of the private key on disk.
- **`vault.py`** — chunk format and encode/decode. Each chunk is a 128-byte header (`struct` packed, magic `DVLT`, version 1, file_id, chunk index/count, plaintext size, nonce, payload size, SHA-256) followed by AES-GCM ciphertext, the whole thing padded and embedded as a 1920×1080 RGB PNG via PIL. `CHUNK_SIZE` = 6,220,656 bytes. `encode_file` handles files and directories (directories → temp ZIP via `archive_directory`, cleaned up in a `finally`). `decode_file` verifies chunk index order, file_id, sizes, per-chunk SHA-256, and a final full-file SHA-256; directories are extracted with `extract_zip_safely`, which blocks path traversal. `sha256_file` is used for integrity, never for encryption.
- **`discord_client.py`** — `requests`-based Discord bot client. `upload_vault` posts the manifest first (message `DiscordVault vault=<id> type=manifest`), then each `chunk_*.png` (`type=chunk index=N`). `download_vault` paginates the full channel (no page cap) and matches by `vault=<id>` in message content, then downloads manifest and chunks by index. `list_vaults` parses manifest messages and streams each manifest attachment into memory to read metadata. `_request` retries on HTTP 429 using `retry_after`. `DiscordError` is raised on non-OK responses. `get_current_user`, `get_channel`, and `delete_message` are not implemented — nothing calls them.
- **`main.py`** — argparse with `upload`/`list`/`restore`/`encode`/`decode` subcommands. Upload and restore use `tempfile.TemporaryDirectory` so no encrypted intermediates are left on disk. Restore prints a clean `Error: vault '<id>' was not found.` on `DiscordError`.

## Key operational facts

- Secrets live in `.env` and `.discord-vault/` — both are gitignored. Never commit them.
- Tests import `from src.crypto ...`, so run pytest from the repo root.
- The manifest is stored in plaintext on Discord and contains file metadata; see README "Security Notes" for what Discord can observe (attachment sizes, timestamps, count, vault existence).
- `restored/` and `data/output/` are gitignored output locations. `data/input/` is also gitignored — it holds the ~97 MB of sample MP4s used for CLI demos and is not part of the repo.