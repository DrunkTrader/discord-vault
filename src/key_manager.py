from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey,
    X25519PublicKey,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent

KEY_DIR = PROJECT_ROOT / ".discord-vault"

PRIVATE_KEY_PATH = KEY_DIR / "private.key"
PUBLIC_KEY_PATH = KEY_DIR / "public.key"


def generate_keypair() -> None:
    if PRIVATE_KEY_PATH.exists():
        raise FileExistsError(
            f"Private key already exists: "
            f"{PRIVATE_KEY_PATH}"
        )

    KEY_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    private_key = X25519PrivateKey.generate()

    public_key = private_key.public_key()

    private_bytes = private_key.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )

    public_bytes = public_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )

    PRIVATE_KEY_PATH.write_bytes(private_bytes)
    PUBLIC_KEY_PATH.write_bytes(public_bytes)

    PRIVATE_KEY_PATH.chmod(0o600)
    PUBLIC_KEY_PATH.chmod(0o644)

    print("Keypair generated.")
    print(f"Private key: {PRIVATE_KEY_PATH}")
    print(f"Public key:  {PUBLIC_KEY_PATH}")


def load_private_key() -> X25519PrivateKey:
    data = PRIVATE_KEY_PATH.read_bytes()

    return X25519PrivateKey.from_private_bytes(data)


def load_public_key() -> X25519PublicKey:
    data = PUBLIC_KEY_PATH.read_bytes()

    return X25519PublicKey.from_public_bytes(data)


def main() -> None:
    generate_keypair()


if __name__ == "__main__":
    main()