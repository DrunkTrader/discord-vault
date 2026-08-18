import hashlib
from pathlib import Path

from pixel_codec import png_to_bytes


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def verify_chunks(output_dir: Path) -> None:
    binary_dir = output_dir / "binary"

    for binary_path in sorted(binary_dir.glob("*.bin")):
        index = binary_path.stem.split("_")[1]

        png_path = output_dir / f"chunk_{index}.png"

        original = binary_path.read_bytes()

        recovered = png_to_bytes(
            png_path,
            len(original),
        )

        original_hash = sha256(original)
        recovered_hash = sha256(recovered)

        if original_hash == recovered_hash:
            print(f"chunk {index}: OK")
        else:
            print(f"chunk {index}: FAILED")


def main() -> None:
    output_dir = Path("../data/output")

    verify_chunks(output_dir)


if __name__ == "__main__":
    main()