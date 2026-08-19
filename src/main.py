import argparse
import os
import tempfile
import json
from pathlib import Path

from .discord_client import (DiscordClient, DiscordError,)
from .vault import decode_file, encode_file

def get_channel_id() -> str:
    channel_id = os.getenv("DISCORD_CHANNEL_ID")

    if not channel_id:
        raise RuntimeError(
            "DISCORD_CHANNEL_ID is not set"
        )

    return channel_id


def cmd_encode(args):
    encode_file(
        Path(args.input),
        Path(args.output),
    )


def cmd_decode(args):
    decode_file(
        Path(args.input),
        Path(args.output),
    )


def cmd_upload(args):

    client = DiscordClient()
    channel_id = get_channel_id()

    source = Path(args.input)

    if not source.exists():
        raise FileNotFoundError(source)

    with tempfile.TemporaryDirectory(
        prefix="discord-vault-"
    ) as temp_dir:

        vault_dir = Path(temp_dir) / "vault"

        print(
            f"Encrypting: {source}"
        )

        encode_file(
            source,
            vault_dir,
        )

        print()
        print("Uploading vault...")

        client.upload_vault(
            vault_dir,
            channel_id,
        )

        print()
        print("Local encrypted data removed.")


def cmd_list(args):

    client = DiscordClient()

    channel_id = get_channel_id()

    vaults = client.list_vaults(
        channel_id
    )

    if not vaults:
        print("No vaults found.")
        return

    def format_size(
        size: int,
    ) -> str:

        units = [
            "B",
            "KB",
            "MB",
            "GB",
            "TB",
        ]

        value = float(size)

        for unit in units:

            if value < 1024:
                return (
                    f"{value:.2f} {unit}"
                )

            value /= 1024

        return f"{value:.2f} PB"

    print()
    print("Vaults")
    print("─" * 64)

    for index, vault in enumerate(
        vaults,
        start=1,
    ):

        print()
        print(
            f"{index}. "
            f"{vault['filename']}"
        )

        print(
            f"   ID:       "
            f"{vault['vault_id']}"
        )

        print(
            f"   Type:     "
            f"{vault['source_type']}"
        )

        print(
            f"   Size:     "
            f"{format_size(vault['file_size'])}"
        )

        print(
            f"   Chunks:   "
            f"{vault['total_chunks']}"
        )

        print(
            f"   Chunk:    "
            f"{format_size(vault['chunk_size'])}"
        )

        print(
            f"   SHA-256:  "
            f"{vault['file_sha256']}"
        )

    print()

def cmd_download(args):
    client = DiscordClient()

    channel_id = get_channel_id()

    client.download_vault(
        channel_id,
        args.vault_id,
        Path(args.output),
    )

def cmd_restore(args):

    client = DiscordClient()
    channel_id = get_channel_id()

    with tempfile.TemporaryDirectory(
        prefix="discord-vault-restore-"
    ) as temp_dir:

        vault_dir = Path(temp_dir)

        print(
            f"Downloading vault "
            f"{args.vault_id}..."
        )

        try:
            client.download_vault(
                channel_id,
                args.vault_id,
                vault_dir,
            )

        except DiscordError:
            print()
            print(
                f"Error: vault "
                f"'{args.vault_id}' "
                f"was not found."
            )
            return

        manifest_path = (
            vault_dir / "manifest.json"
        )

        try:
            manifest = json.loads(
                manifest_path.read_text()
            )

        except (
            FileNotFoundError,
            json.JSONDecodeError,
        ):
            print()
            print(
                "Error: downloaded vault "
                "has an invalid manifest."
            )
            return

        if args.output:
            output = Path(args.output)

        else:
            output = (
                Path("restored")
                / manifest["filename"]
            )

        print()
        print(
            f"Restoring: "
            f"{manifest['filename']}"
        )

        print(
            f"Output: {output}"
        )

        try:
            decode_file(
                vault_dir,
                output,
            )

        except Exception as error:
            print()
            print(
                f"Error: restore failed: "
                f"{error}"
            )
            return

        print()
        print("Restore complete.")
        print(
            f"Restored to: {output}"
        )

    print(
        "Temporary encrypted data removed."
    )
    
def main():

    parser = argparse.ArgumentParser(
        prog="discord-vault",
        description=(
            "Encrypted file storage using "
            "Discord as the storage backend."
        ),
    )

    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
    )

    # ======================================================
    # encode
    # ======================================================

    encode_parser = subparsers.add_parser(
        "encode",
        help="Encrypt and encode a file",
    )

    encode_parser.add_argument(
        "input",
        help="Input file",
    )

    encode_parser.add_argument(
        "output",
        help="Output vault directory",
    )

    encode_parser.set_defaults(
        func=cmd_encode
    )

    # ======================================================
    # decode
    # ======================================================

    decode_parser = subparsers.add_parser(
        "decode",
        help="Decode and decrypt a vault",
    )

    decode_parser.add_argument(
        "input",
        help="Vault directory",
    )

    decode_parser.add_argument(
        "output",
        help="Recovered file",
    )

    decode_parser.set_defaults(
        func=cmd_decode
    )

    # ======================================================
    # upload
    # ======================================================

    upload_parser = subparsers.add_parser(
        "upload",
        help="Upload a vault to Discord",
    )

    upload_parser.add_argument(
        "input",
        help="File or folder to encrypt and upload",
    )

    upload_parser.set_defaults(
        func=cmd_upload
    )

    # ======================================================
    # list
    # ======================================================

    list_parser = subparsers.add_parser(
        "list",
        help="List vaults stored on Discord",
    )

    list_parser.set_defaults(
        func=cmd_list
    )

    # ======================================================
    # download
    # ======================================================

    download_parser = subparsers.add_parser(
        "download",
        help="Download a vault from Discord",
    )

    download_parser.add_argument(
        "vault_id",
        help="Vault ID",
    )

    download_parser.add_argument(
        "output",
        help="Output directory",
    )

    download_parser.set_defaults(
        func=cmd_download
    )
    
    # ======================================================
    # restore
    # ======================================================
    
    restore_parser = subparsers.add_parser(
        "restore",
        help="Download and restore a vault",
    )

    restore_parser.add_argument(
        "vault_id",
        help="Vault ID",
    )

    restore_parser.add_argument(
        "output",
        nargs="?",
        help="Optional output path",
    )

    restore_parser.set_defaults(
        func=cmd_restore
    )

    # ======================================================
    # execute
    # ======================================================

    args = parser.parse_args()

    args.func(args)


if __name__ == "__main__":
    main()