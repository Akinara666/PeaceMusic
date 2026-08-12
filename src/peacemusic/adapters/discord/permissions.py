"""Discord-aware capability policy for music operations."""

from __future__ import annotations

from peacemusic.modules.music.permissions import MusicCapability, MusicRequestContext


class DiscordMusicPermissionService:
    _DJ_CAPABILITIES = {
        MusicCapability.PAUSE,
        MusicCapability.RESUME,
        MusicCapability.SKIP,
        MusicCapability.STOP,
        MusicCapability.SET_VOLUME,
        MusicCapability.QUEUE_REMOVE,
        MusicCapability.QUEUE_MOVE,
        MusicCapability.QUEUE_CLEAR,
        MusicCapability.QUEUE_SHUFFLE,
        MusicCapability.LOOP,
        MusicCapability.AUTOPLAY,
        MusicCapability.DISCONNECT,
        MusicCapability.SEEK,
    }

    async def allowed(
        self, context: MusicRequestContext, capability: MusicCapability
    ) -> bool:
        if context.can_manage_guild:
            return True
        if capability in self._DJ_CAPABILITIES and not context.has_dj_role:
            return False
        if capability in {MusicCapability.QUEUE_ADD, MusicCapability.PLAY}:
            return context.user_voice_channel_id is not None and (
                context.bot_voice_channel_id is None
                or context.user_voice_channel_id == context.bot_voice_channel_id
            )
        return (
            context.user_voice_channel_id is not None
            and context.user_voice_channel_id == context.bot_voice_channel_id
        )
