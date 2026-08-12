"""Application service for bounded playback history queries."""

from __future__ import annotations

from peacemusic.core.errors import ValidationError
from peacemusic.modules.history.models import PlaybackHistoryEntry
from peacemusic.modules.history.ports import PlaybackHistoryRepository
from peacemusic.modules.music.models import Track


class PlaybackHistoryService:
    def __init__(
        self, repository: PlaybackHistoryRepository, *, max_query_limit: int = 50
    ) -> None:
        if max_query_limit < 1:
            raise ValueError("max_query_limit must be positive")
        self._repository = repository
        self._max_query_limit = max_query_limit

    async def record(self, guild_id: int, track: Track) -> PlaybackHistoryEntry:
        if guild_id <= 0:
            raise ValidationError("guild_id must be positive")
        return await self._repository.record(guild_id, track)

    async def recent(
        self, guild_id: int, *, limit: int = 10
    ) -> list[PlaybackHistoryEntry]:
        if guild_id <= 0:
            raise ValidationError("guild_id must be positive")
        if limit < 1 or limit > self._max_query_limit:
            raise ValidationError(
                f"history limit must be between 1 and {self._max_query_limit}"
            )
        return await self._repository.recent(guild_id, limit)
