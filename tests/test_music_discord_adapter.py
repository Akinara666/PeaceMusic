from __future__ import annotations

import asyncio

from peacemusic.adapters.discord.permissions import DiscordMusicPermissionService
from peacemusic.infrastructure.persistence.repositories.in_memory_dj_roles import (
    InMemoryDJRoleRepository,
)
from peacemusic.infrastructure.persistence.repositories.in_memory_settings import (
    InMemoryGuildSettingsRepository,
)
from peacemusic.adapters.discord.presenters.music import player_embed, track_embed
from peacemusic.modules.music.models import Track
from peacemusic.modules.music.permissions import MusicCapability, MusicRequestContext
from peacemusic.modules.music.player import GuildPlayer
from peacemusic.modules.settings.service import GuildSettingsService


def test_discord_music_permissions_require_shared_voice_channel() -> None:
    async def scenario() -> None:
        service = DiscordMusicPermissionService()
        same_voice = MusicRequestContext(
            guild_id=1,
            user_id=2,
            user_voice_channel_id=3,
            bot_voice_channel_id=3,
        )
        other_voice = MusicRequestContext(
            guild_id=1,
            user_id=2,
            user_voice_channel_id=4,
            bot_voice_channel_id=3,
        )

        assert not await service.allowed(same_voice, MusicCapability.SKIP)
        assert not await service.allowed(other_voice, MusicCapability.SKIP)
        assert await service.allowed(
            MusicRequestContext(guild_id=1, user_id=2, user_voice_channel_id=4),
            MusicCapability.PLAY,
        )
        assert not await service.allowed(other_voice, MusicCapability.PLAY)

        dj_voice = MusicRequestContext(
            guild_id=1,
            user_id=2,
            user_voice_channel_id=3,
            bot_voice_channel_id=3,
            member_role_ids=(10,),
            dj_role_ids=(10,),
        )
        normal_voice = MusicRequestContext(
            guild_id=1,
            user_id=2,
            user_voice_channel_id=3,
            bot_voice_channel_id=3,
        )
        assert await service.allowed(dj_voice, MusicCapability.SKIP)
        assert not await service.allowed(normal_voice, MusicCapability.SKIP)
        assert await service.allowed(normal_voice, MusicCapability.PLAY)

    asyncio.run(scenario())


def test_discord_music_permissions_load_persistent_dj_roles() -> None:
    async def scenario() -> None:
        roles = InMemoryDJRoleRepository()
        await roles.add_role(1, 10, "DJ")
        service = DiscordMusicPermissionService(roles)
        context = MusicRequestContext(
            guild_id=1,
            user_id=2,
            user_voice_channel_id=3,
            bot_voice_channel_id=3,
            member_role_ids=(10,),
        )

        assert await service.allowed(context, MusicCapability.SKIP)
        assert await roles.list_roles(1) == [(10, "DJ")]

        await roles.remove_role(1, 10)
        assert not await service.allowed(context, MusicCapability.SKIP)

    asyncio.run(scenario())


def test_discord_music_permissions_can_be_opened_for_all_voice_members() -> None:
    async def scenario() -> None:
        settings = GuildSettingsService(InMemoryGuildSettingsRepository())
        await settings.update(
            1,
            actor_user_id=99,
            section="music",
            values={"permission_mode": "everyone"},
        )
        service = DiscordMusicPermissionService(settings=settings)
        context = MusicRequestContext(
            guild_id=1,
            user_id=2,
            user_voice_channel_id=3,
            bot_voice_channel_id=3,
        )

        assert await service.allowed(context, MusicCapability.SKIP)

        other_voice = MusicRequestContext(
            guild_id=1,
            user_id=2,
            user_voice_channel_id=4,
            bot_voice_channel_id=3,
        )
        assert not await service.allowed(other_voice, MusicCapability.SKIP)

    asyncio.run(scenario())


def test_music_presenters_render_track_and_player_state() -> None:
    track = Track(
        title="Example",
        source_url="https://example.test",
        requested_by=1,
        webpage_url="https://example.test/watch",
        thumbnail="https://example.test/thumb.jpg",
        uploader="Example Artist",
        duration=125,
    )
    player = GuildPlayer(1)
    player.enqueue(track)

    embed = track_embed(track, queue_position=2)
    assert embed.title == "Example"
    assert embed.url == "https://example.test/watch"
    assert embed.thumbnail.url == "https://example.test/thumb.jpg"
    assert {field.name for field in embed.fields} == {
        "Artist / channel",
        "Duration",
        "Requested by",
        "Queue",
    }
    assert next(field for field in embed.fields if field.name == "Duration").value == (
        "2:05"
    )
    assert "Now playing" in (player_embed(player).description or "")
