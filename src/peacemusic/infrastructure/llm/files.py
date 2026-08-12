"""Port for provider-specific Gemini file uploads."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from peacemusic.modules.attachments.models import PreparedAttachment


@dataclass(frozen=True, slots=True)
class GeminiFileReference:
    name: str
    uri: str
    mime_type: str


class GeminiFileService(Protocol):
    async def upload(self, attachment: PreparedAttachment) -> GeminiFileReference:
        """Upload a prepared file and return a provider reference."""

    async def cleanup(self, provider_reference: GeminiFileReference) -> None:
        """Delete a temporary provider-side file when supported."""
