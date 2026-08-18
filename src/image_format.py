import hashlib
import struct
import uuid
from dataclasses import dataclass


MAGIC = b"DVLT"
VERSION = 1

HEADER_SIZE = 128
NONCE_SIZE = 12
GCM_TAG_SIZE = 16
FILE_ID_SIZE = 16
SHA256_SIZE = 32

HEADER_FORMAT = "<4sBBH16sQQQ12sQ32s"

BASE_HEADER_SIZE = struct.calcsize(HEADER_FORMAT)

RESERVED_SIZE = HEADER_SIZE - BASE_HEADER_SIZE

assert BASE_HEADER_SIZE == 100
assert RESERVED_SIZE == 28


@dataclass
class ChunkHeader:
    file_id: bytes
    chunk_index: int
    total_chunks: int
    plaintext_size: int
    nonce: bytes
    payload_size: int
    sha256: bytes


def create_file_id() -> bytes:
    return uuid.uuid4().bytes


def calculate_sha256(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


def pack_header(header: ChunkHeader) -> bytes:
    if len(header.file_id) != FILE_ID_SIZE:
        raise ValueError("file_id must be 16 bytes")

    if len(header.nonce) != NONCE_SIZE:
        raise ValueError("nonce must be 12 bytes")

    if len(header.sha256) != SHA256_SIZE:
        raise ValueError("sha256 must be 32 bytes")

    packed = struct.pack(
        HEADER_FORMAT,
        MAGIC,
        VERSION,
        0,
        HEADER_SIZE,
        header.file_id,
        header.chunk_index,
        header.total_chunks,
        header.plaintext_size,
        header.nonce,
        header.payload_size,
        header.sha256,
    )

    return packed + bytes(RESERVED_SIZE)


def unpack_header(data: bytes) -> ChunkHeader:
    if len(data) < HEADER_SIZE:
        raise ValueError("Data is smaller than header")

    (
        magic,
        version,
        flags,
        header_size,
        file_id,
        chunk_index,
        total_chunks,
        plaintext_size,
        nonce,
        payload_size,
        sha256,
    ) = struct.unpack(
        HEADER_FORMAT,
        data[:BASE_HEADER_SIZE],
    )

    if magic != MAGIC:
        raise ValueError("Invalid magic")

    if version != VERSION:
        raise ValueError(
            f"Unsupported version: {version}"
        )

    if header_size != HEADER_SIZE:
        raise ValueError(
            f"Invalid header size: {header_size}"
        )

    return ChunkHeader(
        file_id=file_id,
        chunk_index=chunk_index,
        total_chunks=total_chunks,
        plaintext_size=plaintext_size,
        nonce=nonce,
        payload_size=payload_size,
        sha256=sha256,
    )