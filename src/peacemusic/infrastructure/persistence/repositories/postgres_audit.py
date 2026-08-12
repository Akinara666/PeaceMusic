"""PostgreSQL audit adapters."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime

from peacemusic.infrastructure.persistence.database import PostgresDatabase
from peacemusic.modules.audit.models import AuditEvent


class PostgresAuditWriter:
    def __init__(self, database: PostgresDatabase) -> None:
        self._database = database

    async def write(self, event: AuditEvent) -> None:
        async with self._database.acquire() as connection:
            await connection.execute(
                """
                INSERT INTO audit_events
                    (guild_id, actor_user_id, event_type, payload, created_at)
                VALUES ($1, $2, $3, $4::jsonb, $5)
                """,
                event.guild_id,
                event.actor_user_id,
                event.event_type,
                json.dumps(event.payload, default=str),
                event.created_at,
            )


class PostgresSettingsAuditWriter:
    def __init__(self, database: PostgresDatabase) -> None:
        self._database = database

    async def record_settings_change(
        self,
        *,
        guild_id: int,
        actor_user_id: int,
        changes: Mapping[str, object],
        recorded_at: datetime,
    ) -> None:
        await self._writer.write(
            AuditEvent(
                guild_id=guild_id,
                actor_user_id=actor_user_id,
                event_type="SETTINGS_CHANGED",
                payload=dict(changes),
                created_at=recorded_at,
            )
        )


def _json_payload(changes: Mapping[str, object]) -> str:
    import json

    return json.dumps(dict(changes), default=str)
