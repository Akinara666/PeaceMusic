from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import pytest

from peacemusic.adapters.discord.cogs.chat import ChatCog
from peacemusic.core.errors import PermissionDeniedError, ValidationError
from peacemusic.infrastructure.persistence.repositories.in_memory_audit import (
    InMemoryAuditWriter,
)
from peacemusic.infrastructure.persistence.repositories.in_memory_access import (
    InMemoryAccessControlRepository,
)
from peacemusic.infrastructure.persistence.repositories.postgres_access import (
    PostgresAccessControlRepository,
)
from peacemusic.modules.access.service import AccessControlService
from peacemusic.modules.audit.service import AuditService


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


def test_access_changes_are_audited_and_ids_are_validated() -> None:
    async def scenario() -> None:
        writer = InMemoryAuditWriter()
        service = AccessControlService(
            InMemoryAccessControlRepository(), audit=AuditService(writer)
        )
        await service.set_user_blocked(
            guild_id=1,
            target_user_id=2,
            actor_user_id=9,
            blocked=True,
            can_manage_guild=True,
        )
        assert writer.events[0].event_type == "BOT_ACCESS_CHANGE"
        with pytest.raises(ValidationError):
            await service.set_channel_silent(
                guild_id=0,
                channel_id=3,
                actor_user_id=9,
                silent=True,
                can_manage_guild=True,
            )

    asyncio.run(scenario())


def test_chat_cog_suppresses_access_blocked_messages() -> None:
    class Access:
        async def is_suppressed(self, **_kwargs: int) -> bool:
            return True

    message = type(
        "Message",
        (),
        {
            "author": type("Author", (), {"bot": False, "id": 2})(),
            "guild": type("Guild", (), {"id": 1})(),
            "channel": type("Channel", (), {"id": 3})(),
        },
    )()

    asyncio.run(ChatCog(object(), Access()).on_message(message))


def test_postgres_access_repository_uses_expected_operations() -> None:
    class Connection:
        def __init__(self) -> None:
            self.commands: list[tuple[str, object]] = []

        async def fetchval(self, query: str, *_args: int) -> bool:
            self.commands.append((query, "fetchval"))
            return "disabled_users" in query

        async def execute(self, query: str, *_args: object) -> None:
            self.commands.append((query, "execute"))

    class Database:
        def __init__(self, connection: Connection) -> None:
            self.connection = connection

        @asynccontextmanager
        async def acquire(self):
            yield self.connection

    async def scenario() -> None:
        connection = Connection()
        repository = PostgresAccessControlRepository(Database(connection))
        assert await repository.is_user_disabled(1, 2)
        assert not await repository.is_channel_muted(1, 3)
        await repository.set_user_disabled(1, 2, True)
        await repository.set_user_disabled(1, 2, False)
        await repository.set_channel_muted(1, 3, True)
        await repository.set_channel_muted(1, 3, False)
        assert len(connection.commands) == 6

    asyncio.run(scenario())
