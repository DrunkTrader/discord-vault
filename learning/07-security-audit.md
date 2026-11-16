# 07. Security Audit

Scope: `src/` and `requirements.txt` at commit `3acb26a`. Method: reading the source, tracing call paths ([06](06-function-reference.md)), a git-history scan for secrets, running the existing tests, and running `pip-audit` on `requirements.txt`. No application code was changed and the Discord API was never contacted.

Labels: **Confirmed** means the flaw is visible in the code. **Potential** means it depends on conditions I could not verify. Severity is my judgement for a personal-use tool.

## Summary

| ID | Severity | Status | Title |
| --- | --- | --- | --- |
| F1 | Medium | Confirmed code flaw, exploit needs preconditions | Manifest `filename` used as an output path |
| F2 | Medium | Confirmed design gap | No sender authentication, manifest unauthenticated |
| F3 | Medium | Confirmed | Private key stored unencrypted, `chmod` after write |
| F4 | Medium | Confirmed design gap | Plaintext manifest leaks metadata and plaintext hashes |
| F5 | Medium | Potential | No size limits when restoring (ZIP bomb, huge manifest) |
| F6 | Low | Confirmed | Unverified plaintext left at the output path on failure |
| F7 | Low | Confirmed | No timeouts, no 5xx retry, errors flattened, exit code 0 |
| F8 | Needs triage | Confirmed by tool, applicability not verified | 47 known advisories in pinned dependencies |
| F9 | Low | Confirmed hardening gap | Key wrap lacks context binding |
| F10 | Low | Confirmed | Terminal escape injection through `list` |
| F11 | Info | Confirmed | Manifest controls chunk file names |
| F12 | Info | Confirmed | Keys are not wiped from memory |
| F13 | Info | By design | No freshness, rollback or deletion protection |

Negative results (checked and clean) are listed at the end.

---

## F1. Manifest `filename` used as an output path (Medium)

- **Where:** `cmd_restore`, `src/main.py:204-211`: `Path("restored") / manifest["filename"]`. Then `decode_file` runs `output_file.parent.mkdir(parents=True)` (`src/vault.py:767`) and writes to that path (`:788-790`).
- **Evidence:** `Path("restored") / "../../evil"` is `restored/../../evil`. `Path("restored") / "/etc/x"` is `/etc/x` (an absolute right-hand side replaces the left). I ran both. Nothing in the code strips directory parts.
- **Attack scenario:** an attacker posts a vault whose manifest has `"filename": "../../.bashrc"` (or an absolute path) and tricks you into `restore <id>`. The restore would write attacker-chosen content there, subject to your user's permissions.
- **Preconditions (important):** `unwrap_key` runs before `mkdir` and the write (`src/vault.py:735-740`), and fails with `InvalidTag` unless the envelope was wrapped to **your public key**. So the attacker needs write access to the channel **and** your `public.key` bytes. The public key is not secret by design, but it is not published either. A vault from a legitimate but compromised uploader also qualifies.
- **Impact:** arbitrary file write as the current user. The attacker controls both the contents and the "expected" hash, so the final SHA-256 check does not help.
- **Mitigation:** take `Path(manifest["filename"]).name`, reject empty, `.`, `..` and names containing separators, and verify the resolved path stays under `restored/`.

## F2. No sender authentication, unauthenticated manifest (Medium)

- **Where:** design of `wrap_key` (`src/crypto.py:83`): anyone with `public.key` can create a vault you will accept. The manifest has no signature or MAC.
- **Evidence:** `decode_file` trusts `filename`, `source_type`, `chunks[*].image`, sizes and hashes from the manifest after only the GCM checks on chunks (`src/vault.py:681-858`). The manifest's `file_sha256` is attacker-editable, so it only detects accidental damage.
- **Scenario:** a party with channel write access and your public key posts a well-formed forged vault. This is the precondition for F1 and F5.
- **What still holds:** without the file key, an attacker cannot alter chunks undetected. Each header authenticates `file_id`, `chunk_index` and `total_chunks`, and `decode_file` compares them to the manifest. A manifest edited to drop or reorder chunks fails the `total_chunks` / `chunk_index` comparison (`src/vault.py:818-834`).
- **Mitigation:** sign the manifest with an Ed25519 key you keep private, or encrypt and authenticate the manifest under `file_key` and bind it to the chunks.

## F3. Private key stored unencrypted, written before `chmod` (Medium)

- **Where:** `generate_keypair`, `src/key_manager.py:33-48`. `NoEncryption()`, then `write_bytes` (line 44), then `chmod(0o600)` (line 47).
- **Evidence:** between the write and the `chmod` the file has default-umask permissions (often 0644). `KEY_DIR.mkdir` uses default permissions as well.
- **Impact:** any process or user that can read the file gets every vault. On a single-user machine with full-disk encryption this is moderate. Backups, cloud sync of the project folder, or another local user make it worse.
- **Mitigation:** create the file with `os.open(path, O_WRONLY|O_CREAT|O_EXCL, 0o600)`, set the directory to 0700, and consider passphrase protection (scrypt or Argon2id plus AES-GCM) or an OS keyring.

## F4. Plaintext manifest leaks metadata and plaintext hashes (Medium)

- **Where:** `manifest` dict, `src/vault.py:532-587`, uploaded as `manifest.json` (`src/discord_client.py:378-386`).
- **Evidence:** it carries `filename`, `file_size`, `source_type`, `file_sha256`, and per-chunk `sha256` of the **plaintext**.
- **Impact:** anyone with channel access can learn names and sizes, and can test whether you stored a specific known file by hashing it. This is a confirmation-of-file attack, which is a real leak for well-known files.
- **Mitigation:** encrypt the manifest body (keeping only `file_id` and the key envelope in clear), or store only keyed hashes.

## F5. No size limits when restoring (Medium, potential)

- **Where:** `extract_zip_safely` (`src/vault.py:626-662`), `decode_file` (`:664`), `png_to_bytes` (`:194-208`).
- **Evidence:** extraction calls `archive.extract` without checking `info.file_size`, entry count or compression ratio. A decoded chunk is held fully in memory, and the manifest's `file_size` and `total_chunks` are not bounded. The `Image.open` call is guarded by the dimension check but happens after Pillow has parsed the header.
- **Scenario:** a forged vault (F2 preconditions) or an accidentally huge folder expands to fill the disk.
- **Mitigation:** cap total uncompressed size and entry count, check `info.file_size` and the ratio before extraction.

## F6. Unverified plaintext left on failure (Low)

- **Where:** `decode_file`, `src/vault.py:786-790` and `:864-891`. For files, `temp_file = output_file`, written chunk by chunk, with the whole-file hash checked last.
- **Evidence:** if a later chunk or the final hash fails, the earlier (individually authenticated) bytes remain at the destination. The user can mistake a truncated file for a result.
- **Mitigation:** write to `output_file.with_suffix(".part")` and `os.replace` after the final check.

## F7. Robustness and error handling (Low)

- **No timeouts:** `session.request` (`src/discord_client.py:98`), `requests.get` (`:219`, `:649`) have no `timeout`. A stalled connection hangs the CLI forever.
- **Retry limited to 429:** 5xx and connection errors are not retried (`:96-130`).
- **Error flattening:** `cmd_restore` turns every `DiscordError` into "vault not found" (`src/main.py:175-182`), including auth failures and missing chunks.
- **Exit code:** `cmd_restore` returns normally after errors (`:182`, `:202`, `:235`), so scripts see exit 0.
- **Partial uploads:** the manifest is posted first, then chunks. A crash leaves a partial vault. `list` shows it and `restore` fails with `Missing chunk`. No cleanup exists.
- **Cost:** `list` and `restore` fetch the whole channel history every time.
- **Mitigation:** timeouts, backoff on 5xx, specific error messages, non-zero exit codes, upload-then-publish ordering or a final "commit" message.

## F8. Pinned dependencies with known advisories (needs triage)

- **Where:** `requirements.txt`.
- **Evidence:** `pip-audit -r requirements.txt --no-deps` reported **47 known vulnerabilities in 3 packages**: `pillow 12.3.0` (fix listed: 13.0.0), `urllib3 2.7.0` (fix 2.8.0) and `certifi 2026.7.22` (fix 2026.10.18). I did not read each advisory, so I cannot say which affect this code. `cryptography 50.0.0` and `requests 2.34.2` were not flagged.
- **Relevance:** Pillow parses PNGs that come from the Discord channel (`src/vault.py:198`), so decoder bugs are reachable by anyone who can post to the channel. `urllib3` and `certifi` sit under TLS and HTTP.
- **Mitigation:** review the advisories, upgrade the three packages, rerun the tests, and add `pip-audit` to CI. Re-running the audit is advised because advisory data changes.

## F9. Key wrap lacks context binding (Low)

- **Where:** `wrap_key` / `unwrap_key` (`src/crypto.py:111-119`, `:151-156`): AES-GCM with `aad=None`, HKDF with `salt=None` and a fixed `info`.
- **Impact:** no known attack here. Modern designs (HPKE, age) bind the ephemeral public key, recipient public key and a version into the KDF context or AAD, which protects against future protocol mistakes.
- **Mitigation:** pass `ephemeral_public || recipient_public` in HKDF `info` or as AAD.

## F10. Terminal escape injection through `list` (Low)

- **Where:** `list_vaults` copies `manifest["filename"]` and other values straight from downloaded JSON (`src/discord_client.py:664-692`); `cmd_list` prints them (`src/main.py:115-148`).
- **Evidence:** no sanitising. Anyone who can post a message `DiscordVault vault=x type=manifest` with a `manifest.json` attachment can make `list` print arbitrary text, including ANSI escape sequences. No public key is needed for this one.
- **Impact:** misleading output or terminal manipulation.
- **Mitigation:** strip control characters before printing.

## F11. Manifest controls chunk file names (Info)

- **Where:** `image_path = input_dir / chunk_info["image"]` (`src/vault.py:803-806`).
- **Evidence:** a value like `../x.png` makes the code open a PNG outside the vault directory. It would still have to decrypt correctly to be used, so the practical impact is minimal.
- **Mitigation:** require `image` to equal `chunk_%06d.png` for its index.

## F12. Keys are not wiped from memory (Info)

- `file_key`, `wrapping_key` and `shared_secret` are immutable Python `bytes`. They are freed by the garbage collector without zeroing, and could appear in swap or core dumps. Realistic mitigation in Python is limited. Disable core dumps and use encrypted swap if it matters.

## F13. No freshness, rollback or deletion protection (Info)

- Anyone with the bot token or channel permissions can delete or re-post messages. Old vault versions stay valid forever, and there is no version counter. There is no vault-delete command (`delete_message` was never implemented).
- If several messages carry the same `vault=<id>`, the loop keeps the last one it sees. Discord returns newest first, so the oldest message wins (`src/discord_client.py:489-518`). A later duplicate therefore cannot displace the original manifest or chunk. This is a side effect of iteration order, not a designed protection.

---

## Threat model

Assets: file contents (high), filenames and sizes (medium), `private.key` (critical), bot token (medium).

| Actor | Capability | What they get |
| --- | --- | --- |
| Discord staff or a channel member | read all messages | ciphertext, sizes, timestamps, manifests (F4) |
| Channel member with posting rights | add messages | fake vaults, garbled `list` output (F10). With your public key: F1, F2, F5 |
| Holder of the bot token | same as a channel member, plus bot permissions | can delete the stored data |
| Local user on your machine | read files | `.env` (token), `private.key` if readable (F3) |
| Network observer | TLS-protected traffic | traffic volume only |
| Malware as your user | everything above | full compromise |

Out of scope and not defended: Discord's terms of service, durability (Discord can delete content or expire CDN links), traffic analysis, a compromised Python environment.

## Checked and clean (negative findings)

- **Hardcoded secrets:** none in `src/`. A scan of the whole git history found only the placeholder in `.env.example`. No `.env` or key file is tracked.
- **Randomness:** only `secrets`, `uuid4` and the library's key generator. No `random` module.
- **Nonce reuse:** none found. Fresh random 96-bit nonce per chunk and per wrap. Per-vault keys keep the count far below the 2^32 guideline.
- **Authentication tags:** GCM tags are verified on every decrypt. No decrypt-without-verify path exists. No AES-ECB, CBC or custom crypto.
- **Header integrity:** all 128 header bytes are AAD (`src/vault.py:254`, `:321`).
- **Timing:** no secret value is compared with `==`. Hash comparisons are on public values.
- **Token leakage:** the token is only used in the session header (`src/discord_client.py:74-81`). Error messages print the response body and status, not the token.
- **Zip Slip:** the check at `src/vault.py:645-657` is correct for the common `..` case. Symlinks are refused at archive time.
- **Secrets in git:** `.gitignore` covers `.env`, `.discord-vault/`, `*.key`, `*.pem`.

## Recommended order of fixes

1. F1 (sanitise filename). Small and contained.
2. F3 (key permissions and passphrase protection).
3. F8 (dependency upgrades and CI audit).
4. F2 and F4 (encrypt and authenticate the manifest, ideally with a signature).
5. F5, F6, F7 (limits, atomic output, timeouts, exit codes).
6. F9, F10, F11 (hardening).

Next: [08-learning-roadmap.md](08-learning-roadmap.md).
