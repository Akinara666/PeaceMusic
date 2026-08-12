"""Checkpoint-safe audit event model."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class AuditEvent:
    guild_id: int
    actor_user_id: int | None
    event_type: str
    payload: dict[str, object]
    created_at: datetime
