"""Translate agent request context into the music application context."""

from __future__ import annotations

from peacemusic.modules.agent.context import AgentRequestContext
from peacemusic.modules.music.permissions import MusicRequestContext


def music_context(context: AgentRequestContext) -> MusicRequestContext:
    return MusicRequestContext(
        guild_id=context.guild_id or 0,
        user_id=context.user_id,
        user_voice_channel_id=context.user_voice_channel_id,
        bot_voice_channel_id=context.bot_voice_channel_id,
        can_manage_guild=context.can_manage_guild,
        member_role_ids=context.member_role_ids,
        dj_role_ids=context.dj_role_ids,
        text_channel_id=context.channel_id,
    )
