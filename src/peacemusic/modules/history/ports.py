"""Persistence ports for playback history."""

from __future__ import annotations

from typing import Protocol

from peacemusic.modules.history.models import PlaybackHistoryEntry
from peacemusic.modules.music.models import Track


class PlaybackHistoryRepository(Protocol):
    async def record(self, guild_id: int, track: Track) -> PlaybackHistoryEntry:
        """Record one accepted track in the guild's playback history."""

    async def recent(self, guild_id: int, limit: int) -> list[PlaybackHistoryEntry]:
        """Return the most recent entries, newest first."""
