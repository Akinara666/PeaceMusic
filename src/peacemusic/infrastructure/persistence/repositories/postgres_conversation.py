"""PostgreSQL repository for bounded agent conversation history."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Any

from peacemusic.infrastructure.persistence.database import PostgresDatabase
from peacemusic.modules.agent.conversation import ConversationMessage


class PostgresConversationRepository:
    """Persist only serializable user/assistant messages for each thread."""

    def __init__(self, database: PostgresDatabase, *, max_messages: int = 40) -> None:
        if max_messages < 1:
            raise ValueError("max_messages must be positive")
        self._database = database
        self._max_messages = max_messages

    async def recent(
        self, thread_id: str, *, limit: int
    ) -> Sequence[ConversationMessage]:
        if limit < 1:
            return ()
        selected_limit = min(limit, self._max_messages)
        async with self._database.acquire() as connection:
            rows = await connection.fetch(
                """
                SELECT role, content, created_at
                  FROM (
                        SELECT id, role, content, created_at
                          FROM conversation_messages
                         WHERE thread_id = $1
                         ORDER BY id DESC
                         LIMIT $2
                       ) recent
                 ORDER BY id ASC
                """,
                thread_id,
                selected_limit,
            )
        return [self._message(row) for row in rows]

    async def append(self, thread_id: str, message: ConversationMessage) -> None:
        created_at = message.created_at or datetime.now(timezone.utc)
        async with self._database.acquire() as connection:
            async with connection.transaction():
                await connection.execute(
                    """
                    INSERT INTO conversation_messages
                        (thread_id, role, content, created_at)
                    VALUES ($1, $2, $3, $4)
                    """,
                    thread_id,
                    message.role,
                    message.content,
                    created_at,
                )
                await connection.execute(
                    """
                    DELETE FROM conversation_messages
                     WHERE thread_id = $1
                       AND id NOT IN (
                           SELECT id
                             FROM conversation_messages
                            WHERE thread_id = $1
                            ORDER BY id DESC
                            LIMIT $2
                       )
                    """,
                    thread_id,
                    self._max_messages,
                )

    async def clear(self, thread_id: str) -> int:
        async with self._database.acquire() as connection:
            result = await connection.execute(
                "DELETE FROM conversation_messages WHERE thread_id = $1",
                thread_id,
            )
        return int(result.split()[-1])

    @staticmethod
    def _message(row: Any) -> ConversationMessage:
        return ConversationMessage(
            role=row["role"],
            content=row["content"],
            created_at=row["created_at"],
        )
