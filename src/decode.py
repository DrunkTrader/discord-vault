import argparse
import base64
import hashlib
import json
from pathlib import Path

from .crypto import unwrap_key
from .key_manager import load_private_key
from .secure_chunk import decode_chunk


def sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()

    with path.open("rb") as file:
        while chunk := file.read(1024 * 1024):
            hasher.update(chunk)

    return hasher.hexdigest()


def decode(
    input_dir: Path,
    output_file: Path,
) -> None:

    manifest_path = input_dir / "manifest.json"

    if not manifest_path.exists():
        raise FileNotFoundError(
            f"Missing manifest: {manifest_path}"
        )

    manifest = json.loads(
        manifest_path.read_text()
    )

    # --------------------------------------------------
    # Load and validate manifest
    # --------------------------------------------------

    if manifest.get("version") != 1:
        raise ValueError(
            "Unsupported manifest version"
        )

    total_chunks = manifest["total_chunks"]
    expected_file_size = manifest["file_size"]
    expected_file_hash = manifest["file_sha256"]

    file_id = bytes.fromhex(
        manifest["file_id"]
    )

    # --------------------------------------------------
    # Recover the AES file key
    # --------------------------------------------------

    wrapped = manifest["wrapped_file_key"]

    envelope = {
        "ephemeral_public_key": base64.b64decode(
            wrapped["ephemeral_public_key"]
        ),
        "nonce": base64.b64decode(
            wrapped["nonce"]
        ),
        "encrypted_file_key": base64.b64decode(
            wrapped["encrypted_file_key"]
        ),
    }

    private_key = load_private_key()

    file_key = unwrap_key(
        envelope,
        private_key,
    )

    # --------------------------------------------------
    # Decode chunks
    # --------------------------------------------------

    chunks = manifest["chunks"]

    if len(chunks) != total_chunks:
        raise ValueError(
            "Manifest chunk count mismatch"
        )

    output_file.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with output_file.open("wb") as output:

        for expected_index, chunk_info in enumerate(
            chunks
        ):

            index = chunk_info["index"]

            if index != expected_index:
                raise ValueError(
                    f"Unexpected chunk index: {index}"
                )

            image_name = chunk_info["image"]

            image_path = (
                input_dir / image_name
            )

            if not image_path.exists():
                raise FileNotFoundError(
                    f"Missing chunk: {image_path}"
                )

            header, plaintext = decode_chunk(
                image_path,
                file_key,
            )

            # ------------------------------------------
            # Validate header against manifest
            # ------------------------------------------

            if header.file_id != file_id:
                raise ValueError(
                    f"File ID mismatch in chunk {index}"
                )

            if header.chunk_index != index:
                raise ValueError(
                    f"Chunk index mismatch: {index}"
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

            manifest_hash = chunk_info["sha256"]

            actual_hash = hashlib.sha256(
                plaintext
            ).hexdigest()

            if actual_hash != manifest_hash:
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

    # --------------------------------------------------
    # Validate reconstructed file
    # --------------------------------------------------

    actual_size = output_file.stat().st_size

    if actual_size != expected_file_size:
        raise ValueError(
            f"File size mismatch: "
            f"expected {expected_file_size:,}, "
            f"got {actual_size:,}"
        )

    actual_file_hash = sha256_file(
        output_file
    )

    print()
    print(
        f"Expected SHA-256: {expected_file_hash}"
    )
    print(
        f"Actual SHA-256:   {actual_file_hash}"
    )

    if actual_file_hash != expected_file_hash:
        raise ValueError(
            "Final SHA-256 verification failed"
        )

    print()
    print("SUCCESS: File reconstructed.")
    print(f"Output: {output_file}")


def main() -> None:

    parser = argparse.ArgumentParser(
        description="DiscordVault decoder"
    )

    parser.add_argument(
        "input",
        help="Directory containing PNG chunks and manifest",
    )

    parser.add_argument(
        "output",
        help="Recovered output file",
    )

    args = parser.parse_args()

    decode(
        Path(args.input),
        Path(args.output),
    )


if __name__ == "__main__":
    main()