"""In-memory memory repository for deterministic unit tests."""

from __future__ import annotations

from collections.abc import Sequence

from peacemusic.modules.memory.models import MemoryKind, MemoryRecord


class InMemoryMemoryRepository:
    def __init__(self) -> None:
        self.records: dict[str, MemoryRecord] = {}

    async def put(self, record: MemoryRecord) -> None:
        self.records[record.memory_id] = record

    async def search(
        self,
        namespace: tuple[str, ...],
        query: str,
        *,
        kind: MemoryKind | None,
        limit: int,
    ) -> Sequence[MemoryRecord]:
        query_terms = set(query.lower().split())
        matches = [
            record
            for record in self.records.values()
            if record.namespace == namespace
            and (kind is None or record.kind is kind)
            and query_terms.intersection(record.content.lower().split())
        ]
        return matches[:limit]

    async def delete(self, namespace: tuple[str, ...], *, memory_id: str | None) -> int:
        if memory_id is not None:
            record = self.records.get(memory_id)
            if record is None or record.namespace != namespace:
                return 0
            del self.records[memory_id]
            return 1
        ids = [
            record_id
            for record_id, record in self.records.items()
            if record.namespace == namespace
        ]
        for record_id in ids:
            del self.records[record_id]
        return len(ids)
