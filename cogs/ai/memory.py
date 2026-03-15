from __future__ import annotations

import asyncio
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional, Sequence

import numpy as np

@dataclass(frozen=True)
class StoredMessage:
    id: int
    channel_id: int
    discord_message_id: Optional[int]
    role: str
    author_id: Optional[int]
    author_name: str
    content_text: str
    created_at: str
    embedding_model: Optional[str] = None

    @property
    def formatted_text(self) -> str:
        if self.content_text:
            return f"[{self.created_at}] {self.author_name}: {self.content_text}"
        return f"[{self.created_at}] {self.author_name}"


@dataclass(frozen=True)
class SemanticMatch(StoredMessage):
    score: float = 0.0


@dataclass(frozen=True)
class ChatState:
    channel_id: int
    summary: str
    last_summarized_message_id: int
    updated_at: Optional[str] = None


class MemoryStore:
    """Persist chat memory and embeddings in a local SQLite database."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._write_lock = asyncio.Lock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS chat_state (
                    channel_id INTEGER PRIMARY KEY,
                    summary TEXT NOT NULL DEFAULT '',
                    last_summarized_message_id INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel_id INTEGER NOT NULL,
                    discord_message_id INTEGER,
                    role TEXT NOT NULL,
                    author_id INTEGER,
                    author_name TEXT NOT NULL,
                    content_text TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    embedding BLOB,
                    embedding_dim INTEGER,
                    embedding_model TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_messages_channel_recent
                    ON messages(channel_id, id DESC);
                CREATE INDEX IF NOT EXISTS idx_messages_channel_embeddings
                    ON messages(channel_id, embedding_model, id DESC);
                """
            )

    async def store_message(
        self,
        *,
        channel_id: int,
        discord_message_id: Optional[int],
        role: str,
        author_id: Optional[int],
        author_name: str,
        content_text: str,
        created_at: str,
        embedding: Optional[np.ndarray],
        embedding_model: Optional[str],
    ) -> StoredMessage:
        if embedding is not None:
            normalized = np.ascontiguousarray(np.asarray(embedding, dtype=np.float32))
            embedding_blob = normalized.tobytes()
            embedding_dim = int(normalized.shape[0])
        else:
            embedding_blob = None
            embedding_dim = None

        def _store() -> StoredMessage:
            with self._connect() as conn:
                cursor = conn.execute(
                    """
                    INSERT INTO messages (
                        channel_id,
                        discord_message_id,
                        role,
                        author_id,
                        author_name,
                        content_text,
                        created_at,
                        embedding,
                        embedding_dim,
                        embedding_model
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        channel_id,
                        discord_message_id,
                        role,
                        author_id,
                        author_name,
                        content_text,
                        created_at,
                        embedding_blob,
                        embedding_dim,
                        embedding_model,
                    ),
                )
                message_id = int(cursor.lastrowid)
                conn.execute(
                    "INSERT OR IGNORE INTO chat_state(channel_id) VALUES (?)",
                    (channel_id,),
                )
                return StoredMessage(
                    id=message_id,
                    channel_id=channel_id,
                    discord_message_id=discord_message_id,
                    role=role,
                    author_id=author_id,
                    author_name=author_name,
                    content_text=content_text,
                    created_at=created_at,
                    embedding_model=embedding_model,
                )

        async with self._write_lock:
            return await asyncio.to_thread(_store)

    async def get_recent_messages(
        self, channel_id: int, limit: int
    ) -> list[StoredMessage]:
        def _load() -> list[StoredMessage]:
            with self._connect() as conn:
                rows = conn.execute(
                    """
                    SELECT
                        id,
                        channel_id,
                        discord_message_id,
                        role,
                        author_id,
                        author_name,
                        content_text,
                        created_at,
                        embedding_model
                    FROM messages
                    WHERE channel_id = ?
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (channel_id, limit),
                ).fetchall()
            messages = [self._row_to_message(row) for row in rows]
            messages.reverse()
            return messages

        return await asyncio.to_thread(_load)

    async def get_chat_state(self, channel_id: int) -> ChatState:
        def _load() -> ChatState:
            with self._connect() as conn:
                conn.execute(
                    "INSERT OR IGNORE INTO chat_state(channel_id) VALUES (?)",
                    (channel_id,),
                )
                row = conn.execute(
                    """
                    SELECT channel_id, summary, last_summarized_message_id, updated_at
                    FROM chat_state
                    WHERE channel_id = ?
                    """,
                    (channel_id,),
                ).fetchone()
            if row is None:  # pragma: no cover - guarded by INSERT OR IGNORE
                return ChatState(
                    channel_id=channel_id,
                    summary="",
                    last_summarized_message_id=0,
                )
            return ChatState(
                channel_id=int(row["channel_id"]),
                summary=row["summary"] or "",
                last_summarized_message_id=int(row["last_summarized_message_id"] or 0),
                updated_at=row["updated_at"],
            )

        return await asyncio.to_thread(_load)

    async def update_chat_state(
        self,
        *,
        channel_id: int,
        summary: str,
        last_summarized_message_id: int,
    ) -> None:
        def _write() -> None:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO chat_state(
                        channel_id,
                        summary,
                        last_summarized_message_id,
                        updated_at
                    )
                    VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(channel_id) DO UPDATE SET
                        summary = excluded.summary,
                        last_summarized_message_id = excluded.last_summarized_message_id,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (channel_id, summary, last_summarized_message_id),
                )

        async with self._write_lock:
            await asyncio.to_thread(_write)

    async def count_unsummarized_messages(
        self, channel_id: int, after_message_id: int
    ) -> int:
        def _count() -> int:
            with self._connect() as conn:
                row = conn.execute(
                    """
                    SELECT COUNT(*) AS count
                    FROM messages
                    WHERE channel_id = ? AND id > ?
                    """,
                    (channel_id, after_message_id),
                ).fetchone()
            return int(row["count"] if row is not None else 0)

        return await asyncio.to_thread(_count)

    async def get_recent_summary_window(
        self, channel_id: int, limit: int
    ) -> tuple[int, list[StoredMessage]]:
        def _load() -> tuple[int, list[StoredMessage]]:
            with self._connect() as conn:
                rows = conn.execute(
                    """
                    SELECT
                        id,
                        channel_id,
                        discord_message_id,
                        role,
                        author_id,
                        author_name,
                        content_text,
                        created_at,
                        embedding_model
                    FROM messages
                    WHERE channel_id = ?
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (channel_id, limit),
                ).fetchall()
            if not rows:
                return 0, []
            latest_id = int(rows[0]["id"])
            messages = [self._row_to_message(row) for row in rows]
            messages.reverse()
            return latest_id, messages

        return await asyncio.to_thread(_load)

    async def get_semantic_matches(
        self,
        *,
        channel_id: int,
        query_embedding: np.ndarray,
        embedding_model: str,
        limit: int,
        min_score: float = 0.35,
        exclude_ids: Sequence[int] = (),
    ) -> list[SemanticMatch]:
        query = np.ascontiguousarray(np.asarray(query_embedding, dtype=np.float32))
        excluded = set(exclude_ids)

        def _search() -> list[SemanticMatch]:
            with self._connect() as conn:
                rows = conn.execute(
                    """
                    SELECT
                        id,
                        channel_id,
                        discord_message_id,
                        role,
                        author_id,
                        author_name,
                        content_text,
                        created_at,
                        embedding,
                        embedding_model
                    FROM messages
                    WHERE channel_id = ?
                      AND embedding_model = ?
                      AND embedding IS NOT NULL
                    ORDER BY id DESC
                    """,
                    (channel_id, embedding_model),
                ).fetchall()

            if not rows:
                return []

            vectors: list[np.ndarray] = []
            messages: list[StoredMessage] = []
            for row in rows:
                if int(row["id"]) in excluded:
                    continue
                raw_embedding = row["embedding"]
                if raw_embedding is None:
                    continue
                vector = np.frombuffer(raw_embedding, dtype=np.float32)
                if vector.size != query.size:
                    continue
                vectors.append(vector)
                messages.append(self._row_to_message(row))

            if not vectors:
                return []

            matrix = np.vstack(vectors)
            scores = matrix @ query
            top_count = min(limit, scores.shape[0])
            if top_count < 1:
                return []

            top_indices = np.argpartition(scores, -top_count)[-top_count:]
            ranked = top_indices[np.argsort(scores[top_indices])[::-1]]

            matches: list[SemanticMatch] = []
            for idx in ranked:
                score = float(scores[idx])
                if score < min_score:
                    continue
                message = messages[int(idx)]
                matches.append(
                    SemanticMatch(
                        **message.__dict__,
                        score=score,
                    )
                )
            return matches

        return await asyncio.to_thread(_search)

    def _row_to_message(self, row: sqlite3.Row) -> StoredMessage:
        return StoredMessage(
            id=int(row["id"]),
            channel_id=int(row["channel_id"]),
            discord_message_id=row["discord_message_id"],
            role=row["role"],
            author_id=row["author_id"],
            author_name=row["author_name"],
            content_text=row["content_text"],
            created_at=row["created_at"],
            embedding_model=row["embedding_model"],
        )


def format_memory_block(
    messages: Iterable[StoredMessage],
    *,
    include_scores: bool = False,
) -> str:
    lines: list[str] = []
    for message in messages:
        prefix = ""
        if include_scores and isinstance(message, SemanticMatch):
            prefix = f"(score={message.score:.3f}) "
        lines.append(f"{prefix}{message.formatted_text}")
    return "\n".join(lines)
