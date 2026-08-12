"""PostgreSQL repository for playback history."""

from __future__ import annotations

from typing import Any

from peacemusic.infrastructure.persistence.database import PostgresDatabase
from peacemusic.modules.history.models import PlaybackHistoryEntry
from peacemusic.modules.music.models import Track


class PostgresPlaybackHistoryRepository:
    def __init__(self, database: PostgresDatabase) -> None:
        self._database = database

    async def record(self, guild_id: int, track: Track) -> PlaybackHistoryEntry:
        async with self._database.acquire() as connection:
            row = await connection.fetchrow(
                """
                INSERT INTO play_history
                    (guild_id, title, source_url, requested_by, duration)
                VALUES ($1, $2, $3, $4, $5)
                RETURNING id, guild_id, title, source_url, requested_by,
                          played_at, duration
                """,
                guild_id,
                track.title,
                track.source_url,
                track.requested_by,
                track.duration,
            )
        return self._entry(row)

    async def recent(self, guild_id: int, limit: int) -> list[PlaybackHistoryEntry]:
        async with self._database.acquire() as connection:
            rows = await connection.fetch(
                """
                SELECT id, guild_id, title, source_url, requested_by,
                       played_at, duration
                  FROM play_history
                 WHERE guild_id = $1
                 ORDER BY played_at DESC, id DESC
                 LIMIT $2
                """,
                guild_id,
                limit,
            )
        return [self._entry(row) for row in rows]

    @staticmethod
    def _entry(row: Any) -> PlaybackHistoryEntry:
        return PlaybackHistoryEntry(
            id=row["id"],
            guild_id=row["guild_id"],
            title=row["title"],
            source_url=row["source_url"],
            requested_by=row["requested_by"],
            played_at=row["played_at"],
            duration=row["duration"],
        )
