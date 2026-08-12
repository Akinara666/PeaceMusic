"""LangGraph Store-backed semantic memory repository."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Any

from peacemusic.infrastructure.llm.langgraph_persistence import LangGraphPersistence
from peacemusic.modules.memory.models import MemoryKind, MemoryRecord


class LangGraphMemoryRepository:
    """Map application memory records onto LangGraph Store documents."""

    def __init__(self, persistence: LangGraphPersistence) -> None:
        self._persistence = persistence

    async def put(self, record: MemoryRecord) -> None:
        value = {
            "content": record.content,
            "kind": record.kind.value,
            "metadata": record.metadata,
            "created_at": record.created_at.isoformat(),
            "expires_at": record.expires_at.isoformat() if record.expires_at else None,
        }
        await self._persistence.store.aput(
            record.namespace,
            record.memory_id,
            value,
            index=["content"],
        )

    async def search(
        self,
        namespace: tuple[str, ...],
        query: str,
        *,
        kind: MemoryKind | None,
        limit: int,
    ) -> Sequence[MemoryRecord]:
        filters = {"kind": kind.value} if kind is not None else None
        items = await self._persistence.store.asearch(
            namespace,
            query=query,
            filter=filters,
            limit=limit,
        )
        return [
            record
            for item in items
            if (record := self._record(item)) is not None and self._is_live(record)
        ]

    async def delete(self, namespace: tuple[str, ...], *, memory_id: str | None) -> int:
        if memory_id is not None:
            item = await self._persistence.store.aget(namespace, memory_id)
            if item is None:
                return 0
            await self._persistence.store.adelete(namespace, memory_id)
            return 1
        items = await self._persistence.store.asearch(namespace, limit=10_000)
        deleted = 0
        for item in items:
            await self._persistence.store.adelete(namespace, item.key)
            deleted += 1
        return deleted

    async def count(self, namespace: tuple[str, ...]) -> int:
        items = await self._persistence.store.asearch(namespace, limit=10_000)
        return sum(
            1
            for item in items
            if (record := self._record(item)) is not None and self._is_live(record)
        )

    @staticmethod
    def _record(item: Any) -> MemoryRecord | None:
        value = dict(getattr(item, "value", {}) or {})
        content = value.get("content")
        if not isinstance(content, str) or not content:
            return None
        created_at = _parse_datetime(value.get("created_at"))
        if created_at is None:
            return None
        expires_at = _parse_datetime(value.get("expires_at"))
        metadata = {
            str(key): str(item_value)
            for key, item_value in dict(value.get("metadata", {}) or {}).items()
        }
        return MemoryRecord(
            memory_id=str(getattr(item, "key", "")),
            namespace=tuple(getattr(item, "namespace", ())),
            kind=MemoryKind(value.get("kind", MemoryKind.SEMANTIC.value)),
            content=content,
            created_at=created_at,
            expires_at=expires_at,
            metadata=metadata,
        )

    @staticmethod
    def _is_live(record: MemoryRecord) -> bool:
        return record.expires_at is None or record.expires_at > datetime.now(
            timezone.utc
        )


def _parse_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return None
