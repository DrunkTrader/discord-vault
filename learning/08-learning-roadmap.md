# 08. Learning Roadmap

A study path that follows this codebase. Each stage names the files to read, a hands-on exercise, and a checkpoint. Run exercises in a scratch copy or a temporary directory, never against real data. The other documents in this folder are the reference: [00](00-project-overview.md) through [07](07-security-audit.md).

## Prerequisites

- Python: bytes vs str, `struct`, context managers, `pathlib`.
- Basic modular arithmetic idea (what "mod" means). Not required in depth.
- Comfort with a terminal and virtualenvs.

## Stage 1: Architecture (read [01](01-architecture.md))

- Read `src/main.py`, then follow one command into `vault.py`.
- **Exercise:** draw the call graph for `upload` by hand, then compare with [06](06-function-reference.md).
- **Checkpoint:** which module never imports crypto? Why is that good?

## Stage 2: Encoding vs hashing vs encryption ([02](02-cryptography-fundamentals.md) intro)

- **Exercise:** in a Python shell, base64-encode a string, SHA-256 it, and AES-GCM encrypt it with `src/crypto.py`. Reverse each without a key and note which ones you can.
- **Checkpoint:** why can someone un-base64 your manifest fields but not decrypt the chunk?

## Stage 3: Randomness and keys ([03](03-key-hierarchy.md))

- **Exercise:** list every key from the inventory and label it DEK, KEK or master key.
- **Checkpoint:** which key would you back up first, and why is there no way to rebuild it?

## Stage 4: Authenticated encryption ([02](02-cryptography-fundamentals.md) sections 2 and 7)

- **Exercise:** encrypt a message with `encrypt`, flip one bit, observe `InvalidTag`. Then flip a bit of the AAD only.
- **Exercise:** read the tamper tests in `tests/test_vault.py` and predict which exception each one expects before running them.
- **Checkpoint:** what does AAD protect that the ciphertext tag alone would not?

## Stage 5: Key agreement and key derivation ([02](02-cryptography-fundamentals.md) sections 3 to 5)

- **Exercise:** with the `cryptography` library, make two X25519 keypairs and show `a.exchange(B) == b.exchange(A)`. Then run HKDF on it with two different `info` strings and compare the outputs.
- **Checkpoint:** why does restore need the ephemeral *public* key from the manifest?

## Stage 6: The full flow ([04](04-encryption-decryption-flow.md), [05](05-application-workflow.md))

- **Exercise:** use `encode` and `decode` on a 10 MB file in a temp directory. Open one `chunk_000000.png`, note it looks like noise. Compute the expected number of chunks and compare with `manifest.json`.
- **Exercise:** edit `total_chunks` in a copy of the manifest and observe which check fails.
- **Checkpoint:** list the checks that run, in order, when a chunk is swapped from another vault.

## Stage 7: Threat modelling ([07](07-security-audit.md))

- **Exercise:** for each finding, decide who the attacker is and what they need. Pay special attention to F1: why does it need the public key?
- **Exercise (practice, on a copy):** write a failing test for the filename traversal case, then a fix. Do not push it into the documentation branch.
- **Checkpoint:** which findings are design limits and which are bugs?

## Stage 8: Beyond this project

Topics that DiscordVault does not cover, in a sensible order:

1. Password-based key derivation: scrypt, Argon2id, and why HKDF is not enough for passwords.
2. Digital signatures: Ed25519, how they fix F2.
3. HPKE (RFC 9180) and the `age` file format, as polished versions of what `wrap_key` does.
4. Streaming AEAD designs (STREAM construction, `age` payload format) as an alternative to independent chunks.
5. Key management: OS keyrings, hardware tokens, envelope encryption with a KMS.
6. Content-defined chunking, deduplication and their privacy trade-offs.

## Knowledge checkpoints

You understand the project when you can answer these without notes:

1. Which key encrypts the data and which protects that key?
2. How many AES-GCM operations run for a 14 MB file?
3. What does each of GCM, HKDF, X25519 and SHA-256 contribute?
4. What exactly is authenticated by the chunk header, and what does that prevent?
5. What can Discord see? What can someone who steals `private.key` see?
6. Name three weaknesses and how you would fix each.

## Further reading

- NIST SP 800-38D (GCM), RFC 7748 (X25519), RFC 5869 (HKDF), RFC 9180 (HPKE).
- The `cryptography` library documentation for AESGCM, X25519 and HKDF.
- "Cryptography Engineering" (Ferguson, Schneier, Kohno) and "Serious Cryptography" (Aumasson).
