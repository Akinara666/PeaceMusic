"""Discord-aware capability policy for music operations."""

from __future__ import annotations

from peacemusic.modules.music.permissions import MusicCapability, MusicRequestContext
from peacemusic.modules.music.roles import DJRoleRepository
from peacemusic.modules.settings.service import GuildSettingsService


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

    def __init__(
        self,
        dj_roles: DJRoleRepository | None = None,
        settings: GuildSettingsService | None = None,
    ) -> None:
        self._dj_roles = dj_roles
        self._settings = settings

    async def allowed(
        self, context: MusicRequestContext, capability: MusicCapability
    ) -> bool:
        if context.can_manage_guild:
            return True
        permission_mode = "role"
        if self._settings is not None:
            guild_settings = await self._settings.get(context.guild_id)
            permission_mode = guild_settings.music.permission_mode
        configured_roles = context.dj_role_ids
        if self._dj_roles is not None:
            configured_roles = await self._dj_roles.list_role_ids(context.guild_id)
        has_dj_role = bool(set(context.member_role_ids).intersection(configured_roles))
        if (
            capability in self._DJ_CAPABILITIES
            and permission_mode == "role"
            and not has_dj_role
        ):
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
