import base64
import hashlib
import json
import secrets
import shutil
import struct
import tempfile
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from .crypto import decrypt, encrypt, generate_key, unwrap_key, wrap_key
from .key_manager import load_private_key, load_public_key


# ============================================================
# Constants
# ============================================================

IMAGE_WIDTH = 1920
IMAGE_HEIGHT = 1080
CHANNELS = 3

IMAGE_CAPACITY = (
    IMAGE_WIDTH
    * IMAGE_HEIGHT
    * CHANNELS
)

MAGIC = b"DVLT"
VERSION = 1

HEADER_SIZE = 128
NONCE_SIZE = 12
GCM_TAG_SIZE = 16

FILE_ID_SIZE = 16
SHA256_SIZE = 32

CHUNK_SIZE = (
    IMAGE_CAPACITY
    - HEADER_SIZE
    - GCM_TAG_SIZE
)

HEADER_FORMAT = "<4sBBH16sQQQ12sQ32s"

BASE_HEADER_SIZE = struct.calcsize(
    HEADER_FORMAT
)

RESERVED_SIZE = (
    HEADER_SIZE
    - BASE_HEADER_SIZE
)

assert BASE_HEADER_SIZE == 100
assert RESERVED_SIZE == 28


# ============================================================
# Header
# ============================================================

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
        raise ValueError(
            "Data is smaller than header"
        )

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


# ============================================================
# PNG codec
# ============================================================

def bytes_to_png(
    data: bytes,
    output: str | Path,
) -> None:

    if len(data) > IMAGE_CAPACITY:
        raise ValueError(
            f"Data too large: {len(data)} bytes"
        )

    padded = data + bytes(
        IMAGE_CAPACITY - len(data)
    )

    image = Image.frombytes(
        "RGB",
        (IMAGE_WIDTH, IMAGE_HEIGHT),
        padded,
    )

    image.save(
        output,
        format="PNG",
    )


def png_to_bytes(
    image_path: str | Path,
) -> bytes:

    image = Image.open(image_path)

    if image.size != (
        IMAGE_WIDTH,
        IMAGE_HEIGHT,
    ):
        raise ValueError(
            f"Invalid image size: {image.size}"
        )

    return image.convert("RGB").tobytes()


# ============================================================
# Secure chunk
# ============================================================

def encode_chunk(
    plaintext: bytes,
    file_id: bytes,
    chunk_index: int,
    total_chunks: int,
    file_key: bytes,
    output_path: str | Path,
) -> None:

    nonce = secrets.token_bytes(
        NONCE_SIZE
    )

    ciphertext_size = (
        len(plaintext)
        + GCM_TAG_SIZE
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

    header_bytes = pack_header(
        header
    )

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
            f"Chunk too large: "
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

    raw = png_to_bytes(
        image_path
    )

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


# ============================================================
# File hashing
# ============================================================

def sha256_file(path: Path) -> str:

    hasher = hashlib.sha256()

    with path.open("rb") as file:

        while chunk := file.read(
            1024 * 1024
        ):
            hasher.update(chunk)

    return hasher.hexdigest()

# ============================================================
# Folder archiving
# ============================================================

def archive_directory(
    directory: Path,
    output_zip: Path,
) -> None:
    """Create a ZIP while preserving paths relative to directory."""

    directory = directory.resolve()
    output_zip = output_zip.resolve()

    with zipfile.ZipFile(
        output_zip,
        mode="w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=6,
    ) as archive:

        for path in sorted(directory.rglob("*")):

            if path.is_symlink():
                raise ValueError(
                    f"Symlinks are not supported: {path}"
                )

            if not path.is_file():
                continue

            archive.write(
                path,
                arcname=path.relative_to(directory),
            )

# ============================================================
# Encode complete file
# ============================================================

def encode_file(
    input_path: str | Path,
    output_dir: str | Path,
) -> None:

    input_path = Path(input_path)
    output_dir = Path(output_dir)

    if not input_path.exists():
        raise FileNotFoundError(input_path)

    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    archive_path: Path | None = None
    source_path = input_path
    source_type = "file"

    # --------------------------------------------------------
    # Directory → temporary ZIP
    # --------------------------------------------------------

    if input_path.is_dir():

        source_type = "directory"

        temp_dir = Path(
            tempfile.mkdtemp(
                prefix="discord-vault-"
            )
        )

        archive_path = (
            temp_dir / "archive.zip"
        )

        try:

            archive_directory(
                input_path,
                archive_path,
            )

            source_path = archive_path

            print(
                f"Archived directory: "
                f"{input_path}"
            )

            print(
                f"Archive size: "
                f"{archive_path.stat().st_size:,} bytes"
            )

        except Exception:

            shutil.rmtree(
                temp_dir,
                ignore_errors=True,
            )

            raise

    try:

        file_size = source_path.stat().st_size

        total_chunks = (
            file_size + CHUNK_SIZE - 1
        ) // CHUNK_SIZE

        file_id = create_file_id()

        # One random AES-256 key per vault.
        file_key = generate_key()

        # Wrap AES key using X25519.
        public_key = load_public_key()

        wrapped_key = wrap_key(
            file_key,
            public_key,
        )

        chunks = []

        with source_path.open("rb") as file:

            for index in range(
                total_chunks
            ):

                plaintext = file.read(
                    CHUNK_SIZE
                )

                if not plaintext:
                    break

                png_path = (
                    output_dir
                    / f"chunk_{index:06d}.png"
                )

                encode_chunk(
                    plaintext=plaintext,
                    file_id=file_id,
                    chunk_index=index,
                    total_chunks=total_chunks,
                    file_key=file_key,
                    output_path=png_path,
                )

                chunk_hash = hashlib.sha256(
                    plaintext
                ).hexdigest()

                chunks.append(
                    {
                        "index": index,
                        "size": len(plaintext),
                        "sha256": chunk_hash,
                        "image": png_path.name,
                    }
                )

                print(
                    f"Encoded chunk "
                    f"{index + 1}/{total_chunks} "
                    f"({len(plaintext):,} bytes)"
                )

        manifest = {
            "version": 1,

            "file_id": file_id.hex(),

            "filename": input_path.name,

            "source_type": source_type,

            "archive_format": (
                "zip"
                if source_type == "directory"
                else None
            ),

            "file_size": file_size,

            "file_sha256": sha256_file(
                source_path
            ),

            "chunk_size": CHUNK_SIZE,

            "total_chunks": total_chunks,

            "encryption": {
                "algorithm": "AES-256-GCM",
                "key_wrap": (
                    "X25519-HKDF-SHA256-AES-256-GCM"
                ),
            },

            "wrapped_file_key": {

                "ephemeral_public_key":
                    base64.b64encode(
                        wrapped_key[
                            "ephemeral_public_key"
                        ]
                    ).decode("ascii"),

                "nonce":
                    base64.b64encode(
                        wrapped_key["nonce"]
                    ).decode("ascii"),

                "encrypted_file_key":
                    base64.b64encode(
                        wrapped_key[
                            "encrypted_file_key"
                        ]
                    ).decode("ascii"),
            },

            "chunks": chunks,
        }

        manifest_path = (
            output_dir / "manifest.json"
        )

        manifest_path.write_text(
            json.dumps(
                manifest,
                indent=4,
            )
        )

        print()
        print("Encryption complete.")
        print(f"Input:      {input_path}")
        print(f"Type:       {source_type}")
        print(f"Size:       {file_size:,} bytes")
        print(f"Chunks:     {total_chunks}")
        print(f"Chunk size: {CHUNK_SIZE:,} bytes")
        print(f"Output:     {output_dir}")

    finally:

        if archive_path is not None:

            shutil.rmtree(
                archive_path.parent,
                ignore_errors=True,
            )

# ============================================================
# Decode complete file
# ============================================================

# ============================================================
# Safe ZIP extraction
# ============================================================

def extract_zip_safely(
    archive_path: Path,
    output_dir: Path,
) -> None:
    """Extract ZIP while preventing path traversal."""

    output_dir = output_dir.resolve()

    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    with zipfile.ZipFile(
        archive_path
    ) as archive:

        for info in archive.infolist():

            target = (
                output_dir
                / Path(info.filename)
            ).resolve()

            if (
                target != output_dir
                and output_dir not in target.parents
            ):
                raise ValueError(
                    f"Unsafe ZIP path: "
                    f"{info.filename}"
                )

            archive.extract(
                info,
                output_dir,
            )

def decode_file(
    input_dir: str | Path,
    output_file: str | Path,
) -> None:

    input_dir = Path(input_dir)
    output_file = Path(output_file)

    manifest_path = (
        input_dir / "manifest.json"
    )

    if not manifest_path.exists():
        raise FileNotFoundError(
            f"Missing manifest: {manifest_path}"
        )

    manifest = json.loads(
        manifest_path.read_text()
    )

    if manifest.get("version") != 1:
        raise ValueError(
            "Unsupported manifest version"
        )

    total_chunks = manifest[
        "total_chunks"
    ]

    expected_file_size = manifest[
        "file_size"
    ]

    expected_file_hash = manifest[
        "file_sha256"
    ]

    file_id = bytes.fromhex(
        manifest["file_id"]
    )

    # --------------------------------------------------------
    # Recover AES file key
    # --------------------------------------------------------

    wrapped = manifest[
        "wrapped_file_key"
    ]

    envelope = {
        "ephemeral_public_key":
            base64.b64decode(
                wrapped[
                    "ephemeral_public_key"
                ]
            ),

        "nonce":
            base64.b64decode(
                wrapped["nonce"]
            ),

        "encrypted_file_key":
            base64.b64decode(
                wrapped[
                    "encrypted_file_key"
                ]
            ),
    }

    private_key = load_private_key()

    file_key = unwrap_key(
        envelope,
        private_key,
    )

    # --------------------------------------------------------
    # Decode chunks
    # --------------------------------------------------------

    chunks = manifest["chunks"]

    if len(chunks) != total_chunks:
        raise ValueError(
            "Manifest chunk count mismatch"
        )

    source_type = manifest.get(
    "source_type",
    "file",
    )

    if source_type not in {
        "file",
        "directory",
    }:
        raise ValueError(
            f"Unsupported source type: "
            f"{source_type}"
        )

    output_file.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temp_root = None

    if source_type == "directory":

        temp_root = Path(
            tempfile.mkdtemp(
                prefix="discord-vault-restore-"
            )
        )

        temp_file = (
            temp_root / "restore.zip"
        )

    else:

        temp_file = output_file

    with temp_file.open("wb") as output:

        for expected_index, chunk_info in enumerate(
            chunks
        ):

            index = chunk_info["index"]

            if index != expected_index:
                raise ValueError(
                    f"Unexpected chunk index: {index}"
                )

            image_path = (
                input_dir
                / chunk_info["image"]
            )

            if not image_path.exists():
                raise FileNotFoundError(
                    f"Missing chunk: {image_path}"
                )

            header, plaintext = decode_chunk(
                image_path,
                file_key,
            )

            if header.file_id != file_id:
                raise ValueError(
                    f"File ID mismatch "
                    f"in chunk {index}"
                )

            if header.chunk_index != index:
                raise ValueError(
                    f"Chunk index mismatch "
                    f"in chunk {index}"
                )

            if header.total_chunks != total_chunks:
                raise ValueError(
                    f"Total chunk count mismatch "
                    f"in chunk {index}"
                )

            if len(plaintext) != chunk_info["size"]:
                raise ValueError(
                    f"Chunk size mismatch "
                    f"in chunk {index}"
                )

            actual_hash = hashlib.sha256(
                plaintext
            ).hexdigest()

            if actual_hash != chunk_info["sha256"]:
                raise ValueError(
                    f"SHA-256 mismatch "
                    f"in chunk {index}"
                )

            output.write(plaintext)

            print(
                f"Decoded chunk "
                f"{index + 1}/{total_chunks} "
                f"({len(plaintext):,} bytes)"
            )

    # --------------------------------------------------------
    # Final verification
    # --------------------------------------------------------

    actual_size = temp_file.stat().st_size

    if actual_size != expected_file_size:
        raise ValueError(
            f"File size mismatch: "
            f"expected {expected_file_size:,}, "
            f"got {actual_size:,}"
        )

    actual_hash = sha256_file(
        temp_file
    )

    print()
    print(
        f"Expected SHA-256: "
        f"{expected_file_hash}"
    )

    print(
        f"Actual SHA-256:   "
        f"{actual_hash}"
    )

    if actual_hash != expected_file_hash:
        raise ValueError(
            "Final SHA-256 verification failed"
        )

    if source_type == "directory":

        try:

            extract_zip_safely(
                temp_file,
                output_file,
            )

        finally:

            if temp_root is not None:

                shutil.rmtree(
                    temp_root,
                    ignore_errors=True,
                )

        print()
        print("SUCCESS: Directory restored.")
        print(f"Output: {output_file}")

    else:

        print()
        print("SUCCESS: File reconstructed.")
        print(f"Output: {output_file}")