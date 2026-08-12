"""PostgreSQL audit adapter for application configuration changes."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

from peacemusic.infrastructure.persistence.database import PostgresDatabase


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
        async with self._database.acquire() as connection:
            await connection.execute(
                """
                INSERT INTO audit_events (
                    guild_id, actor_user_id, event_type, payload, created_at
                )
                VALUES ($1, $2, 'SETTINGS_CHANGED', $3::jsonb, $4)
                """,
                guild_id,
                actor_user_id,
                _json_payload(changes),
                recorded_at,
            )


def _json_payload(changes: Mapping[str, object]) -> str:
    import json

    return json.dumps(dict(changes), default=str)
