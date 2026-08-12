"""Interactive player controls backed by the shared MusicService."""

from __future__ import annotations

import discord

from peacemusic.adapters.discord.context import music_request_context
from peacemusic.adapters.discord.presenters.music import player_embed
from peacemusic.core.errors import PeaceMusicError
from peacemusic.modules.music.models import PlaybackStatus
from peacemusic.modules.music.service import MusicService


class PlayerView(discord.ui.View):
    """Persistent controls for one player message."""

    def __init__(self, service: MusicService) -> None:
        super().__init__(timeout=None)
        self._service = service

    @discord.ui.button(
        label="⏯",
        style=discord.ButtonStyle.success,
        custom_id="peacemusic_player_pause",
    )
    async def pause_resume(
        self, interaction: discord.Interaction, _button: discord.ui.Button
    ) -> None:
        try:
            context = music_request_context(interaction)
            player = await self._service.player_state(context.guild_id)
            if player.status is PlaybackStatus.PAUSED:
                await self._service.resume(context)
            else:
                await self._service.pause(context)
            await self._refresh(interaction, context.guild_id)
        except (PeaceMusicError, ValueError) as exc:
            await self._send_error(interaction, exc)

    @discord.ui.button(
        label="⏭",
        style=discord.ButtonStyle.secondary,
        custom_id="peacemusic_player_skip",
    )
    async def skip(
        self, interaction: discord.Interaction, _button: discord.ui.Button
    ) -> None:
        try:
            context = music_request_context(interaction)
            await self._service.skip(context)
            await self._refresh(interaction, context.guild_id)
        except (PeaceMusicError, ValueError) as exc:
            await self._send_error(interaction, exc)

    @discord.ui.button(
        label="⏹",
        style=discord.ButtonStyle.secondary,
        custom_id="peacemusic_player_stop",
    )
    async def stop(
        self, interaction: discord.Interaction, _button: discord.ui.Button
    ) -> None:
        try:
            context = music_request_context(interaction)
            await self._service.stop(context)
            await self._refresh(interaction, context.guild_id)
        except (PeaceMusicError, ValueError) as exc:
            await self._send_error(interaction, exc)

    @discord.ui.button(
        label="🔀",
        style=discord.ButtonStyle.secondary,
        custom_id="peacemusic_player_shuffle",
    )
    async def shuffle(
        self, interaction: discord.Interaction, _button: discord.ui.Button
    ) -> None:
        try:
            context = music_request_context(interaction)
            await self._service.shuffle_queue(context)
            await self._refresh(interaction, context.guild_id)
        except (PeaceMusicError, ValueError) as exc:
            await self._send_error(interaction, exc)

    async def _refresh(self, interaction: discord.Interaction, guild_id: int) -> None:
        await interaction.response.edit_message(
            embed=player_embed(await self._service.player_state(guild_id)),
            view=self,
        )

    @staticmethod
    async def _send_error(interaction: discord.Interaction, error: Exception) -> None:
        message = str(error) or "Player operation failed"
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)
