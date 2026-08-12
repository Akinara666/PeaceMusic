from __future__ import annotations

import asyncio

import pytest

from peacemusic.core.errors import ResourceNotFoundError, ValidationError
from peacemusic.infrastructure.persistence.repositories.in_memory_playlists import (
    InMemoryPlaylistRepository,
)
from peacemusic.modules.music.models import ResolvedMedia
from peacemusic.modules.music.permissions import (
    AllowAllPermissionService,
    MusicRequestContext,
)
from peacemusic.modules.music.player_manager import GuildPlayerManager
from peacemusic.modules.music.service import MusicService
from peacemusic.modules.playlists.service import PlaylistService


class Resolver:
    async def resolve(self, query: str) -> ResolvedMedia:
        return ResolvedMedia(
            title=query,
            source_url=f"https://example.test/{query}",
            duration=120,
        )


def _services() -> tuple[PlaylistService, MusicService]:
    music = MusicService(GuildPlayerManager(), Resolver(), AllowAllPermissionService())
    playlists = PlaylistService(InMemoryPlaylistRepository(), music)
    return playlists, music


def test_playlist_lifecycle_and_shared_playback_service() -> None:
    async def scenario() -> None:
        playlists, music = _services()
        context = MusicRequestContext(guild_id=1, user_id=2)

        await playlists.create(context, "Favorites")
        await playlists.add(context, "favorites", "Track A")
        await playlists.add(context, "Favorites", "Track B")
        removed = await playlists.remove(context, "Favorites", 0)

        assert removed.title == "Track A"
        assert await playlists.play(context, "Favorites") == 1
        assert (await music.player_state(context.guild_id)).current_track.title == (
            "Track B"
        )

    asyncio.run(scenario())


def test_playlist_validates_ownership_and_size() -> None:
    async def scenario() -> None:
        playlists, _ = _services()
        owner = MusicRequestContext(guild_id=1, user_id=2)
        other_user = MusicRequestContext(guild_id=1, user_id=3)
        await playlists.create(owner, "Favorites")

        with pytest.raises(ResourceNotFoundError):
            await playlists.delete(other_user, "Favorites")

        limited = PlaylistService(
            InMemoryPlaylistRepository(), _services()[1], max_playlist_size=1
        )
        await limited.create(owner, "One")
        await limited.add(owner, "One", "Track A")
        with pytest.raises(ValidationError, match="maximum size"):
            await limited.add(owner, "One", "Track B")

    asyncio.run(scenario())
