import pytest

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey,
)

from src.crypto import (
    generate_key,
    unwrap_key,
    wrap_key,
)
from src.key_manager import (
    load_private_key,
    load_public_key,
)


def test_key_wrap_roundtrip():
    file_key = generate_key()

    public_key = load_public_key()
    private_key = load_private_key()

    envelope = wrap_key(
        file_key,
        public_key,
    )

    recovered_key = unwrap_key(
        envelope,
        private_key,
    )

    assert recovered_key == file_key


def test_wrong_private_key_cannot_unwrap():
    file_key = generate_key()

    public_key = load_public_key()

    envelope = wrap_key(
        file_key,
        public_key,
    )

    wrong_private_key = (
        X25519PrivateKey.generate()
    )

    with pytest.raises(InvalidTag):
        unwrap_key(
            envelope,
            wrong_private_key,
        )


def test_wrapping_is_randomized():
    file_key = generate_key()

    public_key = load_public_key()

    envelope_1 = wrap_key(
        file_key,
        public_key,
    )

    envelope_2 = wrap_key(
        file_key,
        public_key,
    )

    assert (
        envelope_1["ephemeral_public_key"] != envelope_2["ephemeral_public_key"]
    )

    assert (
        envelope_1["nonce"] != envelope_2["nonce"]
    )

    assert (
        envelope_1["encrypted_file_key"] != envelope_2["encrypted_file_key"]
    )