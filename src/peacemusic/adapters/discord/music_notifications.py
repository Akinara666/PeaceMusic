"""Discord presentation adapter for music queue notifications."""

from __future__ import annotations

import discord

from peacemusic.adapters.discord.presenters.music import track_embed
from peacemusic.modules.music.models import Track
from peacemusic.modules.music.permissions import MusicRequestContext
from peacemusic.modules.settings.service import GuildSettingsService


class DiscordQueueNotificationPublisher:
    """Send rich queue announcements to the channel that requested playback."""

    def __init__(self, bot: discord.Client, settings: GuildSettingsService) -> None:
        self._bot = bot
        self._settings = settings

    async def publish_track_queued(
        self,
        context: MusicRequestContext,
        track: Track,
        *,
        queue_position: int | None,
        now_playing: bool,
    ) -> None:
        if context.text_channel_id is None:
            return
        settings = await self._settings.get(context.guild_id)
        if (
            not settings.general.notifications_enabled
            or not settings.music.track_announce
        ):
            return

        channel = self._bot.get_channel(context.text_channel_id)
        if channel is None:
            fetch_channel = getattr(self._bot, "fetch_channel", None)
            if fetch_channel is not None:
                channel = await fetch_channel(context.text_channel_id)
        if channel is None or not hasattr(channel, "send"):
            return

        description = "▶️ Now playing" if now_playing else "✅ Added to the queue"
        await channel.send(
            embed=track_embed(
                track,
                description=description,
                queue_position=queue_position,
                now_playing=now_playing,
            )
        )
