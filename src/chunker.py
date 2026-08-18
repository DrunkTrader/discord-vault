from pathlib import Path
import hashlib

from .pixel_codec import PAYLOAD_CAPACITY


CHUNK_SIZE = PAYLOAD_CAPACITY


def calculate_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def chunk_file(
    input_path: str | Path,
    output_dir: str | Path,
) -> list[dict]:

    input_path = Path(input_path)
    output_dir = Path(output_dir)

    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    file_size = input_path.stat().st_size

    total_chunks = (
        file_size + CHUNK_SIZE - 1
    ) // CHUNK_SIZE

    chunks = []

    with input_path.open("rb") as file:

        for index in range(total_chunks):

            data = file.read(CHUNK_SIZE)

            if not data:
                break

            chunk_path = (
                output_dir
                / f"chunk_{index:06d}.bin"
            )

            chunk_path.write_bytes(data)

            chunks.append(
                {
                    "index": index,
                    "size": len(data),
                    "sha256": calculate_sha256(data),
                    "path": str(chunk_path),
                }
            )

    return chunks