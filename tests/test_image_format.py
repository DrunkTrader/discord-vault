from src.image_format import (
    HEADER_SIZE,
    ChunkHeader,
    calculate_sha256,
    create_file_id,
    pack_header,
    unpack_header,
)


def test_header_roundtrip():

    data = b"hello discord vault"

    header = ChunkHeader(
        file_id=create_file_id(),
        chunk_index=7,
        total_chunks=20,
        plaintext_size=len(data),
        nonce=b"123456789012",
        payload_size=len(data) + 16,
        sha256=calculate_sha256(data),
    )

    encoded = pack_header(header)

    assert len(encoded) == HEADER_SIZE

    decoded = unpack_header(encoded)

    assert decoded.file_id == header.file_id
    assert decoded.chunk_index == 7
    assert decoded.total_chunks == 20
    assert decoded.plaintext_size == len(data)
    assert decoded.nonce == header.nonce
    assert decoded.payload_size == len(data) + 16
    assert decoded.sha256 == header.sha256