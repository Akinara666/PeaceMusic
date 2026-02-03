from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Tuple, TYPE_CHECKING

import discord
import requests
from google.genai import types

if TYPE_CHECKING:  # pragma: no cover - imported for type hints only
    from google import genai


class AttachmentProcessor:
    """Convert Discord attachments into Gemini-friendly content."""

    def __init__(
        self, client: "genai.Client", image_name: Path, video_name: Path
    ) -> None:
        self._client = client
        self._image_name = image_name
        self._video_name = video_name

    async def to_content(
        self,
        message: discord.Message,
        user_text: str,
    ) -> Tuple[types.Content, str]:
        attachment = message.attachments[0]
        content_type = attachment.content_type or ""

        if "image" in content_type:
            file_path = self._image_name
            fallback = (
                f'[Image posted by "{message.author.name}". No caption provided.]'
            )
        elif "video" in content_type:
            file_path = self._video_name
            fallback = (
                f'[Video posted by "{message.author.name}". No caption provided.]'
            )
        else:
            text_content = types.Part.from_text(text=user_text)
            return types.Content(role="user", parts=[text_content]), user_text

        prompt_text = message.content or fallback
        downloaded_path = await self._download_attachment(attachment, file_path)
        uploaded_file = await self._client.aio.files.upload(file=downloaded_path)
        file = await self._wait_for_file(uploaded_file.name)

        parts = [
            types.Part.from_uri(file_uri=file.uri, mime_type=file.mime_type),
            types.Part.from_text(text=prompt_text),
        ]
        content = types.Content(role="user", parts=parts)
        return content, prompt_text

    async def _download_attachment(
        self, attachment: discord.Attachment, target: Path
    ) -> Path:
        def _fetch() -> bytes:
            response = requests.get(attachment.url, timeout=30)
            response.raise_for_status()
            return response.content

        data = await asyncio.to_thread(_fetch)
        await asyncio.to_thread(target.write_bytes, data)
        return target

    async def _wait_for_file(self, file_name: str) -> types.File:
        while True:
            file = await self._client.aio.files.get(name=file_name)
            state = getattr(file.state, "name", "")
            if state == "ACTIVE":
                return file
            if state != "PROCESSING":
                raise RuntimeError(f"File {file_name} failed with state {state}")
            await asyncio.sleep(1)
