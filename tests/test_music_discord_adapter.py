from __future__ import annotations

import asyncio

from peacemusic.adapters.discord.permissions import DiscordMusicPermissionService
from peacemusic.adapters.discord.presenters.music import player_embed, track_embed
from peacemusic.modules.music.models import Track
from peacemusic.modules.music.permissions import MusicCapability, MusicRequestContext
from peacemusic.modules.music.player import GuildPlayer


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

        assert await service.allowed(same_voice, MusicCapability.SKIP)
        assert not await service.allowed(other_voice, MusicCapability.SKIP)
        assert await service.allowed(
            MusicRequestContext(guild_id=1, user_id=2, user_voice_channel_id=4),
            MusicCapability.PLAY,
        )
        assert not await service.allowed(other_voice, MusicCapability.PLAY)

    asyncio.run(scenario())


def test_music_presenters_render_track_and_player_state() -> None:
    track = Track(title="Example", source_url="https://example.test", requested_by=1)
    player = GuildPlayer(1)
    player.enqueue(track)

    assert track_embed(track).title == "Example"
    assert "Now playing" in (player_embed(player).description or "")
