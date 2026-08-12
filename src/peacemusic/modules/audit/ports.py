"""Audit persistence port."""

from __future__ import annotations

from typing import Protocol

from peacemusic.modules.audit.models import AuditEvent


class AuditWriter(Protocol):
    async def write(self, event: AuditEvent) -> None:
        """Persist one application audit event."""
