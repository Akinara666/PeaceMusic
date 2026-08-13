"""Thin slash-command adapter over :class:`MusicService`."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from peacemusic.adapters.discord.presenters.music import player_embed, track_embed
from peacemusic.adapters.discord.context import music_request_context
from peacemusic.adapters.discord.views.player import PlayerView
from peacemusic.core.errors import PeaceMusicError
from peacemusic.modules.music.models import LoopMode
from peacemusic.modules.music.ports import PlayerMessageRepository
from peacemusic.modules.music.permissions import MusicRequestContext
from peacemusic.modules.music.service import MusicService
from peacemusic.modules.history.service import PlaybackHistoryService
from peacemusic.modules.settings.service import GuildSettingsService


class MusicCog(commands.Cog):
    def __init__(
        self,
        service: MusicService,
        history: PlaybackHistoryService | None = None,
        settings: GuildSettingsService | None = None,
        player_messages: PlayerMessageRepository | None = None,
    ) -> None:
        self._service = service
        self._history = history
        self._settings = settings
        self._player_messages = player_messages

    @staticmethod
    def _context(
        interaction: discord.Interaction, *, notify_queue: bool = True
    ) -> MusicRequestContext:
        try:
            return music_request_context(interaction, notify_queue=notify_queue)
        except ValueError as exc:
            raise PeaceMusicError(str(exc)) from exc

    async def _send_error(
        self, interaction: discord.Interaction, error: Exception
    ) -> None:
        message = str(error) or "Music operation failed"
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)

    async def _publish_player(
        self, interaction: discord.Interaction, embed: discord.Embed
    ) -> None:
        """Create or update the one persisted player message for a guild."""

        guild = interaction.guild
        channel = interaction.channel
        if self._player_messages is not None and guild is not None:
            stored = await self._player_messages.get(guild.id)
            if stored is not None and stored[0] == getattr(channel, "id", None):
                fetch_message = getattr(channel, "fetch_message", None)
                if fetch_message is not None:
                    try:
                        message = await fetch_message(stored[1])
                        await message.edit(embed=embed, view=PlayerView(self._service))
                        await interaction.response.send_message(
                            "Player updated.", ephemeral=True
                        )
                        return
                    except Exception:  # noqa: BLE001 - stale Discord message
                        pass

        await interaction.response.send_message(
            embed=embed, view=PlayerView(self._service)
        )
        if self._player_messages is not None and guild is not None:
            original_response = getattr(interaction, "original_response", None)
            if original_response is not None:
                message = await original_response()
                await self._player_messages.save(
                    guild.id,
                    channel_id=getattr(channel, "id", 0),
                    message_id=message.id,
                )

    @app_commands.command(name="play", description="Play or queue a track")
    @app_commands.guild_only()
    async def play(self, interaction: discord.Interaction, query: str) -> None:
        try:
            track = await self._service.play(
                self._context(interaction, notify_queue=False), query
            )
            await self._publish_player(interaction, track_embed(track))
        except PeaceMusicError as exc:
            await self._send_error(interaction, exc)

    @app_commands.command(name="search", description="Search for a playable track")
    @app_commands.guild_only()
    async def search(self, interaction: discord.Interaction, query: str) -> None:
        try:
            track = await self._service.resolve_track(self._context(interaction), query)
            await interaction.response.send_message(
                embed=track_embed(track, description="Search result")
            )
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

    @app_commands.command(name="seek", description="Seek within the current track")
    @app_commands.guild_only()
    async def seek(self, interaction: discord.Interaction, seconds: int) -> None:
        try:
            position = await self._service.seek(self._context(interaction), seconds)
            await interaction.response.send_message(
                f"⏩ Playback moved to {position} seconds."
            )
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

    @app_commands.command(name="join", description="Join your voice channel")
    @app_commands.guild_only()
    async def join(self, interaction: discord.Interaction) -> None:
        try:
            await self._service.connect(self._context(interaction))
            await interaction.response.send_message("🔊 Joined your voice channel.")
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

    @app_commands.command(name="nowplaying", description="Show the current track")
    @app_commands.guild_only()
    async def nowplaying(self, interaction: discord.Interaction) -> None:
        try:
            if interaction.guild is None:
                raise PeaceMusicError("Music commands are only available in guilds")
            player = await self._service.player_state(interaction.guild.id)
            await self._publish_player(interaction, player_embed(player))
        except PeaceMusicError as exc:
            await self._send_error(interaction, exc)

    @app_commands.command(name="autoplay", description="Enable or disable autoplay")
    @app_commands.guild_only()
    async def autoplay(self, interaction: discord.Interaction, enabled: bool) -> None:
        try:
            if self._settings is None or interaction.guild is None:
                raise PeaceMusicError("Guild settings are unavailable")
            settings = await self._settings.update(
                interaction.guild.id,
                actor_user_id=interaction.user.id,
                section="music",
                values={"autoplay_enabled": enabled},
            )
            state = "enabled" if settings.music.autoplay_enabled else "disabled"
            await interaction.response.send_message(f"Autoplay {state}.")
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
