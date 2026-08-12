"""discord.py voice gateway used by the v2 MusicService."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import discord

from peacemusic.core.errors import PlaybackError, ResourceNotFoundError


class DiscordVoiceGateway:
    def __init__(self, bot: discord.Client) -> None:
        self._bot = bot
        self._clients: dict[int, discord.VoiceClient] = {}

    async def connect(self, guild_id: int, channel_id: int) -> None:
        guild = self._bot.get_guild(guild_id)
        if guild is None:
            raise ResourceNotFoundError("Discord guild is unavailable")
        channel = guild.get_channel(channel_id)
        if not isinstance(channel, discord.VoiceChannel):
            raise ResourceNotFoundError("Discord voice channel is unavailable")
        client = self._clients.get(guild_id) or guild.voice_client
        if client is not None and client.is_connected():
            if client.channel.id != channel_id:
                await client.move_to(channel)
            self._clients[guild_id] = client
            return
        try:
            self._clients[guild_id] = await channel.connect()
        except (discord.DiscordException, OSError) as exc:
            raise PlaybackError("Could not connect to the voice channel") from exc

    async def play(
        self,
        guild_id: int,
        source: object,
        *,
        after: Callable[[Exception | None], None] | None = None,
    ) -> None:
        client = self._client(guild_id)
        if client.is_playing() or client.is_paused():
            client.stop()
        try:
            client.play(source, after=after)
        except (discord.DiscordException, OSError, TypeError) as exc:
            raise PlaybackError("Could not start Discord audio playback") from exc

    async def pause(self, guild_id: int) -> None:
        self._client(guild_id).pause()

    async def resume(self, guild_id: int) -> None:
        self._client(guild_id).resume()

    async def stop(self, guild_id: int) -> None:
        client = self._clients.get(guild_id)
        if client is not None and (client.is_playing() or client.is_paused()):
            client.stop()

    async def set_volume(self, guild_id: int, volume: int) -> None:
        client = self._client(guild_id)
        source: Any = getattr(client, "source", None)
        if hasattr(source, "volume"):
            source.volume = volume / 100

    async def disconnect(self, guild_id: int) -> None:
        client = self._clients.pop(guild_id, None)
        if client is not None:
            await client.disconnect()

    def _client(self, guild_id: int) -> discord.VoiceClient:
        client = self._clients.get(guild_id)
        if client is None or not client.is_connected():
            raise PlaybackError("Bot is not connected to voice")
        return client
