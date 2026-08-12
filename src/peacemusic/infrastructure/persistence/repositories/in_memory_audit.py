"""Deterministic audit writer for tests."""

from __future__ import annotations

from peacemusic.modules.audit.models import AuditEvent


class InMemoryAuditWriter:
    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    async def write(self, event: AuditEvent) -> None:
        self.events.append(event)
