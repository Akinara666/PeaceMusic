"""Deterministic playback history repository for tests and local development."""

from __future__ import annotations

from datetime import datetime, timezone

from peacemusic.modules.history.models import PlaybackHistoryEntry
from peacemusic.modules.music.models import Track


class InMemoryPlaybackHistoryRepository:
    def __init__(self) -> None:
        self.values: list[PlaybackHistoryEntry] = []
        self._next_id = 1

    async def record(self, guild_id: int, track: Track) -> PlaybackHistoryEntry:
        entry = PlaybackHistoryEntry(
            id=self._next_id,
            guild_id=guild_id,
            title=track.title,
            source_url=track.source_url,
            requested_by=track.requested_by,
            played_at=datetime.now(timezone.utc),
            duration=track.duration,
        )
        self._next_id += 1
        self.values.append(entry)
        return entry

    async def recent(self, guild_id: int, limit: int) -> list[PlaybackHistoryEntry]:
        return [entry for entry in reversed(self.values) if entry.guild_id == guild_id][
            :limit
        ]
