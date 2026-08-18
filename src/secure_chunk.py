from pathlib import Path
import secrets

from .crypto import decrypt, encrypt

from .image_format import (
    HEADER_SIZE,
    ChunkHeader,
    calculate_sha256,
    pack_header,
    unpack_header,
)

from .pixel_codec import (
    IMAGE_CAPACITY,
    bytes_to_png,
    png_to_bytes,
)


GCM_TAG_SIZE = 16


def encode_chunk(
    plaintext: bytes,
    file_id: bytes,
    chunk_index: int,
    total_chunks: int,
    file_key: bytes,
    output_path: str | Path,
) -> None:

    nonce = secrets.token_bytes(12)

    ciphertext_size = (
        len(plaintext) + 16
    )

    plaintext_hash = calculate_sha256(
        plaintext
    )

    header = ChunkHeader(
        file_id=file_id,
        chunk_index=chunk_index,
        total_chunks=total_chunks,
        plaintext_size=len(plaintext),
        nonce=nonce,
        payload_size=ciphertext_size,
        sha256=plaintext_hash,
    )

    header_bytes = pack_header(header)

    ciphertext, returned_nonce = encrypt(
        plaintext,
        file_key,
        aad=header_bytes,
        nonce=nonce,
    )

    if returned_nonce != nonce:
        raise RuntimeError(
            "Encryption nonce mismatch"
        )

    if len(ciphertext) != ciphertext_size:
        raise RuntimeError(
            "Ciphertext size mismatch"
        )

    image_data = (
        header_bytes + ciphertext
    )

    if len(image_data) > IMAGE_CAPACITY:
        raise ValueError(
            f"Chunk is too large for image: "
            f"{len(image_data)} bytes"
        )

    bytes_to_png(
        image_data,
        output_path,
    )


def decode_chunk(
    image_path: str | Path,
    file_key: bytes,
) -> tuple[ChunkHeader, bytes]:

    raw = png_to_bytes(image_path)

    header_bytes = raw[
        :HEADER_SIZE
    ]

    header = unpack_header(
        header_bytes
    )

    ciphertext_start = HEADER_SIZE

    ciphertext_end = (
        ciphertext_start
        + header.payload_size
    )

    ciphertext = raw[
        ciphertext_start:ciphertext_end
    ]

    if len(ciphertext) != header.payload_size:
        raise ValueError(
            "Ciphertext size does not match header"
        )

    plaintext = decrypt(
        ciphertext,
        file_key,
        header.nonce,
        aad=header_bytes,
    )

    if len(plaintext) != header.plaintext_size:
        raise ValueError(
            "Plaintext size does not match header"
        )

    calculated_hash = calculate_sha256(
        plaintext
    )

    if calculated_hash != header.sha256:
        raise ValueError(
            "SHA-256 verification failed"
        )

    return header, plaintext