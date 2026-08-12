"""Conversion from Discord interactions to application context."""

from __future__ import annotations

import discord

from peacemusic.modules.settings.ports import SettingsAuthorizer
from peacemusic.modules.music.permissions import MusicRequestContext


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


def music_request_context(interaction: discord.Interaction) -> MusicRequestContext:
    """Convert a Discord interaction into the shared music request context."""

    if interaction.guild is None:
        raise ValueError("Music commands are only available in guilds")
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
