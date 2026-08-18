import argparse

from .vault import (
    decode_file,
    encode_file,
)


def main() -> None:

    parser = argparse.ArgumentParser(
        description="DiscordVault"
    )

    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
    )

    # --------------------------------------------------------
    # encode
    # --------------------------------------------------------

    encode_parser = subparsers.add_parser(
        "encode",
        help="Encrypt a file",
    )

    encode_parser.add_argument(
        "input",
        help="Input file",
    )

    encode_parser.add_argument(
        "output",
        help="Output directory",
    )

    # --------------------------------------------------------
    # decode
    # --------------------------------------------------------

    decode_parser = subparsers.add_parser(
        "decode",
        help="Decrypt a vault",
    )

    decode_parser.add_argument(
        "input",
        help="Vault directory",
    )

    decode_parser.add_argument(
        "output",
        help="Recovered file",
    )

    args = parser.parse_args()

    if args.command == "encode":

        encode_file(
            args.input,
            args.output,
        )

    elif args.command == "decode":

        decode_file(
            args.input,
            args.output,
        )


if __name__ == "__main__":
    main()