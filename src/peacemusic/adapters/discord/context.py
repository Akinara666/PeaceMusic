"""Conversion from Discord interactions to application context."""

from __future__ import annotations

import discord

from peacemusic.modules.settings.ports import SettingsAuthorizer


class DiscordSettingsAuthorizer(SettingsAuthorizer):
    """Resolve Manage Guild permission from Discord at request time."""

    def __init__(self, bot: discord.Client) -> None:
        self._bot = bot

    async def can_manage_settings(self, guild_id: int, user_id: int) -> bool:
        guild = self._bot.get_guild(guild_id)
        if guild is None:
            return False
        member = guild.get_member(user_id)
        return bool(member and member.guild_permissions.manage_guild)


def is_guild_manager(interaction: discord.Interaction) -> bool:
    """Check the adapter-level permission needed to open settings UI."""

    user = interaction.user
    return isinstance(user, discord.Member) and user.guild_permissions.manage_guild
