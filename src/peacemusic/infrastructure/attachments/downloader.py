"""Bounded HTTP downloader for Discord attachments."""

from __future__ import annotations

import httpx

from peacemusic.core.errors import ExternalServiceError


class HttpAttachmentDownloader:
    def __init__(self, *, timeout_seconds: float = 30.0) -> None:
        self._timeout = timeout_seconds

    async def __call__(self, url: str) -> bytes:
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout,
                follow_redirects=False,
            ) as client:
                response = await client.get(url)
                response.raise_for_status()
                return response.content
        except httpx.HTTPError as exc:
            raise ExternalServiceError("Attachment download failed") from exc
