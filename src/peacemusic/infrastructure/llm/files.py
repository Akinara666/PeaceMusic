"""Port for provider-specific Gemini file uploads."""

from __future__ import annotations

from typing import Protocol

from peacemusic.modules.attachments.models import PreparedAttachment


class GeminiFileService(Protocol):
    async def upload(self, attachment: PreparedAttachment) -> str:
        """Upload a prepared file and return a provider reference."""

    async def cleanup(self, provider_reference: str) -> None:
        """Delete a temporary provider-side file when supported."""
