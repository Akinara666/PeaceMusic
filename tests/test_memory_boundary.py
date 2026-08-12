from __future__ import annotations

import asyncio

import pytest

from peacemusic.core.errors import PermissionDeniedError, ValidationError
from peacemusic.core.metrics import MetricsRegistry
from peacemusic.infrastructure.persistence.repositories.in_memory_memory import (
    InMemoryMemoryRepository,
)
from peacemusic.infrastructure.persistence.repositories.in_memory_settings import (
    InMemoryGuildSettingsRepository,
)
from peacemusic.modules.memory.namespaces import channel_namespace, user_namespace
from peacemusic.modules.memory.service import MemoryService
from peacemusic.modules.settings.service import GuildSettingsService


def test_memory_namespaces_are_explicit_and_independent() -> None:
    assert user_namespace(1, 2) != channel_namespace(1, 2)
    assert user_namespace(1, 2) == ("guild", "1", "user", "2", "memory")


def test_memory_service_remember_recall_and_forget() -> None:
    async def scenario() -> None:
        settings = GuildSettingsService(InMemoryGuildSettingsRepository())
        repository = InMemoryMemoryRepository()
        service = MemoryService(
            repository, settings_service=settings, metrics=MetricsRegistry()
        )

        record = await service.remember(
            guild_id=1,
            user_id=2,
            content="User prefers ambient music",
        )
        matches = await service.recall(
            guild_id=1,
            user_id=2,
            query="ambient music",
        )
        assert matches == [record]
        assert record.expires_at is not None
        assert (
            await service.forget(guild_id=1, user_id=2, memory_id=record.memory_id) == 1
        )

    asyncio.run(scenario())


def test_memory_service_enforces_limits_and_settings() -> None:
    async def scenario() -> None:
        settings = GuildSettingsService(InMemoryGuildSettingsRepository())
        service = MemoryService(InMemoryMemoryRepository(), settings_service=settings)
        with pytest.raises(ValidationError):
            await service.recall(guild_id=1, user_id=2, query="x", limit=0)

        current = await settings.get(1)
        current.memory.enabled = False
        repository = InMemoryGuildSettingsRepository()
        await repository.save(current)
        settings = GuildSettingsService(repository)
        service = MemoryService(InMemoryMemoryRepository(), settings_service=settings)
        with pytest.raises(PermissionDeniedError):
            await service.remember(guild_id=1, user_id=2, content="secret")

    asyncio.run(scenario())


def test_memory_admin_clears_require_manage_server() -> None:
    async def scenario() -> None:
        settings = GuildSettingsService(InMemoryGuildSettingsRepository())
        repository = InMemoryMemoryRepository()
        service = MemoryService(repository, settings_service=settings)
        await service.remember(
            guild_id=1,
            user_id=2,
            content="private preference",
        )
        await service.remember(
            guild_id=1,
            user_id=2,
            content="channel preference",
            scope="channel",
            channel_id=9,
        )

        with pytest.raises(PermissionDeniedError):
            await service.clear_user(
                guild_id=1,
                actor_user_id=3,
                target_user_id=2,
                can_manage_guild=False,
            )

        assert (
            await service.clear_channel(
                guild_id=1,
                actor_user_id=3,
                channel_id=9,
                can_manage_guild=True,
            )
            == 1
        )
        assert await service.count_user(guild_id=1, user_id=2) == 1

    asyncio.run(scenario())
