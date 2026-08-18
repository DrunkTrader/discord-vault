import json
import os
import time
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

load_dotenv()


API_BASE = "https://discord.com/api/v10"

USER_AGENT = (
    "DiscordBot "
    "(https://github.com/DrunkTrader/discord-vault, 0.1.0)"
)

MAX_RETRIES = 5


class DiscordError(Exception):
    """Discord API error."""


class DiscordClient:

    def __init__(
        self,
        token: str | None = None,
    ) -> None:

        self.token = (
            token
            or os.getenv("DISCORD_BOT_TOKEN")
        )

        if not self.token:
            raise ValueError(
                "DISCORD_BOT_TOKEN is not set"
            )

        self.session = requests.Session()

        self.session.headers.update(
            {
                "Authorization": (
                    f"Bot {self.token}"
                ),
                "User-Agent": USER_AGENT,
            }
        )

    # ========================================================
    # HTTP
    # ========================================================

    def _request(
        self,
        method: str,
        endpoint: str,
        **kwargs: Any,
    ) -> requests.Response:

        url = f"{API_BASE}{endpoint}"

        for attempt in range(MAX_RETRIES):

            response = self.session.request(
                method,
                url,
                **kwargs,
            )

            if response.status_code != 429:
                break

            try:
                data = response.json()

                retry_after = float(
                    data["retry_after"]
                )

            except Exception:

                retry_after = float(
                    response.headers.get(
                        "Retry-After",
                        "1",
                    )
                )

            print(
                f"Discord rate limit. "
                f"Retrying in "
                f"{retry_after:.2f}s "
                f"({attempt + 1}/{MAX_RETRIES})"
            )

            time.sleep(retry_after)

        if not response.ok:

            try:
                details = response.json()

            except Exception:
                details = response.text

            raise DiscordError(
                f"Discord API error "
                f"{response.status_code}: "
                f"{details}"
            )

        return response

    # ========================================================
    # Authentication
    # ========================================================

    def get_current_user(self) -> dict:

        response = self._request(
            "GET",
            "/users/@me",
        )

        return response.json()

    # ========================================================
    # Channel
    # ========================================================

    def get_channel(
        self,
        channel_id: str,
    ) -> dict:

        response = self._request(
            "GET",
            f"/channels/{channel_id}",
        )

        return response.json()

    # ========================================================
    # Upload one file
    # ========================================================

    def upload_file(
        self,
        channel_id: str,
        file_path: str | Path,
        message: str | None = None,
    ) -> dict:

        file_path = Path(file_path)

        if not file_path.exists():
            raise FileNotFoundError(
                file_path
            )

        if not file_path.is_file():
            raise ValueError(
                f"Not a file: {file_path}"
            )

        payload = {}

        if message is not None:
            payload["content"] = message

        with file_path.open("rb") as file:

            files = {
                "files[0]": (
                    file_path.name,
                    file,
                    "image/png",
                )
            }

            response = self._request(
                "POST",
                f"/channels/{channel_id}/messages",
                data={
                    "payload_json": json.dumps(
                        payload
                    )
                },
                files=files,
            )

        return response.json()

    # ========================================================
    # Download attachment
    # ========================================================

    def download_attachment(
        self,
        url: str,
        output_path: str | Path,
    ) -> Path:

        output_path = Path(
            output_path
        )

        output_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        response = requests.get(
            url,
            stream=True,
        )

        if not response.ok:
            raise DiscordError(
                f"Attachment download failed: "
                f"{response.status_code}"
            )

        with output_path.open("wb") as file:

            for chunk in response.iter_content(
                chunk_size=1024 * 1024
            ):

                if chunk:
                    file.write(chunk)

        return output_path

    # ========================================================
    # List messages
    # ========================================================

    def _parse_vault_message(
        self,
        content: str,
) -> dict | None:

        if not content.startswith(
            "DiscordVault"
        ):
            return None

        metadata = {}

        for part in content.split():

            if "=" not in part:
                continue

            key, value = part.split(
                "=",
                1,
            )

            metadata[key] = value

        if "vault" not in metadata:
            return None

        if "type" not in metadata:
            return None

        return metadata
    
    def list_messages(
        self,
        channel_id: str,
        limit: int | None = None,
    ) -> list[dict]:

        messages = []
        before = None

        while True:

            page_size = 100

            params = {
                "limit": page_size,
            }

            if before is not None:
                params["before"] = before

            response = self._request(
                "GET",
                f"/channels/{channel_id}/messages",
                params=params,
            )

            page = response.json()

            if not page:
                break

            messages.extend(page)

            # Discord returns newest → oldest.
            # The last message is therefore our
            # pagination cursor.
            before = page[-1]["id"]

            if len(page) < page_size:
                break

            if limit is not None and len(messages) >= limit:
                messages = messages[:limit]
                break

        return messages

    # ========================================================
    # Upload complete vault
    # ========================================================

    def upload_vault(
        self,
        vault_dir: str | Path,
        channel_id: str,
    ) -> list[dict]:

        vault_dir = Path(vault_dir)

        if not vault_dir.is_dir():
            raise FileNotFoundError(
                f"Vault directory not found: "
                f"{vault_dir}"
            )

        manifest_path = (
            vault_dir / "manifest.json"
        )

        if not manifest_path.exists():
            raise FileNotFoundError(
                "manifest.json not found"
            )

        manifest = json.loads(
            manifest_path.read_text()
        )

        file_id = manifest["file_id"]

        messages = []

        # ----------------------------------------------------
        # Upload manifest first
        # ----------------------------------------------------

        print("Uploading manifest...")

        result = self.upload_file(
            channel_id,
            manifest_path,
            message=(
                "DiscordVault "
                f"vault={file_id} "
                "type=manifest"
            ),
        )

        messages.append(result)

        # ----------------------------------------------------
        # Upload chunks
        # ----------------------------------------------------

        chunks = sorted(
            vault_dir.glob(
                "chunk_*.png"
            )
        )

        if len(chunks) != manifest["total_chunks"]:
            raise DiscordError(
                "Number of PNG chunks does not "
                "match manifest"
            )

        for index, chunk_path in enumerate(
            chunks
        ):

            print(
                f"Uploading chunk "
                f"{index + 1}/{len(chunks)}..."
            )

            result = self.upload_file(
                channel_id,
                chunk_path,
                message=(
                    "DiscordVault "
                    f"vault={file_id} "
                    f"type=chunk "
                    f"index={index}"
                ),
            )

            messages.append(result)

        print()
        print(
            f"Uploaded vault {file_id}"
        )
        print(
            f"Files uploaded: "
            f"{len(messages)}"
        )

        return messages

    # ========================================================
    # Download complete vault
    # ========================================================

    def download_vault(
        self,
        channel_id: str,
        file_id: str,
        output_dir: str | Path,
    ) -> Path:

        output_dir = Path(
            output_dir
        )

        output_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        print(
            f"Searching Discord for vault "
            f"{file_id}..."
        )

        messages = self.list_messages(
            channel_id,
            limit=100,
        )

        manifest_attachment = None
        chunk_attachments = {}

        for message in messages:

            content = message.get(
                "content",
                "",
            )

            if (
                f"vault={file_id}"
                not in content
            ):
                continue

            for attachment in message.get(
                "attachments",
                []
            ):

                filename = attachment[
                    "filename"
                ]

                if filename == "manifest.json":

                    manifest_attachment = (
                        attachment
                    )

                elif filename.startswith(
                    "chunk_"
                ) and filename.endswith(
                    ".png"
                ):

                    try:

                        index = int(
                            filename[
                                6:-4
                            ]
                        )

                        chunk_attachments[
                            index
                        ] = attachment

                    except ValueError:
                        continue

        if manifest_attachment is None:
            raise DiscordError(
                f"Manifest for vault "
                f"{file_id} not found"
            )

        # ----------------------------------------------------
        # Download manifest
        # ----------------------------------------------------

        manifest_path = (
            output_dir / "manifest.json"
        )

        print(
            "Downloading manifest..."
        )

        self.download_attachment(
            manifest_attachment["url"],
            manifest_path,
        )

        manifest = json.loads(
            manifest_path.read_text()
        )

        if manifest["file_id"] != file_id:
            raise DiscordError(
                "Downloaded manifest has "
                "unexpected file ID"
            )

        total_chunks = manifest[
            "total_chunks"
        ]

        # ----------------------------------------------------
        # Download chunks
        # ----------------------------------------------------

        for index in range(
            total_chunks
        ):

            attachment = (
                chunk_attachments.get(index)
            )

            if attachment is None:
                raise DiscordError(
                    f"Missing chunk {index}"
                )

            output_path = (
                output_dir
                / f"chunk_{index:06d}.png"
            )

            print(
                f"Downloading chunk "
                f"{index + 1}/{total_chunks}..."
            )

            self.download_attachment(
                attachment["url"],
                output_path,
            )

        print()
        print(
            f"Vault downloaded to "
            f"{output_dir}"
        )

        return output_dir

    # ========================================================
    # Delete message
    # ========================================================

    def delete_message(
        self,
        channel_id: str,
        message_id: str,
    ) -> None:

        self._request(
            "DELETE",
            (
                f"/channels/{channel_id}"
                f"/messages/{message_id}"
            ),
        )
        
    def list_vaults(
        self,
        channel_id: str,
) -> list[str]:

        messages = self.list_messages(
            channel_id
        )

        vaults = set()

        for message in messages:

            metadata = self._parse_vault_message(
                message.get("content", "")
            )

            if metadata is None:
                continue

            if metadata.get("type") != "manifest":
                continue

            vaults.add(
                metadata["vault"]
            )

        return sorted(vaults)