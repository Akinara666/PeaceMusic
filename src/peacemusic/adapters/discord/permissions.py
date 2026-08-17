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
        return await self.denial_reason(context, capability) is None

    async def denial_reason(
        self, context: MusicRequestContext, capability: MusicCapability
    ) -> tuple[str, dict[str, object]] | None:
        """Explain a rejected request for user- and model-facing adapters."""

        if context.can_manage_guild:
            return None
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
            if configured_roles:
                message = (
                    f"Cannot perform '{capability.value}': this server requires a "
                    "DJ role for music controls, and the user does not have one. "
                    "The user also does not have Manage Server permission."
                )
                reason = "dj_role_required"
            else:
                message = (
                    f"Cannot perform '{capability.value}': this server is configured "
                    "to require a DJ role for music controls, but no DJ role is "
                    "configured. The user also does not have Manage Server "
                    "permission."
                )
                reason = "dj_role_not_configured"
            return message, {
                "capability": capability.value,
                "reason": reason,
                "permission_mode": permission_mode,
                "has_manage_guild": False,
                "has_dj_role": False,
            }
        if capability in {MusicCapability.QUEUE_ADD, MusicCapability.PLAY}:
            if context.user_voice_channel_id is None:
                return (
                    f"Cannot perform '{capability.value}': the user is not in a "
                    "voice channel.",
                    {
                        "capability": capability.value,
                        "reason": "user_not_in_voice_channel",
                    },
                )
            if (
                context.bot_voice_channel_id is not None
                and context.user_voice_channel_id != context.bot_voice_channel_id
            ):
                return (
                    f"Cannot perform '{capability.value}': the user is not in the "
                    "bot's voice channel.",
                    {
                        "capability": capability.value,
                        "reason": "different_voice_channel",
                    },
                )
            return None
        if context.user_voice_channel_id is None:
            return (
                f"Cannot perform '{capability.value}': the user is not in a voice "
                "channel.",
                {
                    "capability": capability.value,
                    "reason": "user_not_in_voice_channel",
                },
            )
        if context.bot_voice_channel_id is None:
            return (
                f"Cannot perform '{capability.value}': the bot is not connected "
                "to a voice channel.",
                {
                    "capability": capability.value,
                    "reason": "bot_not_in_voice_channel",
                },
            )
        if context.user_voice_channel_id != context.bot_voice_channel_id:
            return (
                f"Cannot perform '{capability.value}': the user is not in the "
                "bot's voice channel.",
                {
                    "capability": capability.value,
                    "reason": "different_voice_channel",
                },
            )
        return None
