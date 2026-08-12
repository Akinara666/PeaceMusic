from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

from peacemusic.infrastructure.persistence.repositories.langgraph_memory import (
    LangGraphMemoryRepository,
)
from peacemusic.modules.memory.models import MemoryKind, MemoryRecord


class Store:
    def __init__(self) -> None:
        self.values = {}

    async def aput(self, namespace, key, value, *, index):
        self.values[(tuple(namespace), key)] = SimpleNamespace(
            namespace=tuple(namespace), key=key, value=value
        )

    async def asearch(self, namespace, **kwargs):
        return [
            item
            for (item_namespace, _), item in self.values.items()
            if item_namespace == tuple(namespace)
        ]

    async def aget(self, namespace, key):
        return self.values.get((tuple(namespace), key))

    async def adelete(self, namespace, key):
        self.values.pop((tuple(namespace), key), None)


class Persistence:
    def __init__(self) -> None:
        self.store = Store()


def test_langgraph_memory_repository_round_trips_records() -> None:
    async def scenario() -> None:
        repository = LangGraphMemoryRepository(Persistence())
        record = MemoryRecord(
            memory_id="m1",
            namespace=("guild", "1", "user", "2", "memory"),
            kind=MemoryKind.SEMANTIC,
            content="User likes ambient music",
            created_at=datetime.now(timezone.utc),
        )

        await repository.put(record)
        matches = await repository.search(
            record.namespace, "ambient", kind=None, limit=5
        )

        assert matches[0].content == record.content
        assert await repository.count(record.namespace) == 1
        assert await repository.delete(record.namespace, memory_id="m1") == 1

    asyncio.run(scenario())


def test_langgraph_memory_repository_ignores_invalid_and_expired_values() -> None:
    async def scenario() -> None:
        persistence = Persistence()
        repository = LangGraphMemoryRepository(persistence)
        namespace = ("guild", "1", "memory")
        persistence.store.values[(namespace, "bad")] = SimpleNamespace(
            namespace=namespace,
            key="bad",
            value={"content": "", "created_at": "not-a-date"},
        )
        assert await repository.count(namespace) == 0
        assert await repository.delete(namespace, memory_id="missing") == 0
        assert await repository.delete(namespace, memory_id=None) == 1

    asyncio.run(scenario())
