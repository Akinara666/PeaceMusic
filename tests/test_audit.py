from __future__ import annotations

import asyncio

from peacemusic.infrastructure.persistence.repositories.in_memory_audit import (
    InMemoryAuditWriter,
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
