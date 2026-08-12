"""Gemini Files API adapter for prepared local attachments."""

from __future__ import annotations

import asyncio

from peacemusic.core.errors import ExternalServiceError
from peacemusic.infrastructure.llm.files import GeminiFileReference
from peacemusic.modules.attachments.models import PreparedAttachment


class GeminiFilesAdapter:
    """Upload and delete files through the Google GenAI Files API."""

    def __init__(
        self, *, api_key: str, processing_timeout_seconds: float = 60.0
    ) -> None:
        if not api_key or processing_timeout_seconds <= 0:
            raise ValueError("Gemini Files requires an API key and positive timeout")
        self._api_key = api_key
        self._timeout = processing_timeout_seconds

    async def upload(self, attachment: PreparedAttachment) -> GeminiFileReference:
        try:
            from google import genai
        except ImportError as exc:  # pragma: no cover - dependency guard
            raise ExternalServiceError("Gemini Files support is unavailable") from exc

        def upload_file():
            client = genai.Client(api_key=self._api_key)
            return client.files.upload(
                file=str(attachment.path),
                config={"mime_type": attachment.content_type},
            )

        try:
            uploaded = await asyncio.wait_for(
                asyncio.to_thread(upload_file), self._timeout
            )
        except Exception as exc:  # noqa: BLE001 - provider boundary
            raise ExternalServiceError("Gemini file upload failed") from exc
        name = getattr(uploaded, "name", None)
        uri = getattr(uploaded, "uri", None)
        if not isinstance(name, str) or not isinstance(uri, str):
            raise ExternalServiceError("Gemini returned no file reference")
        return GeminiFileReference(name, uri, attachment.content_type)

    async def cleanup(self, provider_reference: GeminiFileReference) -> None:
        try:
            from google import genai
        except ImportError:
            return

        def delete_file() -> None:
            client = genai.Client(api_key=self._api_key)
            client.files.delete(name=provider_reference.name)

        try:
            await asyncio.wait_for(asyncio.to_thread(delete_file), self._timeout)
        except Exception:
            # Cleanup is best-effort; temporary local files are still guaranteed by
            # AttachmentService's context manager.
            return
