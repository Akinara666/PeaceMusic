"""PostgreSQL adapter with an optional import boundary for local tooling."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any


class PostgresDatabase:
    """Own one asyncpg pool and expose only application-level operations."""

    def __init__(self, url: str, *, min_size: int, max_size: int) -> None:
        self.url = url
        self.min_size = min_size
        self.max_size = max_size
        self._pool: Any = None

    @property
    def connected(self) -> bool:
        return self._pool is not None

    async def connect(self) -> None:
        if self._pool is not None:
            return
        try:
            import asyncpg
        except ImportError as exc:  # pragma: no cover - dependency guard
            raise RuntimeError(
                "PostgreSQL support requires the 'asyncpg' package."
            ) from exc
        self._pool = await asyncpg.create_pool(
            dsn=self.url,
            min_size=self.min_size,
            max_size=self.max_size,
        )

    async def healthcheck(self) -> bool:
        if self._pool is None:
            return False
        try:
            async with self._pool.acquire() as connection:
                await connection.fetchval("SELECT 1")
        except Exception:  # noqa: BLE001 - readiness must be a safe boolean
            return False
        return True

    @asynccontextmanager
    async def acquire(self) -> AsyncIterator[Any]:
        """Borrow a connection for a repository operation."""

        if self._pool is None:
            raise RuntimeError("PostgreSQL database is not connected")
        async with self._pool.acquire() as connection:
            yield connection

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
        self._pool = None
