from __future__ import annotations

import asyncio

import pytest

from peacemusic.core.errors import PermissionDeniedError
from peacemusic.infrastructure.persistence.repositories.in_memory_access import (
    InMemoryAccessControlRepository,
)
from peacemusic.modules.access.service import AccessControlService


def test_access_controls_suppress_users_and_channels() -> None:
    async def scenario() -> None:
        repository = InMemoryAccessControlRepository()
        service = AccessControlService(repository)

        assert not await service.is_suppressed(guild_id=1, user_id=2, channel_id=3)
        await service.set_user_blocked(
            guild_id=1,
            target_user_id=2,
            actor_user_id=9,
            blocked=True,
            can_manage_guild=True,
        )
        assert await service.is_suppressed(guild_id=1, user_id=2, channel_id=3)
        await service.set_user_blocked(
            guild_id=1,
            target_user_id=2,
            actor_user_id=9,
            blocked=False,
            can_manage_guild=True,
        )
        await service.set_channel_silent(
            guild_id=1,
            channel_id=3,
            actor_user_id=9,
            silent=True,
            can_manage_guild=True,
        )
        assert await service.is_suppressed(guild_id=1, user_id=2, channel_id=3)

    asyncio.run(scenario())


def test_access_changes_require_manage_guild() -> None:
    async def scenario() -> None:
        service = AccessControlService(InMemoryAccessControlRepository())
        with pytest.raises(PermissionDeniedError):
            await service.set_channel_silent(
                guild_id=1,
                channel_id=3,
                actor_user_id=9,
                silent=True,
                can_manage_guild=False,
            )

    asyncio.run(scenario())
