import hashlib
from pathlib import Path

from pixel_codec import png_to_bytes


def sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()

    with path.open("rb") as file:
        while chunk := file.read(1024 * 1024):
            hasher.update(chunk)

    return hasher.hexdigest()


def reconstruct(
    output_dir: Path,
    output_file: Path,
) -> None:

    binary_dir = output_dir / "binary"

    png_files = sorted(
        output_dir.glob("chunk_*.png")
    )

    if not png_files:
        raise FileNotFoundError(
            "No PNG chunks found."
        )

    with output_file.open("wb") as output:

        for png_path in png_files:

            index = png_path.stem.split("_")[1]

            binary_path = (
                binary_dir
                / f"chunk_{index}.bin"
            )

            if not binary_path.exists():
                raise FileNotFoundError(
                    f"Missing binary chunk: "
                    f"{binary_path}"
                )

            size = binary_path.stat().st_size

            data = png_to_bytes(
                png_path,
                size,
            )

            output.write(data)

            print(
                f"Decoded chunk {index}: "
                f"{len(data):,} bytes"
            )


def main() -> None:

    output_dir = Path("../data/output")

    original_file = Path(
        "../data/input/test.bin"
    )

    recovered_file = Path(
        "../data/output/recovered.bin"
    )

    reconstruct(
        output_dir,
        recovered_file,
    )

    original_hash = sha256_file(
        original_file
    )

    recovered_hash = sha256_file(
        recovered_file
    )

    print()
    print(f"Original SHA-256:  {original_hash}")
    print(f"Recovered SHA-256: {recovered_hash}")
    print()

    if original_hash == recovered_hash:
        print("SUCCESS: Files are identical.")
    else:
        print("FAILED: Files are different.")


if __name__ == "__main__":
    main()