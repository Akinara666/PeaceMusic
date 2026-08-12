"""Music infrastructure ports."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from peacemusic.modules.music.models import ResolvedMedia, Track


class MediaResolver(Protocol):
    async def resolve(self, query: str) -> ResolvedMedia:
        """Resolve a search query or trusted URL into playable metadata."""


class AudioSourceFactory(Protocol):
    async def create(self, track: Track) -> object:
        """Create an adapter-owned audio source for a track."""


class VoiceGateway(Protocol):
    async def connect(self, guild_id: int, channel_id: int) -> None:
        """Connect the guild player to a voice channel."""

    async def disconnect(self, guild_id: int) -> None:
        """Disconnect the guild player."""

    async def play(
        self,
        guild_id: int,
        source: object,
        *,
        after: Callable[[Exception | None], None] | None = None,
    ) -> None:
        """Start a source and invoke ``after`` when Discord finishes it."""

    async def pause(self, guild_id: int) -> None:
        """Pause the live voice client."""

    async def resume(self, guild_id: int) -> None:
        """Resume the live voice client."""

    async def stop(self, guild_id: int) -> None:
        """Stop the live voice client."""

    async def set_volume(self, guild_id: int, volume: int) -> None:
        """Apply volume to the active source."""
