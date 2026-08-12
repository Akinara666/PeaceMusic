"""Secure attachment preparation independent from Discord and Gemini SDKs."""

from __future__ import annotations

import asyncio
import mimetypes
import tempfile
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from peacemusic.core.errors import ValidationError
from peacemusic.modules.attachments.models import AttachmentInput, PreparedAttachment

Downloader = Callable[[str], Awaitable[bytes]]


class AttachmentService:
    def __init__(
        self,
        *,
        allowed_mime_types: Sequence[str] = (
            "image/jpeg",
            "image/png",
            "image/webp",
            "video/mp4",
            "audio/mpeg",
            "audio/ogg",
            "audio/wav",
        ),
        max_count: int = 4,
        max_bytes: int = 25_000_000,
        download_timeout_seconds: float = 30.0,
    ) -> None:
        if max_count < 1 or max_bytes < 1 or download_timeout_seconds <= 0:
            raise ValueError("Invalid attachment security limits")
        self._allowed = frozenset(allowed_mime_types)
        self._max_count = max_count
        self._max_bytes = max_bytes
        self._timeout = download_timeout_seconds

    def validate(self, attachments: Sequence[AttachmentInput]) -> None:
        if len(attachments) > self._max_count:
            raise ValidationError("Too many attachments")
        for attachment in attachments:
            if attachment.size_bytes < 0 or attachment.size_bytes > self._max_bytes:
                raise ValidationError("Attachment exceeds the configured size limit")
            if attachment.content_type not in self._allowed:
                raise ValidationError("Attachment MIME type is not allowed")

    @asynccontextmanager
    async def prepare(
        self,
        attachments: Sequence[AttachmentInput],
        *,
        downloader: Downloader,
    ) -> AsyncIterator[list[PreparedAttachment]]:
        """Download into a private temporary directory and always clean it up."""

        self.validate(attachments)
        with tempfile.TemporaryDirectory(prefix="peacemusic-attachment-") as raw_dir:
            directory = Path(raw_dir)
            prepared: list[PreparedAttachment] = []
            for attachment in attachments:
                content = await asyncio.wait_for(
                    downloader(attachment.url), self._timeout
                )
                if len(content) > self._max_bytes:
                    raise ValidationError("Downloaded attachment exceeds size limit")
                content_type = attachment.content_type or "application/octet-stream"
                suffix = mimetypes.guess_extension(content_type) or ".bin"
                path = directory / f"{uuid4().hex}{suffix}"
                path.write_bytes(content)
                prepared.append(
                    PreparedAttachment(
                        attachment_id=attachment.attachment_id,
                        filename=attachment.filename,
                        content_type=content_type,
                        path=path,
                        size_bytes=len(content),
                    )
                )
            yield prepared
