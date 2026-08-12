"""Discord-aware capability policy for music operations."""

from __future__ import annotations

from peacemusic.modules.music.permissions import MusicCapability, MusicRequestContext


class DiscordMusicPermissionService:
    async def allowed(
        self, context: MusicRequestContext, capability: MusicCapability
    ) -> bool:
        if context.can_manage_guild:
            return True
        if capability in {MusicCapability.QUEUE_ADD, MusicCapability.PLAY}:
            return context.user_voice_channel_id is not None and (
                context.bot_voice_channel_id is None
                or context.user_voice_channel_id == context.bot_voice_channel_id
            )
        return (
            context.user_voice_channel_id is not None
            and context.user_voice_channel_id == context.bot_voice_channel_id
        )
