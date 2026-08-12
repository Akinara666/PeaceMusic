from __future__ import annotations

import asyncio

import pytest

from peacemusic.core.config import GlobalLimits
from peacemusic.core.errors import PermissionDeniedError, ValidationError
from peacemusic.infrastructure.persistence.repositories.in_memory_settings import (
    InMemoryGuildSettingsRepository,
    InMemorySettingsAuditWriter,
)
from peacemusic.modules.settings.service import GuildSettingsService


class StaticAuthorizer:
    def __init__(self, allowed: bool) -> None:
        self.allowed = allowed

    async def can_manage_settings(self, guild_id: int, user_id: int) -> bool:
        return self.allowed


def test_new_guild_get_is_persisted_and_cached() -> None:
    async def scenario() -> None:
        repository = InMemoryGuildSettingsRepository()
        service = GuildSettingsService(
            repository,
            limits=GlobalLimits(max_queue_size=50),
            allowed_models=("gemini-safe",),
        )

        settings = await service.get(123)

        assert settings.guild_id == 123
        assert settings.music.max_queue_size == 50
        assert settings.ai.model == "gemini-safe"
        assert 123 in repository.values

    asyncio.run(scenario())


def test_settings_update_is_validated_and_audited() -> None:
    async def scenario() -> None:
        repository = InMemoryGuildSettingsRepository()
        audit = InMemorySettingsAuditWriter()
        service = GuildSettingsService(
            repository,
            limits=GlobalLimits(max_queue_size=100),
            allowed_models=("gemini-safe",),
            authorizer=StaticAuthorizer(True),
            audit_writer=audit,
        )

        settings = await service.update(
            123,
            actor_user_id=456,
            section="music",
            values={"default_volume": 40, "max_queue_size": 80},
        )

        assert settings.music.default_volume == 40
        assert settings.music.max_queue_size == 80
        assert audit.events[0]["actor_user_id"] == 456
        assert audit.events[0]["changes"] == {
            "music.default_volume": 40,
            "music.max_queue_size": 80,
        }

    asyncio.run(scenario())


def test_settings_update_requires_authorization() -> None:
    async def scenario() -> None:
        service = GuildSettingsService(
            InMemoryGuildSettingsRepository(),
            authorizer=StaticAuthorizer(False),
        )

        with pytest.raises(PermissionDeniedError):
            await service.update(
                123,
                actor_user_id=456,
                section="general",
                values={"language": "ru"},
            )

    asyncio.run(scenario())


def test_settings_cannot_exceed_global_queue_limit_or_model_allowlist() -> None:
    async def scenario() -> None:
        service = GuildSettingsService(
            InMemoryGuildSettingsRepository(),
            limits=GlobalLimits(max_queue_size=20),
            allowed_models=("gemini-safe",),
            authorizer=StaticAuthorizer(True),
        )

        with pytest.raises(ValidationError, match="global safety"):
            await service.update(
                123,
                actor_user_id=456,
                section="music",
                values={"max_queue_size": 21},
            )

        with pytest.raises(ValidationError, match="allowlist"):
            await service.update(
                123,
                actor_user_id=456,
                section="ai",
                values={"model": "gemini-arbitrary"},
            )

    asyncio.run(scenario())
