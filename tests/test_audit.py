from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from peacemusic.infrastructure.persistence.repositories.in_memory_audit import (
    InMemoryAuditWriter,
)
from peacemusic.infrastructure.persistence.repositories.postgres_audit import (
    PostgresSettingsAuditWriter,
)
from peacemusic.modules.audit.service import AuditService


def test_audit_service_records_typed_events() -> None:
    async def scenario() -> None:
        writer = InMemoryAuditWriter()
        service = AuditService(writer)

        await service.record(
            guild_id=1,
            actor_user_id=2,
            event_type="PLAY",
            payload={"title": "Example"},
        )

        assert writer.events[0].event_type == "PLAY"
        assert writer.events[0].payload == {"title": "Example"}
        assert writer.events[0].created_at.tzinfo is not None

    asyncio.run(scenario())


def test_postgres_settings_audit_writer_delegates_to_audit_writer() -> None:
    class FakeDatabase:
        def __init__(self) -> None:
            self.calls: list[tuple[object, ...]] = []

        @asynccontextmanager
        async def acquire(self):
            yield self

        async def execute(self, *args: object) -> None:
            self.calls.append(args)

    async def scenario() -> None:
        database = FakeDatabase()
        writer = PostgresSettingsAuditWriter(database)  # type: ignore[arg-type]

        await writer.record_settings_change(
            guild_id=1,
            actor_user_id=2,
            changes={"general.music_channel_id": 123},
            recorded_at=datetime.now(timezone.utc),
        )

        assert len(database.calls) == 1
        assert database.calls[0][3] == "SETTINGS_CHANGED"

    asyncio.run(scenario())
