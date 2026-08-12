"""PostgreSQL repository for long-term memory records."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from peacemusic.infrastructure.persistence.database import PostgresDatabase
from peacemusic.modules.memory.models import MemoryKind, MemoryRecord


class PostgresMemoryRepository:
    def __init__(self, database: PostgresDatabase) -> None:
        self._database = database

    async def put(self, record: MemoryRecord) -> None:
        async with self._database.acquire() as connection:
            await connection.execute(
                """
                INSERT INTO memory_records
                    (memory_id, guild_id, namespace, kind, content, metadata,
                     created_at, expires_at)
                VALUES ($1, $2, $3::jsonb, $4, $5, $6::jsonb, $7, $8)
                ON CONFLICT (memory_id) DO UPDATE SET
                    content = EXCLUDED.content,
                    metadata = EXCLUDED.metadata,
                    expires_at = EXCLUDED.expires_at
                """,
                record.memory_id,
                int(record.namespace[1]),
                json.dumps(record.namespace),
                record.kind.value,
                record.content,
                json.dumps(record.metadata),
                record.created_at,
                record.expires_at,
            )

    async def search(
        self,
        namespace: tuple[str, ...],
        query: str,
        *,
        kind: MemoryKind | None,
        limit: int,
    ) -> Sequence[MemoryRecord]:
        terms = [term for term in query.lower().split() if term]
        if not terms:
            return ()
        clauses = " OR ".join(
            f"content ILIKE ${index}" for index in range(3, 3 + len(terms))
        )
        kind_clause = ""
        args: list[object] = [json.dumps(namespace), limit]
        for term in terms:
            args.append(f"%{term}%")
        if kind is not None:
            kind_clause = f" AND kind = ${len(args) + 1}"
            args.append(kind.value)
        async with self._database.acquire() as connection:
            rows = await connection.fetch(
                f"""
                SELECT memory_id, namespace, kind, content, metadata,
                       created_at, expires_at
                  FROM memory_records
                 WHERE namespace = $1::jsonb AND ({clauses})
                   AND (expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP)
                   {kind_clause}
                 ORDER BY created_at DESC
                 LIMIT $2
                """,
                *args,
            )
        return [self._record(row) for row in rows]

    async def delete(self, namespace: tuple[str, ...], *, memory_id: str | None) -> int:
        async with self._database.acquire() as connection:
            if memory_id is not None:
                result = await connection.execute(
                    """
                    DELETE FROM memory_records
                     WHERE memory_id = $1 AND namespace = $2::jsonb
                    """,
                    memory_id,
                    json.dumps(namespace),
                )
            else:
                result = await connection.execute(
                    "DELETE FROM memory_records WHERE namespace = $1::jsonb",
                    json.dumps(namespace),
                )
        return int(result.split()[-1])

    async def count(self, namespace: tuple[str, ...]) -> int:
        async with self._database.acquire() as connection:
            return int(
                await connection.fetchval(
                    """
                    SELECT COUNT(*) FROM memory_records
                     WHERE namespace = $1::jsonb
                       AND (expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP)
                    """,
                    json.dumps(namespace),
                )
            )

    @staticmethod
    def _record(row: Any) -> MemoryRecord:
        return MemoryRecord(
            memory_id=row["memory_id"],
            namespace=tuple(row["namespace"]),
            kind=MemoryKind(row["kind"]),
            content=row["content"],
            metadata=dict(row["metadata"] or {}),
            created_at=row["created_at"],
            expires_at=row["expires_at"],
        )
