from __future__ import annotations

import asyncio

import pytest

from peacemusic.core.errors import ValidationError
from peacemusic.infrastructure.persistence.repositories.in_memory_history import (
    InMemoryPlaybackHistoryRepository,
)
from peacemusic.modules.history.service import PlaybackHistoryService
from peacemusic.modules.music.models import ResolvedMedia
from peacemusic.modules.music.permissions import (
    AllowAllPermissionService,
    MusicRequestContext,
)
from peacemusic.modules.music.player_manager import GuildPlayerManager
from peacemusic.modules.music.service import MusicService


class Resolver:
    async def resolve(self, query: str) -> ResolvedMedia:
        return ResolvedMedia(title=query, source_url=f"https://example.test/{query}")


def test_history_is_recorded_by_music_service_and_read_newest_first() -> None:
    async def scenario() -> None:
        repository = InMemoryPlaybackHistoryRepository()
        history = PlaybackHistoryService(repository)
        service = MusicService(
            GuildPlayerManager(),
            Resolver(),
            AllowAllPermissionService(),
            history=history,
        )
        context = MusicRequestContext(guild_id=123, user_id=456)

        await service.play(context, "first")
        await service.play(context, "second")
        entries = await history.recent(123, limit=2)

        assert [entry.title for entry in entries] == ["second", "first"]
        assert entries[0].requested_by == 456
        assert entries[0].source_url == "https://example.test/second"

    asyncio.run(scenario())


def test_history_query_limit_is_bounded() -> None:
    async def scenario() -> None:
        history = PlaybackHistoryService(
            InMemoryPlaybackHistoryRepository(), max_query_limit=5
        )

        with pytest.raises(ValidationError, match="between 1 and 5"):
            await history.recent(123, limit=6)

    asyncio.run(scenario())
