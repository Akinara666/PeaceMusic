"""Lifecycle adapter for LangGraph's PostgreSQL checkpointer and store."""

from __future__ import annotations

from typing import Any


class LangGraphPersistence:
    """Own LangGraph persistence resources from application startup to shutdown."""

    def __init__(
        self, database_url: str, *, embedding_api_key: str | None = None
    ) -> None:
        self.database_url = to_psycopg_database_url(database_url)
        self._embedding_api_key = embedding_api_key
        self._checkpointer_context: Any | None = None
        self._store_context: Any | None = None
        self._checkpointer: Any | None = None
        self._store: Any | None = None

    @property
    def checkpointer(self) -> Any:
        if self._checkpointer is None:
            raise RuntimeError("LangGraph persistence has not started")
        return self._checkpointer

    @property
    def store(self) -> Any:
        if self._store is None:
            raise RuntimeError("LangGraph persistence has not started")
        return self._store

    async def start(self) -> None:
        if self._checkpointer is not None:
            return
        try:
            from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
            from langgraph.store.postgres.aio import AsyncPostgresStore
        except ImportError as exc:  # pragma: no cover - deployment dependency
            raise RuntimeError(
                "LangGraph PostgreSQL persistence requires "
                "langgraph-checkpoint-postgres and psycopg."
            ) from exc

        self._checkpointer_context = AsyncPostgresSaver.from_conn_string(
            self.database_url
        )
        store_kwargs: dict[str, Any] = {}
        if self._embedding_api_key:
            from langgraph.store.base import IndexConfig
            from peacemusic.infrastructure.llm.embeddings import GeminiEmbeddingFunction

            store_kwargs["index"] = IndexConfig(
                embed=GeminiEmbeddingFunction(api_key=self._embedding_api_key),
                dims=768,
                fields=["content"],
            )
        self._store_context = AsyncPostgresStore.from_conn_string(
            self.database_url, **store_kwargs
        )
        try:
            self._checkpointer = await self._checkpointer_context.__aenter__()
            self._store = await self._store_context.__aenter__()
            await self._checkpointer.setup()
            await self._store.setup()
        except Exception:
            await self.stop()
            raise

    async def stop(self) -> None:
        if self._store_context is not None:
            await self._store_context.__aexit__(None, None, None)
        if self._checkpointer_context is not None:
            await self._checkpointer_context.__aexit__(None, None, None)
        self._store_context = None
        self._checkpointer_context = None
        self._store = None
        self._checkpointer = None

    async def clear_thread(self, thread_id: str) -> None:
        """Delete all LangGraph checkpoints for one conversation thread."""

        if self._checkpointer is None:
            raise RuntimeError("LangGraph persistence has not started")
        await self._checkpointer.adelete_thread(thread_id)


def to_psycopg_database_url(database_url: str) -> str:
    """Convert the application's asyncpg URL into a psycopg-compatible URL."""

    normalized = database_url.strip()
    if normalized.startswith("postgresql+asyncpg://"):
        return "postgresql://" + normalized.removeprefix("postgresql+asyncpg://")
    if normalized.startswith("postgres://") or normalized.startswith("postgresql://"):
        return normalized
    raise ValueError("LangGraph persistence requires a PostgreSQL database URL")
