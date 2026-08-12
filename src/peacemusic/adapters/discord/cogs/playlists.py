"""Thin Discord adapter for persistent playlist commands."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from peacemusic.adapters.discord.cogs.music import MusicCog
from peacemusic.core.errors import PeaceMusicError
from peacemusic.modules.music.permissions import MusicRequestContext
from peacemusic.modules.playlists.service import PlaylistService


class PlaylistCog(commands.Cog):
    playlist = app_commands.Group(name="playlist", description="Manage playlists")

    def __init__(self, service: PlaylistService) -> None:
        self._service = service

    @staticmethod
    def _context(interaction: discord.Interaction) -> MusicRequestContext:
        return MusicCog._context(interaction)

    async def _send_error(
        self, interaction: discord.Interaction, error: Exception
    ) -> None:
        message = str(error) or "Playlist operation failed"
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)

    @playlist.command(name="create", description="Create a playlist")
    async def create(self, interaction: discord.Interaction, name: str) -> None:
        try:
            playlist = await self._service.create(self._context(interaction), name)
            await interaction.response.send_message(
                f"Created playlist **{playlist.name}**."
            )
        except PeaceMusicError as exc:
            await self._send_error(interaction, exc)

    @playlist.command(name="delete", description="Delete a playlist")
    async def delete(self, interaction: discord.Interaction, name: str) -> None:
        try:
            await self._service.delete(self._context(interaction), name)
            await interaction.response.send_message(f"Deleted playlist **{name}**.")
        except PeaceMusicError as exc:
            await self._send_error(interaction, exc)

    @playlist.command(name="add", description="Add a track to a playlist")
    async def add(
        self, interaction: discord.Interaction, name: str, query: str
    ) -> None:
        try:
            playlist = await self._service.add(self._context(interaction), name, query)
            await interaction.response.send_message(
                f"Added a track to **{playlist.name}** ({len(playlist.tracks)} total)."
            )
        except PeaceMusicError as exc:
            await self._send_error(interaction, exc)

    @playlist.command(name="remove", description="Remove a track from a playlist")
    async def remove(
        self, interaction: discord.Interaction, name: str, index: int
    ) -> None:
        try:
            track = await self._service.remove(self._context(interaction), name, index)
            await interaction.response.send_message(f"Removed **{track.title}**.")
        except PeaceMusicError as exc:
            await self._send_error(interaction, exc)

    @playlist.command(name="play", description="Play a saved playlist")
    async def play(self, interaction: discord.Interaction, name: str) -> None:
        try:
            count = await self._service.play(self._context(interaction), name)
            await interaction.response.send_message(
                f"Queued {count} tracks from **{name}**."
            )
        except PeaceMusicError as exc:
            await self._send_error(interaction, exc)

    @playlist.command(name="list", description="List your playlists")
    async def list(self, interaction: discord.Interaction) -> None:
        try:
            playlists = await self._service.list(self._context(interaction))
            description = (
                "\n".join(
                    f"• **{playlist.name}** — {len(playlist.tracks)} tracks"
                    for playlist in playlists
                )
                or "No playlists yet."
            )
            await interaction.response.send_message(description, ephemeral=True)
        except PeaceMusicError as exc:
            await self._send_error(interaction, exc)
