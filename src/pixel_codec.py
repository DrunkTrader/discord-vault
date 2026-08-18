from pathlib import Path

from PIL import Image


IMAGE_WIDTH = 1920
IMAGE_HEIGHT = 1080
CHANNELS = 3

IMAGE_CAPACITY = (
    IMAGE_WIDTH
    * IMAGE_HEIGHT
    * CHANNELS
)

HEADER_SIZE = 128
GCM_TAG_SIZE = 16

PAYLOAD_CAPACITY = (
    IMAGE_CAPACITY
    - HEADER_SIZE
    - GCM_TAG_SIZE
)


def bytes_to_png(
    data: bytes,
    output: str | Path,
) -> None:

    if len(data) > IMAGE_CAPACITY:
        raise ValueError(
            f"Data is too large: {len(data)} bytes "
            f"(maximum {IMAGE_CAPACITY})"
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

    image = image.convert("RGB")

    return image.tobytes()