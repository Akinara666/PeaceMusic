from __future__ import annotations

import asyncio
import logging
import mimetypes
import os
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Tuple

import discord
from google.genai import types

if TYPE_CHECKING:  # pragma: no cover - imported for type hints only
    from google import genai

logger = logging.getLogger(__name__)


def resolve_attachment_content_type(attachment: discord.Attachment) -> str:
    """Best-effort MIME type for an attachment, inferring from the filename
    when Discord does not provide ``content_type``."""
    content_type = (getattr(attachment, "content_type", None) or "").lower().strip()
    if content_type:
        return content_type

    filename = Path(getattr(attachment, "filename", "")).name
    guessed, _ = mimetypes.guess_type(filename)
    return (guessed or "").lower()


class AttachmentProcessor:
    """Convert Discord attachments into Gemini-friendly content."""

    def __init__(
        self,
        client: "genai.Client",
        image_name: Path,
        video_name: Path,
        *,
        max_bytes: int = 25_000_000,
        max_count: int = 4,
    ) -> None:
        self._client = client
        self._image_name = image_name
        self._video_name = video_name
        self._max_bytes = max_bytes
        self._max_count = max_count

    async def to_content(
        self,
        message: discord.Message,
        prompt_text: str,
        raw_text: str,
    ) -> Tuple[types.Content, str]:
        clean_raw_text = raw_text.strip()
        file_parts: list[types.Part] = []
        attachment_markers: list[str] = []
        prompt_markers: list[str] = []

        attachments = list(message.attachments[: self._max_count])
        for attachment in attachments:
            content_type = self._resolve_content_type(attachment)
            marker = self._build_marker(attachment, content_type)
            attachment_markers.append(marker)

            size = int(getattr(attachment, "size", 0) or 0)
            if size > self._max_bytes:
                logger.warning(
                    "Ignoring oversized attachment %s (%d bytes; limit=%d)",
                    getattr(attachment, "filename", "<unknown>"),
                    size,
                    self._max_bytes,
                )
                prompt_markers.append(f"{marker} [too large to process]")
                continue

            if self._media_kind(content_type) is None:
                prompt_markers.append(marker)
                continue

            try:
                file = await self._upload_attachment(attachment, content_type)
            except Exception:  # noqa: BLE001 - degrade gracefully to text-only context
                logger.exception(
                    "Failed to upload attachment %s",
                    getattr(attachment, "filename", "<unknown>"),
                )
                prompt_markers.append(marker)
                continue

            file_parts.append(
                types.Part.from_uri(
                    file_uri=file.uri,
                    mime_type=file.mime_type or content_type or None,
                )
            )

        skipped_count = max(0, len(message.attachments) - len(attachments))
        if skipped_count:
            marker = f"[{skipped_count} additional attachment(s) omitted]"
            attachment_markers.append(marker)
            prompt_markers.append(marker)

        if not clean_raw_text:
            prompt_markers = attachment_markers

        prompt_payload = prompt_text
        if prompt_markers:
            prompt_payload = f"{prompt_text} {' '.join(prompt_markers)}"

        memory_text = clean_raw_text
        if attachment_markers:
            attachment_block = "\n".join(attachment_markers)
            memory_text = (
                f"{clean_raw_text}\n{attachment_block}"
                if clean_raw_text
                else attachment_block
            )

        parts = [*file_parts, types.Part.from_text(text=prompt_payload)]
        return types.Content(role="user", parts=parts), memory_text or "[Attachment]"

    def _resolve_content_type(self, attachment: discord.Attachment) -> str:
        return resolve_attachment_content_type(attachment)

    def _media_kind(self, content_type: str) -> str | None:
        if content_type.startswith("image/"):
            return "image"
        if content_type.startswith("video/"):
            return "video"
        return None

    def _build_marker(self, attachment: discord.Attachment, content_type: str) -> str:
        filename = Path(getattr(attachment, "filename", "")).name or "attachment"
        media_kind = self._media_kind(content_type)
        if media_kind == "image":
            return f"[Image attachment: {filename}]"
        if media_kind == "video":
            return f"[Video attachment: {filename}]"
        return f"[Attachment: {filename}]"

    async def _upload_attachment(
        self, attachment: discord.Attachment, content_type: str
    ) -> types.File:
        downloaded_path = await self._download_attachment(attachment, content_type)
        try:
            uploaded_file = await self._client.aio.files.upload(file=downloaded_path)
        finally:
            await asyncio.to_thread(downloaded_path.unlink, True)
        return await self._wait_for_file(uploaded_file.name)

    async def _download_attachment(
        self, attachment: discord.Attachment, content_type: str
    ) -> Path:
        filename = Path(getattr(attachment, "filename", "")).name
        suffix = Path(filename).suffix or mimetypes.guess_extension(content_type) or ""
        file_descriptor, temp_name = tempfile.mkstemp(
            prefix="gemini_attachment_",
            suffix=suffix,
        )
        os.close(file_descriptor)
        target = Path(temp_name)

        try:
            # Attachment.save streams the response into the file and avoids holding
            # the whole Discord upload in memory. Prefer it over read() whenever the
            # real discord.py object (or a compatible test double) provides it.
            saver = getattr(attachment, "save", None)
            if callable(saver):
                try:
                    await saver(target, use_cached=True)
                except TypeError:
                    await saver(target)
                if target.stat().st_size > self._max_bytes:
                    raise ValueError(
                        f"Attachment exceeds {self._max_bytes} byte processing limit"
                    )
                return target

            reader = getattr(attachment, "read", None)
            if callable(reader):
                try:
                    data = await reader(use_cached=True)
                except TypeError:
                    data = await reader()
                if len(data) > self._max_bytes:
                    raise ValueError(
                        f"Attachment exceeds {self._max_bytes} byte processing limit"
                    )
                await asyncio.to_thread(target.write_bytes, data)
                return target
        except Exception:
            await asyncio.to_thread(target.unlink, True)
            raise

        await asyncio.to_thread(target.unlink, True)
        raise TypeError("Attachment object does not support read() or save()")

    async def _wait_for_file(
        self, file_name: str, *, max_attempts: int = 60, poll_interval: float = 1.0
    ) -> types.File:
        # Bounded poll loop: a file stuck in PROCESSING on Gemini's side must not
        # block forever, because this is awaited inside the per-channel lock.
        for _ in range(max_attempts):
            file = await self._client.aio.files.get(name=file_name)
            state = getattr(file.state, "name", "")
            if state == "ACTIVE":
                return file
            if state != "PROCESSING":
                raise RuntimeError(f"File {file_name} failed with state {state}")
            await asyncio.sleep(poll_interval)
        raise RuntimeError(
            f"File {file_name} still PROCESSING after "
            f"{max_attempts * poll_interval:.0f}s; giving up"
        )
