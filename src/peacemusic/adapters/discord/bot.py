"""Discord composition adapter for the v2 application."""

from __future__ import annotations

import discord
from discord.ext import commands

from peacemusic.adapters.discord.cogs.music import MusicCog
from peacemusic.adapters.discord.cogs.memory import MemoryCog
from peacemusic.adapters.discord.cogs.dj import DJCog
from peacemusic.adapters.discord.cogs.playlists import PlaylistCog
from peacemusic.adapters.discord.cogs.chat import ChatCog
from peacemusic.adapters.discord.cogs.access import AccessCog
from peacemusic.adapters.discord.cogs.settings import SettingsCog
from peacemusic.adapters.discord.context import DiscordSettingsAuthorizer
from peacemusic.adapters.discord.music_notifications import (
    DiscordQueueNotificationPublisher,
)
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
        set_authorizer = getattr(self.container.guild_settings, "set_authorizer", None)
        if set_authorizer is not None:
            set_authorizer(DiscordSettingsAuthorizer(self))
        self.container.music.attach_runtime(
            voice_gateway=DiscordVoiceGateway(self),
            audio_source_factory=FFmpegAudioSourceFactory(),
        )
        attach_notifications = getattr(
            self.container.music, "attach_queue_notification_publisher", None
        )
        if attach_notifications is not None:
            attach_notifications(
                DiscordQueueNotificationPublisher(self, self.container.guild_settings)
            )
        self._ready = False

    @property
    def is_ready_for_health(self) -> bool:
        return self._ready

    async def setup_hook(self) -> None:
        self.add_view(PlayerView(self.container.music))
        await self.add_cog(
            SettingsCog(
                self.container.guild_settings,
                getattr(self.container, "dj_roles", None),
            )
        )
        await self.add_cog(
            MusicCog(
                self.container.music,
                getattr(self.container, "history", None),
                getattr(self.container, "guild_settings", None),
                getattr(self.container, "player_messages", None),
            )
        )
        playlist_service = getattr(self.container, "playlists", None)
        if playlist_service is not None:
            await self.add_cog(PlaylistCog(playlist_service))
        memory_service = getattr(self.container, "memory", None)
        if memory_service is not None:
            await self.add_cog(
                MemoryCog(
                    memory_service,
                    self.container.guild_settings,
                    self.container.agent.clear_conversation,
                )
            )
        dj_roles = getattr(self.container, "dj_roles", None)
        if dj_roles is not None:
            await self.add_cog(DJCog(dj_roles))
        access = getattr(self.container, "access", None)
        if access is not None:
            await self.add_cog(AccessCog(access))
        await self.add_cog(ChatCog(self.container.agent, access))
        await self.tree.sync()

    async def on_ready(self) -> None:
        self._ready = True
        self.container.mark_discord_ready(True)

    async def on_disconnect(self) -> None:
        self._ready = False
        self.container.mark_discord_ready(False)
