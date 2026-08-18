import json
from pathlib import Path

from .chunker import CHUNK_SIZE


def create_manifest(
    input_path: str | Path,
    chunks: list[dict],
    output_path: str | Path,
) -> None:

    input_path = Path(input_path)
    output_path = Path(output_path)

    manifest = {
        "version": 1,
        "filename": input_path.name,
        "file_size": input_path.stat().st_size,
        "chunk_size": CHUNK_SIZE,
        "total_chunks": len(chunks),
        "chunks": chunks,
    }

    output_path.write_text(
        json.dumps(manifest, indent=4)
    )