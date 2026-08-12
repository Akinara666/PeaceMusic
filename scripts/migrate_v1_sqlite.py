"""Import safe v1 SQLite data into the v2 PostgreSQL schema.

The importer intentionally excludes raw conversations and embedding BLOBs. Only
explicit guild settings, disabled users, muted channels, and text memories are
eligible for migration; semantic embeddings are recomputed by the v2 store.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

SAFE_SETTINGS_COLUMNS = {
    "language",
    "music_channel_id",
    "ai_channel_id",
    "default_volume",
    "max_volume",
    "max_queue_size",
    "autoplay_enabled",
    "track_announce",
    "idle_disconnect_timeout",
    "mode_24_7",
    "ai_enabled",
    "require_ai_mention",
    "ai_model",
    "ai_temperature",
    "memory_enabled",
}
MEMORY_TABLES = ("memory_records", "memories", "long_term_memory")


def _positive_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return value


def _memory_namespace(row: dict[str, Any]) -> tuple[str, ...]:
    guild_id = _positive_int(row["guild_id"])
    user_id = _positive_int(row.get("user_id"))
    channel_id = _positive_int(row.get("channel_id"))
    if user_id is not None:
        return ("guild", str(guild_id), "user", str(user_id), "memory")
    if channel_id is not None:
        return ("guild", str(guild_id), "channel", str(channel_id), "memory")
    return ("guild", str(guild_id), "memory")


def _memory_id(memory: dict[str, Any], namespace: tuple[str, ...]) -> str:
    digest = hashlib.sha256(
        json.dumps(
            [namespace, memory["content"]], ensure_ascii=True, sort_keys=True
        ).encode()
    ).hexdigest()
    return f"v1-{digest[:60]}"


def read_sqlite(path: Path) -> dict[str, list[dict[str, Any]]]:
    """Read known v1 tables as plain values without importing arbitrary blobs."""

    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        result: dict[str, list[dict[str, Any]]] = {}
        for table in (
            "guild_settings",
            "disabled_users",
            "channel_mutes",
            *MEMORY_TABLES,
        ):
            if table not in tables:
                continue
            rows = connection.execute(f'SELECT * FROM "{table}"').fetchall()
            result[table] = [dict(row) for row in rows]
        return result


def extract_text_memories(
    tables: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    """Normalize only explicit text memory rows for later PostgreSQL insertion."""

    memories: list[dict[str, Any]] = []
    for table in MEMORY_TABLES:
        for row in tables.get(table, []):
            content = row.get("content") or row.get("text") or row.get("memory")
            guild_id = _positive_int(row.get("guild_id"))
            if not isinstance(content, str) or not content.strip():
                continue
            if guild_id is None:
                continue
            memories.append(
                {
                    "guild_id": guild_id,
                    "user_id": row.get("user_id"),
                    "channel_id": row.get("channel_id"),
                    "content": content.strip(),
                    "kind": str(row.get("kind") or "semantic"),
                }
            )
    return memories


async def migrate(
    database_url: str, sqlite_path: Path, *, dry_run: bool = False
) -> dict[str, int]:
    """Migrate supported records and return per-category counts."""

    tables = read_sqlite(sqlite_path)
    summary = {
        "guild_settings": len(tables.get("guild_settings", [])),
        "disabled_users": len(tables.get("disabled_users", [])),
        "channel_mutes": len(tables.get("channel_mutes", [])),
        "memories": len(extract_text_memories(tables)),
    }
    if dry_run:
        return summary

    import asyncpg

    connection = await asyncpg.connect(database_url)
    try:
        for row in tables.get("guild_settings", []):
            guild_id = row.get("guild_id")
            if not isinstance(guild_id, int) or guild_id <= 0:
                continue
            columns = [column for column in SAFE_SETTINGS_COLUMNS if column in row]
            values = [row[column] for column in columns]
            if not columns:
                continue
            names = ", ".join(["guild_id", *columns])
            placeholders = ", ".join(f"${index}" for index in range(1, len(values) + 2))
            assignments = ", ".join(
                f"{column} = EXCLUDED.{column}" for column in columns
            )
            await connection.execute(
                f"INSERT INTO guild_settings ({names}) VALUES ({placeholders}) "
                f"ON CONFLICT (guild_id) DO UPDATE SET {assignments}",
                guild_id,
                *values,
            )

        for row in tables.get("disabled_users", []):
            if isinstance(row.get("guild_id"), int) and isinstance(
                row.get("user_id"), int
            ):
                await connection.execute(
                    "INSERT INTO disabled_users (guild_id, user_id) VALUES ($1, $2) "
                    "ON CONFLICT DO NOTHING",
                    row["guild_id"],
                    row["user_id"],
                )
        for row in tables.get("channel_mutes", []):
            guild_id = _positive_int(row.get("guild_id"))
            channel_id = _positive_int(row.get("channel_id"))
            if guild_id is not None and channel_id is not None:
                await connection.execute(
                    "INSERT INTO channel_mutes (guild_id, channel_id, silenced_at) "
                    "VALUES ($1, $2, CURRENT_TIMESTAMP) ON CONFLICT DO NOTHING",
                    guild_id,
                    channel_id,
                )
        imported_at = datetime.now(timezone.utc)
        for memory in extract_text_memories(tables):
            namespace = _memory_namespace(memory)
            kind = (
                memory["kind"]
                if memory["kind"] in {"semantic", "episodic"}
                else "semantic"
            )
            await connection.execute(
                """
                INSERT INTO memory_records
                    (memory_id, guild_id, namespace, kind, content, metadata,
                     created_at, expires_at)
                VALUES ($1, $2, $3::jsonb, $4, $5, $6::jsonb, $7, NULL)
                ON CONFLICT (memory_id) DO NOTHING
                """,
                _memory_id(memory, namespace),
                memory["guild_id"],
                json.dumps(namespace),
                kind,
                memory["content"],
                json.dumps({"source": "v1-sqlite"}),
                imported_at,
            )
    finally:
        await connection.close()
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sqlite_path", type=Path)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    summary = asyncio.run(
        migrate(args.database_url, args.sqlite_path, dry_run=args.dry_run)
    )
    print("Migration summary:", summary)


if __name__ == "__main__":
    main()
