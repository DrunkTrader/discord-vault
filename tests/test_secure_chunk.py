from pathlib import Path

import pytest

from cryptography.exceptions import InvalidTag
from PIL import Image

from src.crypto import generate_key
from src.image_format import (
    HEADER_SIZE,
    create_file_id,
)
from src.secure_chunk import (
    decode_chunk,
    encode_chunk,
)

def read_pixels(path):
    image = Image.open(path).convert("RGB")
    return bytearray(image.tobytes())

def write_pixels(path, pixels):
    image = Image.frombytes(
        "RGB",
        (1920, 1080),
        bytes(pixels),
    )

    image.save(
        path,
        format="PNG",
    )
    
def test_ciphertext_tampering_is_detected(tmp_path):
    original = b"Secret data" * 10000

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

    pixels = read_pixels(image_path)

    # First byte after the 128-byte header.
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
        
def test_nonce_tampering_is_detected(tmp_path):
    original = b"Secret data" * 10000

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

    pixels = read_pixels(image_path)

    # Header layout:
    #
    # MAGIC             0..3
    # VERSION              4
    # FLAGS                5
    # HEADER_SIZE        6..7
    # FILE_ID            8..23
    # CHUNK_INDEX       24..31
    # TOTAL_CHUNKS      32..39
    # PLAINTEXT_SIZE    40..47
    # NONCE             48..59

    nonce_offset = 48

    pixels[nonce_offset] ^= 0x01

    write_pixels(
        image_path,
        pixels,
    )

    with pytest.raises(InvalidTag):
        decode_chunk(
            image_path,
            file_key,
        )
        
def test_hash_tampering_is_detected(tmp_path):
    original = b"Secret data" * 10000

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

    pixels = read_pixels(image_path)

    # SHA-256 starts at byte 68.
    sha256_offset = 68

    pixels[sha256_offset] ^= 0x01

    write_pixels(
        image_path,
        pixels,
    )

    with pytest.raises(InvalidTag):
        decode_chunk(
            image_path,
            file_key,
        )

def test_plaintext_size_tampering_is_detected(
    tmp_path: Path,
):
    original = b"Secret data" * 10000

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

    pixels = read_pixels(image_path)

    # PLAINTEXT_SIZE starts at byte 40.
    plaintext_size_offset = 40

    pixels[plaintext_size_offset] ^= 0x01

    write_pixels(
        image_path,
        pixels,
    )

    with pytest.raises(InvalidTag):
        decode_chunk(
            image_path,
            file_key,
        )

def test_chunk_index_tampering_is_detected(
    tmp_path: Path,
):
    original = b"Secret data" * 10000

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

    pixels = read_pixels(image_path)

    # CHUNK_INDEX starts at byte 24.
    chunk_index_offset = 24

    pixels[chunk_index_offset] ^= 0x01

    write_pixels(
        image_path,
        pixels,
    )

    with pytest.raises(InvalidTag):
        decode_chunk(
            image_path,
            file_key,
        )

def test_secure_chunk_roundtrip(tmp_path: Path):
    original = (
        b"DiscordVault secure chunk test"
        * 10000
    )

    file_id = create_file_id()
    file_key = generate_key()

    image_path = (
        tmp_path / "chunk_000000.png"
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