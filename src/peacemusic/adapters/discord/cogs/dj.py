"""Administrator commands for persistent DJ-role configuration."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from peacemusic.core.errors import PeaceMusicError
from peacemusic.modules.music.roles import DJRoleRepository


class DJCog(commands.Cog):
    dj = app_commands.Group(name="dj", description="Manage DJ roles")

    def __init__(self, repository: DJRoleRepository) -> None:
        self._repository = repository

    @dj.command(name="add", description="Allow a role to control music")
    @app_commands.guild_only()
    async def add(self, interaction: discord.Interaction, role_id: int) -> None:
        try:
            self._require_manager(interaction)
            if interaction.guild is None:
                raise PeaceMusicError("DJ commands are only available in guilds")
            role = interaction.guild.get_role(role_id)
            if role is None:
                raise PeaceMusicError("Role was not found in this server")
            await self._repository.add_role(interaction.guild.id, role.id, role.name)
            await interaction.response.send_message(
                f"Added **{role.name}** as a DJ role.", ephemeral=True
            )
        except PeaceMusicError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)

    @dj.command(name="remove", description="Remove a configured DJ role")
    @app_commands.guild_only()
    async def remove(self, interaction: discord.Interaction, role_id: int) -> None:
        try:
            self._require_manager(interaction)
            if interaction.guild is None:
                raise PeaceMusicError("DJ commands are only available in guilds")
            removed = await self._repository.remove_role(interaction.guild.id, role_id)
            if not removed:
                raise PeaceMusicError("That role is not configured as a DJ role")
            await interaction.response.send_message(
                "Removed the DJ role.", ephemeral=True
            )
        except PeaceMusicError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)

    @dj.command(name="list", description="List configured DJ roles")
    @app_commands.guild_only()
    async def list(self, interaction: discord.Interaction) -> None:
        try:
            self._require_manager(interaction)
            if interaction.guild is None:
                raise PeaceMusicError("DJ commands are only available in guilds")
            roles = await self._repository.list_roles(interaction.guild.id)
            description = (
                "\n".join(f"• <@&{role_id}> — {name}" for role_id, name in roles)
                or "No DJ roles configured."
            )
            await interaction.response.send_message(description, ephemeral=True)
        except PeaceMusicError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)

    @staticmethod
    def _require_manager(interaction: discord.Interaction) -> None:
        if not getattr(
            getattr(interaction.user, "guild_permissions", None),
            "manage_guild",
            False,
        ):
            raise PeaceMusicError("Manage Server permission is required")
