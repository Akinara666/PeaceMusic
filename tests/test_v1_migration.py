from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

from scripts.migrate_v1_sqlite import extract_text_memories, migrate, read_sqlite


def test_v1_reader_imports_explicit_text_and_ignores_embedding_blobs(
    tmp_path: Path,
) -> None:
    database = tmp_path / "v1.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TABLE memories (guild_id INTEGER, user_id INTEGER, content TEXT, embedding BLOB)"
        )
        connection.execute(
            "INSERT INTO memories VALUES (1, 2, 'prefers ambient music', X'0102')"
        )
        connection.execute(
            "CREATE TABLE conversation_messages (guild_id INTEGER, content TEXT)"
        )
        connection.execute("INSERT INTO conversation_messages VALUES (1, 'raw chat')")
        connection.commit()

    tables = read_sqlite(database)
    memories = extract_text_memories(tables)

    assert memories == [
        {
            "guild_id": 1,
            "user_id": 2,
            "channel_id": None,
            "content": "prefers ambient music",
            "kind": "semantic",
        }
    ]
    assert "conversation_messages" not in tables


def test_v1_migration_dry_run_reports_only_supported_records(tmp_path: Path) -> None:
    database = tmp_path / "v1.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE guild_settings (guild_id INTEGER)")
        connection.execute("INSERT INTO guild_settings VALUES (1)")
        connection.execute(
            "CREATE TABLE long_term_memory (guild_id INTEGER, text TEXT)"
        )
        connection.execute("INSERT INTO long_term_memory VALUES (1, 'ambient')")
        connection.commit()

    summary = asyncio.run(migrate("postgresql://unused", database, dry_run=True))

    assert summary == {
        "guild_settings": 1,
        "disabled_users": 0,
        "channel_mutes": 0,
        "memories": 1,
    }
