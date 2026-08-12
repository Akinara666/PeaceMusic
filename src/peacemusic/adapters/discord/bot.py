"""Discord composition adapter for the incrementally built v2 application."""

from __future__ import annotations

import discord
from discord.ext import commands

from peacemusic.adapters.discord.cogs.music import MusicCog
from peacemusic.adapters.discord.cogs.playlists import PlaylistCog
from peacemusic.adapters.discord.cogs.chat import ChatCog
from peacemusic.adapters.discord.cogs.settings import SettingsCog
from peacemusic.adapters.discord.voice import DiscordVoiceGateway
from peacemusic.adapters.discord.views.player import PlayerView
from peacemusic.bootstrap.container import ApplicationContainer
from peacemusic.infrastructure.media.ffmpeg import FFmpegAudioSourceFactory


class PeaceMusicV2Bot(commands.Bot):
    """Own Discord adapters while application services stay in the container."""

    def __init__(self, container: ApplicationContainer) -> None:
        super().__init__(
            command_prefix=commands.when_mentioned,
            intents=container.settings.discord_intents,
            allowed_mentions=discord.AllowedMentions.none(),
        )
        self.container = container
        self.container.music.attach_runtime(
            voice_gateway=DiscordVoiceGateway(self),
            audio_source_factory=FFmpegAudioSourceFactory(),
        )
        self._ready = False

    @property
    def is_ready_for_health(self) -> bool:
        return self._ready

    async def setup_hook(self) -> None:
        self.add_view(PlayerView(self.container.music))
        await self.add_cog(SettingsCog(self.container.guild_settings))
        await self.add_cog(
            MusicCog(self.container.music, getattr(self.container, "history", None))
        )
        playlist_service = getattr(self.container, "playlists", None)
        if playlist_service is not None:
            await self.add_cog(PlaylistCog(playlist_service))
        await self.add_cog(ChatCog(self.container.agent))
        await self.tree.sync()

    async def on_ready(self) -> None:
        self._ready = True
        self.container.mark_discord_ready(True)

    async def on_disconnect(self) -> None:
        self._ready = False
        self.container.mark_discord_ready(False)
