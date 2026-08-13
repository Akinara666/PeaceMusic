"""Strictly authorized Discord administration commands for long-term memory."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from peacemusic.core.errors import PeaceMusicError
from peacemusic.modules.memory.service import MemoryService
from peacemusic.modules.settings.service import GuildSettingsService


class MemoryCog(commands.Cog):
    memory = app_commands.Group(name="memory", description="Manage long-term memory")

    def __init__(
        self,
        service: MemoryService,
        settings: GuildSettingsService,
    ) -> None:
        self._service = service
        self._settings = settings

    @memory.command(name="status", description="Show memory status")
    @app_commands.guild_only()
    async def status(self, interaction: discord.Interaction) -> None:
        await self._send_status(interaction)

    async def _send_status(self, interaction: discord.Interaction) -> None:
        try:
            guild_id, user_id = self._ids(interaction)
            settings = await self._settings.get(guild_id)
            count = await self._service.count_user(
                guild_id=guild_id,
                user_id=user_id,
            )
            state = "enabled" if settings.memory.enabled else "disabled"
            await interaction.response.send_message(
                f"Memory is **{state}**. Your stored records: `{count}`.",
                ephemeral=True,
            )
        except PeaceMusicError as exc:
            await self._send_error(interaction, exc)

    @memory.command(name="stats", description="Show your memory statistics")
    @app_commands.guild_only()
    async def stats(self, interaction: discord.Interaction) -> None:
        await self._send_status(interaction)

    @memory.command(name="forget", description="Forget one of your memories")
    @app_commands.guild_only()
    async def forget(self, interaction: discord.Interaction, memory_id: str) -> None:
        try:
            guild_id, user_id = self._ids(interaction)
            deleted = await self._service.forget(
                guild_id=guild_id,
                user_id=user_id,
                memory_id=memory_id,
            )
            await interaction.response.send_message(
                f"Forgot {deleted} memory record(s).", ephemeral=True
            )
        except PeaceMusicError as exc:
            await self._send_error(interaction, exc)

    @memory.command(name="clear-channel", description="Clear a channel's memories")
    @app_commands.guild_only()
    async def clear_channel(self, interaction: discord.Interaction) -> None:
        try:
            guild_id, user_id = self._ids(interaction)
            channel_id = self._channel_id(interaction)
            deleted = await self._service.clear_channel(
                guild_id=guild_id,
                actor_user_id=user_id,
                channel_id=channel_id,
                can_manage_guild=self._can_manage(interaction),
            )
            await interaction.response.send_message(
                f"Cleared {deleted} channel memory record(s).", ephemeral=True
            )
        except PeaceMusicError as exc:
            await self._send_error(interaction, exc)

    @memory.command(name="clear-user", description="Clear a user's memories")
    @app_commands.guild_only()
    async def clear_user(self, interaction: discord.Interaction, user_id: int) -> None:
        try:
            guild_id, actor_user_id = self._ids(interaction)
            deleted = await self._service.clear_user(
                guild_id=guild_id,
                actor_user_id=actor_user_id,
                target_user_id=user_id,
                can_manage_guild=self._can_manage(interaction),
            )
            await interaction.response.send_message(
                f"Cleared {deleted} user memory record(s).", ephemeral=True
            )
        except PeaceMusicError as exc:
            await self._send_error(interaction, exc)

    @staticmethod
    def _ids(interaction: discord.Interaction) -> tuple[int, int]:
        if interaction.guild is None:
            raise PeaceMusicError("Memory commands are only available in guilds")
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

    @staticmethod
    def _channel_id(interaction: discord.Interaction) -> int:
        channel_id = getattr(getattr(interaction, "channel", None), "id", None)
        if not isinstance(channel_id, int) or channel_id <= 0:
            raise PeaceMusicError("This command must be used in a Discord channel")
        return channel_id

    @staticmethod
    async def _send_error(interaction: discord.Interaction, error: Exception) -> None:
        await interaction.response.send_message(str(error), ephemeral=True)
