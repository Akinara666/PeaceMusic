"""Music infrastructure ports."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from peacemusic.modules.music.models import ResolvedMedia, Track
from peacemusic.modules.music.permissions import MusicRequestContext


class PlayerMessageRepository(Protocol):
    async def get(self, guild_id: int) -> tuple[int, int] | None:
        """Return the persisted ``(channel_id, message_id)`` for a guild."""

    async def save(self, guild_id: int, *, channel_id: int, message_id: int) -> None:
        """Persist the current player message identity for a guild."""


class QueueNotificationPublisher(Protocol):
    async def publish_track_queued(
        self,
        context: "MusicRequestContext",
        track: Track,
        *,
        queue_position: int | None,
        now_playing: bool,
    ) -> None:
        """Publish a user-facing notification after a track enters the queue."""


class MediaResolver(Protocol):
    async def resolve(self, query: str) -> ResolvedMedia:
        """Resolve a search query or trusted URL into playable metadata."""


class AudioSourceFactory(Protocol):
    async def create(self, track: Track, *, start_seconds: int = 0) -> object:
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
