"""Shared service for security-relevant application audit events."""

from __future__ import annotations

from datetime import datetime, timezone

from peacemusic.modules.audit.models import AuditEvent
from peacemusic.modules.audit.ports import AuditWriter


class AuditService:
    def __init__(self, writer: AuditWriter) -> None:
        self._writer = writer

    async def record(
        self,
        *,
        guild_id: int,
        event_type: str,
        actor_user_id: int | None = None,
        payload: dict[str, object] | None = None,
    ) -> None:
        await self._writer.write(
            AuditEvent(
                guild_id=guild_id,
                actor_user_id=actor_user_id,
                event_type=event_type,
                payload=dict(payload or {}),
                created_at=datetime.now(timezone.utc),
            )
        )
