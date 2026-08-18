import pytest

from cryptography.exceptions import InvalidTag

from src.crypto import (
    decrypt,
    encrypt,
    generate_key,
)


def test_encryption_roundtrip():
    original = (
        b"DiscordVault encryption test"
        * 1000
    )

    key = generate_key()

    ciphertext, nonce = encrypt(
        original,
        key,
    )

    recovered = decrypt(
        ciphertext,
        key,
        nonce,
    )

    assert recovered == original


def test_encryption_changes_data():
    original = b"Hello DiscordVault"

    key = generate_key()

    ciphertext, nonce = encrypt(
        original,
        key,
    )

    assert ciphertext != original
    assert len(nonce) == 12


def test_same_data_gets_different_ciphertext():
    original = b"Same data"

    key = generate_key()

    ciphertext_1, nonce_1 = encrypt(
        original,
        key,
    )

    ciphertext_2, nonce_2 = encrypt(
        original,
        key,
    )

    assert nonce_1 != nonce_2
    assert ciphertext_1 != ciphertext_2


def test_tampering_is_detected():
    original = b"Important secret data"

    key = generate_key()

    ciphertext, nonce = encrypt(
        original,
        key,
    )

    tampered = bytearray(ciphertext)

    tampered[0] ^= 0x01

    tampered = bytes(tampered)

    with pytest.raises(InvalidTag):
        decrypt(
            tampered,
            key,
            nonce,
        )


def test_wrong_key_is_rejected():
    original = b"Secret data"

    key = generate_key()
    wrong_key = generate_key()

    ciphertext, nonce = encrypt(
        original,
        key,
    )

    with pytest.raises(InvalidTag):
        decrypt(
            ciphertext,
            wrong_key,
            nonce,
        )