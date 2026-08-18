import hashlib
from pathlib import Path

from crypto import (
    decrypt,
    encrypt,
    generate_key,
)


INPUT = Path("../data/input/test.bin")
OUTPUT = Path("../data/output/recovered_crypto.bin")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> None:
    original = INPUT.read_bytes()

    print(
        f"Original size: {len(original):,} bytes"
    )

    original_hash = sha256(original)

    key = generate_key()

    ciphertext, nonce = encrypt(
        original,
        key,
    )

    print(
        f"Ciphertext size: {len(ciphertext):,} bytes"
    )

    recovered = decrypt(
        ciphertext,
        key,
        nonce,
    )

    OUTPUT.write_bytes(recovered)

    recovered_hash = sha256(recovered)

    print(f"Original SHA-256:  {original_hash}")
    print(f"Recovered SHA-256: {recovered_hash}")

    if original_hash == recovered_hash:
        print("SUCCESS: Encryption round-trip passed.")
    else:
        print("FAILED: Data changed.")


if __name__ == "__main__":
    main()