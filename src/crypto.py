import secrets

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey,
    X25519PublicKey,
)
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


KEY_SIZE = 32
NONCE_SIZE = 12


def generate_key() -> bytes:
    return secrets.token_bytes(KEY_SIZE)


def encrypt(
    data: bytes,
    key: bytes,
    aad: bytes | None = None,
    nonce: bytes | None = None,
) -> tuple[bytes, bytes]:

    if len(key) != KEY_SIZE:
        raise ValueError("Key must be 32 bytes")

    if nonce is None:
        nonce = secrets.token_bytes(NONCE_SIZE)

    if len(nonce) != NONCE_SIZE:
        raise ValueError("Nonce must be 12 bytes")

    aes = AESGCM(key)

    ciphertext = aes.encrypt(
        nonce,
        data,
        aad,
    )

    return ciphertext, nonce


def decrypt(
    ciphertext: bytes,
    key: bytes,
    nonce: bytes,
    aad: bytes | None = None,
) -> bytes:

    if len(key) != KEY_SIZE:
        raise ValueError("Key must be 32 bytes")

    if len(nonce) != NONCE_SIZE:
        raise ValueError("Nonce must be 12 bytes")

    aes = AESGCM(key)

    return aes.decrypt(
        nonce,
        ciphertext,
        aad,
    )


def derive_wrapping_key(
    shared_secret: bytes,
) -> bytes:

    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=KEY_SIZE,
        salt=None,
        info=b"discord-vault-key-wrapping-v1",
    )

    return hkdf.derive(shared_secret)


def wrap_key(
    file_key: bytes,
    recipient_public_key: X25519PublicKey,
) -> dict:

    if len(file_key) != KEY_SIZE:
        raise ValueError(
            "File key must be 32 bytes"
        )

    # Generate a new ephemeral keypair
    # for this particular file key.
    ephemeral_private = X25519PrivateKey.generate()
    ephemeral_public = ephemeral_private.public_key()

    # X25519:
    # ephemeral private + recipient public
    # -> shared secret
    shared_secret = ephemeral_private.exchange(
        recipient_public_key
    )

    # Turn the shared secret into an AES key.
    wrapping_key = derive_wrapping_key(
        shared_secret
    )

    # Encrypt the actual file key.
    nonce = secrets.token_bytes(NONCE_SIZE)

    aes = AESGCM(wrapping_key)

    encrypted_file_key = aes.encrypt(
        nonce,
        file_key,
        None,
    )

    ephemeral_public_bytes = (
        ephemeral_public.public_bytes_raw()
    )

    return {
        "ephemeral_public_key": ephemeral_public_bytes,
        "nonce": nonce,
        "encrypted_file_key": encrypted_file_key,
    }


def unwrap_key(
    envelope: dict,
    recipient_private_key: X25519PrivateKey,
) -> bytes:

    ephemeral_public = (
        X25519PublicKey.from_public_bytes(
            envelope["ephemeral_public_key"]
        )
    )

    shared_secret = recipient_private_key.exchange(
        ephemeral_public
    )

    wrapping_key = derive_wrapping_key(
        shared_secret
    )

    aes = AESGCM(wrapping_key)

    return aes.decrypt(
        envelope["nonce"],
        envelope["encrypted_file_key"],
        None,
    )