"""Discord commands for guild access blocking and silent mode."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from peacemusic.core.errors import PeaceMusicError
from peacemusic.modules.access.service import AccessControlService


class AccessCog(commands.Cog):
    access = app_commands.Group(name="access", description="Manage bot access")

    def __init__(self, service: AccessControlService) -> None:
        self._service = service

    @access.command(name="block-user", description="Block a user from bot responses")
    @app_commands.guild_only()
    async def block_user(self, interaction: discord.Interaction, user_id: int) -> None:
        await self._change_user(interaction, user_id, blocked=True)

    @access.command(name="unblock-user", description="Allow a blocked user again")
    @app_commands.guild_only()
    async def unblock_user(
        self, interaction: discord.Interaction, user_id: int
    ) -> None:
        await self._change_user(interaction, user_id, blocked=False)

    @access.command(
        name="silence-channel", description="Silence bot responses in a channel"
    )
    @app_commands.guild_only()
    async def silence_channel(
        self, interaction: discord.Interaction, channel_id: int
    ) -> None:
        await self._change_channel(interaction, channel_id, silent=True)

    @access.command(
        name="unsilence-channel", description="Enable bot responses in a channel"
    )
    @app_commands.guild_only()
    async def unsilence_channel(
        self, interaction: discord.Interaction, channel_id: int
    ) -> None:
        await self._change_channel(interaction, channel_id, silent=False)

    async def _change_user(
        self, interaction: discord.Interaction, user_id: int, *, blocked: bool
    ) -> None:
        try:
            guild_id, actor_id = self._context(interaction)
            await self._service.set_user_blocked(
                guild_id=guild_id,
                target_user_id=user_id,
                actor_user_id=actor_id,
                blocked=blocked,
                can_manage_guild=self._can_manage(interaction),
            )
            action = "blocked" if blocked else "unblocked"
            await interaction.response.send_message(
                f"User `{user_id}` is now {action}.", ephemeral=True
            )
        except PeaceMusicError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)

    async def _change_channel(
        self, interaction: discord.Interaction, channel_id: int, *, silent: bool
    ) -> None:
        try:
            guild_id, actor_id = self._context(interaction)
            await self._service.set_channel_silent(
                guild_id=guild_id,
                channel_id=channel_id,
                actor_user_id=actor_id,
                silent=silent,
                can_manage_guild=self._can_manage(interaction),
            )
            action = "silenced" if silent else "unsilenced"
            await interaction.response.send_message(
                f"Channel `{channel_id}` is now {action}.", ephemeral=True
            )
        except PeaceMusicError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)

    @staticmethod
    def _context(interaction: discord.Interaction) -> tuple[int, int]:
        if interaction.guild is None:
            raise PeaceMusicError("Access commands are only available in guilds")
        return interaction.guild.id, interaction.user.id

    @staticmethod
    def _can_manage(interaction: discord.Interaction) -> bool:
        return bool(
            getattr(
                getattr(interaction.user, "guild_permissions", None),
                "manage_guild",
                False,
            )
        )
