import argparse
import base64
import hashlib
import json
from pathlib import Path

from .chunker import CHUNK_SIZE
from .crypto import generate_key, wrap_key
from .image_format import create_file_id
from .key_manager import load_public_key
from .secure_chunk import encode_chunk


def sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()

    with path.open("rb") as file:
        while chunk := file.read(1024 * 1024):
            hasher.update(chunk)

    return hasher.hexdigest()


def encode(
    input_path: Path,
    output_dir: Path,
) -> None:

    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    file_size = input_path.stat().st_size

    total_chunks = (
        file_size + CHUNK_SIZE - 1
    ) // CHUNK_SIZE

    file_id = create_file_id()

    # One random AES-256 key for this file.
    file_key = generate_key()

    # Protect the AES key using our X25519 public key.
    public_key = load_public_key()

    wrapped_key = wrap_key(
        file_key,
        public_key,
    )

    chunks = []

    with input_path.open("rb") as file:

        for index in range(total_chunks):

            plaintext = file.read(CHUNK_SIZE)

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
                f"Encoded chunk {index + 1}/{total_chunks} "
                f"({len(plaintext):,} bytes)"
            )

    manifest = {
        "version": 1,
        "file_id": file_id.hex(),
        "filename": input_path.name,
        "file_size": file_size,
        "file_sha256": sha256_file(input_path),
        "chunk_size": CHUNK_SIZE,
        "total_chunks": total_chunks,
        "encryption": {
            "algorithm": "AES-256-GCM",
            "key_wrap": "X25519-HKDF-SHA256-AES-256-GCM",
        },
        "wrapped_file_key": {
            "ephemeral_public_key": base64.b64encode(
                wrapped_key["ephemeral_public_key"]
            ).decode("ascii"),
            "nonce": base64.b64encode(
                wrapped_key["nonce"]
            ).decode("ascii"),
            "encrypted_file_key": base64.b64encode(
                wrapped_key["encrypted_file_key"]
            ).decode("ascii"),
        },
        "chunks": chunks,
    }

    manifest_path = output_dir / "manifest.json"

    manifest_path.write_text(
        json.dumps(
            manifest,
            indent=4,
        )
    )

    print()
    print("Encryption complete.")
    print(f"File:       {input_path}")
    print(f"Size:       {file_size:,} bytes")
    print(f"Chunks:     {total_chunks}")
    print(f"Chunk size: {CHUNK_SIZE:,} bytes")
    print(f"Output:     {output_dir}")
    print(f"Manifest:   {manifest_path}")


def main() -> None:

    parser = argparse.ArgumentParser(
        description="DiscordVault"
    )

    parser.add_argument(
        "input",
        help="Input file",
    )

    parser.add_argument(
        "output",
        help="Output directory",
    )

    args = parser.parse_args()

    encode(
        Path(args.input),
        Path(args.output),
    )


if __name__ == "__main__":
    main()