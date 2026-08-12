"""Thin Discord controller for setup and guild settings."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from peacemusic.adapters.discord.context import is_guild_manager
from peacemusic.adapters.discord.presenters.settings import settings_embed
from peacemusic.adapters.discord.views.settings import SetupView, SettingsView
from peacemusic.modules.settings.service import GuildSettingsService


class SettingsCog(commands.Cog):
    def __init__(self, service: GuildSettingsService) -> None:
        self._service = service

    @app_commands.command(
        name="setup", description="Configure PeaceMusic for this server"
    )
    @app_commands.guild_only()
    async def setup(self, interaction: discord.Interaction) -> None:
        if not is_guild_manager(interaction):
            await interaction.response.send_message(
                "Manage Server permission is required.", ephemeral=True
            )
            return
        assert interaction.guild is not None
        await interaction.response.send_message(
            "PeaceMusic Setup — Step 1/3\nSelect the channel for music commands:",
            view=SetupView(
                self._service,
                guild_id=interaction.guild.id,
                actor_user_id=interaction.user.id,
            ),
            ephemeral=True,
        )

    @app_commands.command(name="settings", description="Open PeaceMusic settings")
    @app_commands.guild_only()
    async def settings(self, interaction: discord.Interaction) -> None:
        if not is_guild_manager(interaction):
            await interaction.response.send_message(
                "Manage Server permission is required.", ephemeral=True
            )
            return
        assert interaction.guild is not None
        current = await self._service.get(interaction.guild.id)
        await interaction.response.send_message(
            embed=settings_embed(current),
            view=SettingsView(
                self._service,
                guild_id=interaction.guild.id,
                actor_user_id=interaction.user.id,
            ),
            ephemeral=True,
        )
