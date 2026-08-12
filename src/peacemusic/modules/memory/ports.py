"""Persistence and embedding ports for long-term memory."""

from __future__ import annotations

from typing import Protocol, Sequence

from peacemusic.modules.memory.models import MemoryKind, MemoryRecord


class MemoryRepository(Protocol):
    async def put(self, record: MemoryRecord) -> None:
        """Persist or replace a memory record."""

    async def search(
        self,
        namespace: tuple[str, ...],
        query: str,
        *,
        kind: MemoryKind | None,
        limit: int,
    ) -> Sequence[MemoryRecord]:
        """Perform provider-side semantic retrieval within a namespace."""

    async def delete(self, namespace: tuple[str, ...], *, memory_id: str | None) -> int:
        """Delete one memory or all records in a namespace."""


class EmbeddingService(Protocol):
    async def embed(self, text: str) -> Sequence[float]:
        """Create an embedding for a provider-backed memory store."""
