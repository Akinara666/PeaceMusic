"""Thin slash-command adapter over :class:`MusicService`."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from peacemusic.adapters.discord.presenters.music import player_embed, track_embed
from peacemusic.core.errors import PeaceMusicError
from peacemusic.modules.music.models import LoopMode
from peacemusic.modules.music.permissions import MusicRequestContext
from peacemusic.modules.music.service import MusicService
from peacemusic.modules.history.service import PlaybackHistoryService


class MusicCog(commands.Cog):
    def __init__(
        self, service: MusicService, history: PlaybackHistoryService | None = None
    ) -> None:
        self._service = service
        self._history = history

    @staticmethod
    def _context(interaction: discord.Interaction) -> MusicRequestContext:
        if interaction.guild is None:
            raise PeaceMusicError("Music commands are only available in guilds")
        member = interaction.user
        user_voice = getattr(getattr(member, "voice", None), "channel", None)
        bot_voice = getattr(
            getattr(interaction.guild, "voice_client", None), "channel", None
        )
        permissions = getattr(member, "guild_permissions", None)
        return MusicRequestContext(
            guild_id=interaction.guild.id,
            user_id=interaction.user.id,
            user_voice_channel_id=getattr(user_voice, "id", None),
            bot_voice_channel_id=getattr(bot_voice, "id", None),
            can_manage_guild=bool(getattr(permissions, "manage_guild", False)),
        )

    async def _send_error(
        self, interaction: discord.Interaction, error: Exception
    ) -> None:
        message = str(error) or "Music operation failed"
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)

    @app_commands.command(name="play", description="Play or queue a track")
    @app_commands.guild_only()
    async def play(self, interaction: discord.Interaction, query: str) -> None:
        try:
            track = await self._service.play(self._context(interaction), query)
            await interaction.response.send_message(embed=track_embed(track))
        except PeaceMusicError as exc:
            await self._send_error(interaction, exc)

    @app_commands.command(name="pause", description="Pause playback")
    @app_commands.guild_only()
    async def pause(self, interaction: discord.Interaction) -> None:
        try:
            await self._service.pause(self._context(interaction))
            await interaction.response.send_message("⏸ Playback paused.")
        except PeaceMusicError as exc:
            await self._send_error(interaction, exc)

    @app_commands.command(name="resume", description="Resume playback")
    @app_commands.guild_only()
    async def resume(self, interaction: discord.Interaction) -> None:
        try:
            await self._service.resume(self._context(interaction))
            await interaction.response.send_message("▶ Playback resumed.")
        except PeaceMusicError as exc:
            await self._send_error(interaction, exc)

    @app_commands.command(name="skip", description="Skip the current track")
    @app_commands.guild_only()
    async def skip(self, interaction: discord.Interaction) -> None:
        try:
            next_track = await self._service.skip(self._context(interaction))
            message = (
                f"⏭ Skipped to **{next_track.title}**."
                if next_track
                else "Queue ended."
            )
            await interaction.response.send_message(message)
        except PeaceMusicError as exc:
            await self._send_error(interaction, exc)

    @app_commands.command(name="stop", description="Stop playback and clear the queue")
    @app_commands.guild_only()
    async def stop(self, interaction: discord.Interaction) -> None:
        try:
            await self._service.stop(self._context(interaction))
            await interaction.response.send_message("⏹ Playback stopped.")
        except PeaceMusicError as exc:
            await self._send_error(interaction, exc)

    @app_commands.command(name="leave", description="Disconnect from voice")
    @app_commands.guild_only()
    async def leave(self, interaction: discord.Interaction) -> None:
        try:
            await self._service.disconnect(self._context(interaction))
            await interaction.response.send_message("👋 Disconnected from voice.")
        except PeaceMusicError as exc:
            await self._send_error(interaction, exc)

    @app_commands.command(name="volume", description="Set player volume")
    @app_commands.guild_only()
    async def volume(self, interaction: discord.Interaction, value: int) -> None:
        try:
            volume = await self._service.set_volume(self._context(interaction), value)
            await interaction.response.send_message(f"🔊 Volume set to {volume}%.")
        except PeaceMusicError as exc:
            await self._send_error(interaction, exc)

    @app_commands.command(name="loop", description="Set loop mode")
    @app_commands.guild_only()
    @app_commands.choices(
        mode=[
            app_commands.Choice(name="Off", value="off"),
            app_commands.Choice(name="Track", value="track"),
            app_commands.Choice(name="Queue", value="queue"),
        ]
    )
    async def loop(
        self, interaction: discord.Interaction, mode: app_commands.Choice[str]
    ) -> None:
        try:
            selected = await self._service.set_loop_mode(
                self._context(interaction), LoopMode(mode.value)
            )
            await interaction.response.send_message(
                f"🔁 Loop mode: `{selected.value}`."
            )
        except PeaceMusicError as exc:
            await self._send_error(interaction, exc)

    @app_commands.command(name="queue", description="Show the current queue")
    @app_commands.guild_only()
    async def queue(self, interaction: discord.Interaction) -> None:
        try:
            player = await self._service.player_state(interaction.guild.id)  # type: ignore[union-attr]
            await interaction.response.send_message(embed=player_embed(player))
        except PeaceMusicError as exc:
            await self._send_error(interaction, exc)

    @app_commands.command(name="history", description="Show recently played tracks")
    @app_commands.guild_only()
    async def history(self, interaction: discord.Interaction, limit: int = 10) -> None:
        if self._history is None:
            await interaction.response.send_message(
                "Playback history is unavailable.", ephemeral=True
            )
            return
        try:
            entries = await self._history.recent(interaction.guild.id, limit)  # type: ignore[union-attr]
            description = (
                "\n".join(
                    f"{index}. **{entry.title}**"
                    for index, entry in enumerate(entries, start=1)
                )
                or "No playback history yet."
            )
            await interaction.response.send_message(description, ephemeral=True)
        except PeaceMusicError as exc:
            await self._send_error(interaction, exc)

    @app_commands.command(name="remove", description="Remove a queued track")
    @app_commands.guild_only()
    async def remove(self, interaction: discord.Interaction, index: int) -> None:
        try:
            track = await self._service.remove_from_queue(
                self._context(interaction), index
            )
            await interaction.response.send_message(f"Removed **{track.title}**.")
        except PeaceMusicError as exc:
            await self._send_error(interaction, exc)

    @app_commands.command(name="move", description="Move a queued track")
    @app_commands.guild_only()
    async def move(
        self, interaction: discord.Interaction, source_index: int, target_index: int
    ) -> None:
        try:
            await self._service.move_in_queue(
                self._context(interaction), source_index, target_index
            )
            await interaction.response.send_message("Queue position updated.")
        except PeaceMusicError as exc:
            await self._send_error(interaction, exc)

    @app_commands.command(name="shuffle", description="Shuffle the queue")
    @app_commands.guild_only()
    async def shuffle(self, interaction: discord.Interaction) -> None:
        try:
            await self._service.shuffle_queue(self._context(interaction))
            await interaction.response.send_message("🔀 Queue shuffled.")
        except PeaceMusicError as exc:
            await self._send_error(interaction, exc)

    @app_commands.command(name="clear", description="Clear the queue")
    @app_commands.guild_only()
    async def clear(self, interaction: discord.Interaction) -> None:
        try:
            count = await self._service.clear_queue(self._context(interaction))
            await interaction.response.send_message(f"Cleared {count} queued tracks.")
        except PeaceMusicError as exc:
            await self._send_error(interaction, exc)
