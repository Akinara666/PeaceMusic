"""Application service for blocked users and silent channels."""

from __future__ import annotations

from peacemusic.core.errors import PermissionDeniedError, ValidationError
from peacemusic.modules.audit.service import AuditService
from peacemusic.modules.access.ports import AccessControlRepository


class AccessControlService:
    """Apply guild access policy without exposing persistence to Discord adapters."""

    def __init__(
        self,
        repository: AccessControlRepository,
        *,
        audit: AuditService | None = None,
    ) -> None:
        self._repository = repository
        self._audit = audit

    async def is_suppressed(
        self, *, guild_id: int, user_id: int, channel_id: int
    ) -> bool:
        self._validate_ids(guild_id, user_id, channel_id)
        return await self._repository.is_user_disabled(
            guild_id, user_id
        ) or await self._repository.is_channel_muted(guild_id, channel_id)

    async def set_user_blocked(
        self,
        *,
        guild_id: int,
        target_user_id: int,
        actor_user_id: int,
        blocked: bool,
        can_manage_guild: bool,
    ) -> None:
        self._require_manager(can_manage_guild)
        self._validate_ids(guild_id, target_user_id, actor_user_id)
        await self._repository.set_user_disabled(guild_id, target_user_id, blocked)
        await self._record(
            guild_id,
            actor_user_id,
            "block" if blocked else "unblock",
            target_user_id,
        )

    async def set_channel_silent(
        self,
        *,
        guild_id: int,
        channel_id: int,
        actor_user_id: int,
        silent: bool,
        can_manage_guild: bool,
    ) -> None:
        self._require_manager(can_manage_guild)
        self._validate_ids(guild_id, channel_id, actor_user_id)
        await self._repository.set_channel_muted(guild_id, channel_id, silent)
        await self._record(
            guild_id,
            actor_user_id,
            "silent" if silent else "unsilent",
            channel_id,
        )

    async def _record(
        self, guild_id: int, actor_user_id: int, action: str, target_id: int
    ) -> None:
        if self._audit is not None:
            await self._audit.record(
                guild_id=guild_id,
                actor_user_id=actor_user_id,
                event_type="BOT_ACCESS_CHANGE",
                payload={"action": action, "target_id": target_id},
            )

    @staticmethod
    def _require_manager(can_manage_guild: bool) -> None:
        if not can_manage_guild:
            raise PermissionDeniedError("Manage Server permission is required")

    @staticmethod
    def _validate_ids(guild_id: int, first_id: int, second_id: int) -> None:
        if guild_id <= 0 or first_id <= 0 or second_id <= 0:
            raise ValidationError("Guild, user, and channel IDs must be positive")
