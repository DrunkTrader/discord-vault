from pathlib import Path

import pytest

from cryptography.exceptions import InvalidTag
from PIL import Image

from src.crypto import generate_key
from src.vault import (
    CHUNK_SIZE,
    HEADER_SIZE,
    ChunkHeader,
    calculate_sha256,
    create_file_id,
    decode_chunk,
    decode_file,
    encode_chunk,
    encode_file,
    pack_header,
    unpack_header,
)


def read_pixels(path: Path) -> bytearray:

    image = Image.open(path).convert("RGB")

    return bytearray(
        image.tobytes()
    )


def write_pixels(
    path: Path,
    pixels: bytearray,
) -> None:

    image = Image.frombytes(
        "RGB",
        (1920, 1080),
        bytes(pixels),
    )

    image.save(
        path,
        format="PNG",
    )


# ============================================================
# Header
# ============================================================

def test_header_roundtrip():

    data = b"hello discord vault"

    header = ChunkHeader(
        file_id=create_file_id(),
        chunk_index=7,
        total_chunks=20,
        plaintext_size=len(data),
        nonce=b"123456789012",
        payload_size=len(data) + 16,
        sha256=calculate_sha256(data),
    )

    encoded = pack_header(header)

    assert len(encoded) == HEADER_SIZE

    decoded = unpack_header(encoded)

    assert decoded.file_id == header.file_id
    assert decoded.chunk_index == 7
    assert decoded.total_chunks == 20
    assert decoded.plaintext_size == len(data)
    assert decoded.nonce == header.nonce
    assert decoded.payload_size == len(data) + 16
    assert decoded.sha256 == header.sha256


# ============================================================
# Secure chunk
# ============================================================

def test_secure_chunk_roundtrip(tmp_path: Path):

    original = (
        b"DiscordVault secure chunk test"
        * 10000
    )

    file_id = create_file_id()
    file_key = generate_key()

    image_path = (
        tmp_path / "chunk.png"
    )

    encode_chunk(
        plaintext=original,
        file_id=file_id,
        chunk_index=0,
        total_chunks=1,
        file_key=file_key,
        output_path=image_path,
    )

    header, recovered = decode_chunk(
        image_path,
        file_key,
    )

    assert recovered == original
    assert header.file_id == file_id
    assert header.chunk_index == 0
    assert header.total_chunks == 1
    assert header.plaintext_size == len(original)


def test_wrong_key_fails(tmp_path: Path):

    original = b"Secret data" * 1000

    file_id = create_file_id()

    correct_key = generate_key()
    wrong_key = generate_key()

    image_path = tmp_path / "chunk.png"

    encode_chunk(
        plaintext=original,
        file_id=file_id,
        chunk_index=0,
        total_chunks=1,
        file_key=correct_key,
        output_path=image_path,
    )

    with pytest.raises(InvalidTag):

        decode_chunk(
            image_path,
            wrong_key,
        )


def test_ciphertext_tampering(
    tmp_path: Path,
):

    original = b"Secret data" * 10000

    file_id = create_file_id()
    file_key = generate_key()

    image_path = tmp_path / "chunk.png"

    encode_chunk(
        plaintext=original,
        file_id=file_id,
        chunk_index=0,
        total_chunks=1,
        file_key=file_key,
        output_path=image_path,
    )

    pixels = read_pixels(image_path)

    pixels[HEADER_SIZE] ^= 0x01

    write_pixels(
        image_path,
        pixels,
    )

    with pytest.raises(InvalidTag):

        decode_chunk(
            image_path,
            file_key,
        )


def test_nonce_tampering(
    tmp_path: Path,
):

    original = b"Secret data" * 10000

    file_id = create_file_id()
    file_key = generate_key()

    image_path = tmp_path / "chunk.png"

    encode_chunk(
        plaintext=original,
        file_id=file_id,
        chunk_index=0,
        total_chunks=1,
        file_key=file_key,
        output_path=image_path,
    )

    pixels = read_pixels(image_path)

    # nonce begins at byte 48
    pixels[48] ^= 0x01

    write_pixels(
        image_path,
        pixels,
    )

    with pytest.raises(InvalidTag):

        decode_chunk(
            image_path,
            file_key,
        )


def test_sha256_tampering(
    tmp_path: Path,
):

    original = b"Secret data" * 10000

    file_id = create_file_id()
    file_key = generate_key()

    image_path = tmp_path / "chunk.png"

    encode_chunk(
        plaintext=original,
        file_id=file_id,
        chunk_index=0,
        total_chunks=1,
        file_key=file_key,
        output_path=image_path,
    )

    pixels = read_pixels(image_path)

    # SHA-256 begins at byte 68.
    pixels[68] ^= 0x01

    write_pixels(
        image_path,
        pixels,
    )

    with pytest.raises(InvalidTag):

        decode_chunk(
            image_path,
            file_key,
        )


def test_chunk_index_tampering(
    tmp_path: Path,
):

    original = b"Secret data" * 10000

    file_id = create_file_id()
    file_key = generate_key()

    image_path = tmp_path / "chunk.png"

    encode_chunk(
        plaintext=original,
        file_id=file_id,
        chunk_index=0,
        total_chunks=1,
        file_key=file_key,
        output_path=image_path,
    )

    pixels = read_pixels(image_path)

    # chunk_index begins at byte 24.
    pixels[24] ^= 0x01

    write_pixels(
        image_path,
        pixels,
    )

    with pytest.raises(InvalidTag):

        decode_chunk(
            image_path,
            file_key,
        )


def test_plaintext_size_tampering(
    tmp_path: Path,
):

    original = b"Secret data" * 10000

    file_id = create_file_id()
    file_key = generate_key()

    image_path = tmp_path / "chunk.png"

    encode_chunk(
        plaintext=original,
        file_id=file_id,
        chunk_index=0,
        total_chunks=1,
        file_key=file_key,
        output_path=image_path,
    )

    pixels = read_pixels(image_path)

    # plaintext_size begins at byte 40.
    pixels[40] ^= 0x01

    write_pixels(
        image_path,
        pixels,
    )

    with pytest.raises(InvalidTag):

        decode_chunk(
            image_path,
            file_key,
        )


# ============================================================
# Complete file
# ============================================================

def test_complete_file_roundtrip(
    tmp_path: Path,
):

    original_path = (
        tmp_path / "original.bin"
    )

    vault_dir = (
        tmp_path / "vault"
    )

    recovered_path = (
        tmp_path / "recovered.bin"
    )

    original = (
        b"DiscordVault end-to-end test"
        * 100000
    )

    original_path.write_bytes(
        original
    )

    encode_file(
        original_path,
        vault_dir,
    )

    decode_file(
        vault_dir,
        recovered_path,
    )

    assert recovered_path.read_bytes() == original


def test_chunk_capacity():

    assert CHUNK_SIZE == 6_220_656