from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from tests.stub_modules import install_stubs, load_project_module

install_stubs()
memory_module = load_project_module("test_memory_module", "cogs/ai/memory.py")

MemoryStore = memory_module.MemoryStore
SemanticMatch = memory_module.SemanticMatch
format_memory_block = memory_module.format_memory_block
np = memory_module.np


class MemoryStoreTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self._to_thread_patcher = patch.object(
            memory_module.asyncio,
            "to_thread",
            new=AsyncMock(side_effect=self._fake_to_thread),
        )
        self._to_thread_patcher.start()
        self.addCleanup(self._to_thread_patcher.stop)
        self.store = MemoryStore(Path(self._tmpdir.name) / "memory.sqlite3")

    async def _fake_to_thread(self, func, *args, **kwargs):
        return func(*args, **kwargs)

    async def test_store_and_retrieve_recent_messages(self) -> None:
        await self.store.store_message(
            channel_id=1,
            discord_message_id=10,
            role="user",
            author_id=100,
            author_name="alice",
            content_text="first",
            created_at="2026-03-15 12:00:00",
            embedding=np.asarray([1.0, 0.0], dtype=np.float32),
            embedding_model="embed-model",
        )
        await self.store.store_message(
            channel_id=1,
            discord_message_id=11,
            role="model",
            author_id=200,
            author_name="mia",
            content_text="second",
            created_at="2026-03-15 12:01:00",
            embedding=None,
            embedding_model=None,
        )

        recent = await self.store.get_recent_messages(1, 10)

        self.assertEqual([item.content_text for item in recent], ["first", "second"])
        self.assertEqual(recent[0].formatted_text, "[2026-03-15 12:00:00] alice: first")

    async def test_chat_state_and_summary_window(self) -> None:
        first = await self.store.store_message(
            channel_id=5,
            discord_message_id=21,
            role="user",
            author_id=300,
            author_name="bob",
            content_text="hello",
            created_at="2026-03-15 15:00:00",
            embedding=np.asarray([0.0, 1.0], dtype=np.float32),
            embedding_model="embed-model",
        )
        await self.store.store_message(
            channel_id=5,
            discord_message_id=22,
            role="model",
            author_id=400,
            author_name="mia",
            content_text="hi",
            created_at="2026-03-15 15:01:00",
            embedding=np.asarray([1.0, 0.0], dtype=np.float32),
            embedding_model="embed-model",
        )

        state = await self.store.get_chat_state(5)
        self.assertEqual(state.summary, "")
        self.assertEqual(state.last_summarized_message_id, 0)

        unsummarized = await self.store.count_unsummarized_messages(5, first.id)
        self.assertEqual(unsummarized, 1)

        latest_id, window = await self.store.get_recent_summary_window(5, 1)
        self.assertEqual(latest_id, window[0].id)
        self.assertEqual(window[0].content_text, "hi")

        await self.store.update_chat_state(
            channel_id=5,
            summary="summary text",
            last_summarized_message_id=latest_id,
        )
        updated_state = await self.store.get_chat_state(5)
        self.assertEqual(updated_state.summary, "summary text")
        self.assertEqual(updated_state.last_summarized_message_id, latest_id)

    async def test_semantic_matches_respect_score_and_exclusions(self) -> None:
        first = await self.store.store_message(
            channel_id=7,
            discord_message_id=31,
            role="user",
            author_id=1,
            author_name="alice",
            content_text="cats",
            created_at="2026-03-15 18:00:00",
            embedding=np.asarray([1.0, 0.0], dtype=np.float32),
            embedding_model="embed-model",
        )
        await self.store.store_message(
            channel_id=7,
            discord_message_id=32,
            role="user",
            author_id=2,
            author_name="bob",
            content_text="dogs",
            created_at="2026-03-15 18:01:00",
            embedding=np.asarray([0.0, 1.0], dtype=np.float32),
            embedding_model="embed-model",
        )

        matches = await self.store.get_semantic_matches(
            channel_id=7,
            query_embedding=np.asarray([1.0, 0.0], dtype=np.float32),
            embedding_model="embed-model",
            limit=2,
            min_score=0.2,
        )

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].content_text, "cats")
        self.assertAlmostEqual(matches[0].score, 1.0, places=4)

        excluded_matches = await self.store.get_semantic_matches(
            channel_id=7,
            query_embedding=np.asarray([1.0, 0.0], dtype=np.float32),
            embedding_model="embed-model",
            limit=2,
            min_score=0.0,
            exclude_ids=[first.id],
        )
        self.assertEqual([match.content_text for match in excluded_matches], ["dogs"])

    async def test_format_memory_block_with_scores(self) -> None:
        match = SemanticMatch(
            id=1,
            channel_id=1,
            discord_message_id=1,
            role="user",
            author_id=1,
            author_name="alice",
            content_text="hello",
            created_at="2026-03-15 19:00:00",
            embedding_model="embed-model",
            score=0.75,
        )

        block = format_memory_block([match], include_scores=True)

        self.assertEqual(block, "(score=0.750) [2026-03-15 19:00:00] alice: hello")

    async def test_format_memory_block_can_omit_timestamps(self) -> None:
        match = SemanticMatch(
            id=1,
            channel_id=1,
            discord_message_id=1,
            role="user",
            author_id=1,
            author_name="alice",
            content_text="hello",
            created_at="2026-03-15 19:00:00",
            embedding_model="embed-model",
            score=0.75,
        )

        block = format_memory_block(
            [match],
            include_scores=True,
            include_timestamps=False,
        )

        self.assertEqual(block, "(score=0.750) alice: hello")

    async def test_directory_database_path_falls_back_to_nested_file(self) -> None:
        db_dir = Path(self._tmpdir.name) / "chat_memory.sqlite3"
        db_dir.mkdir()
        store = MemoryStore(db_dir)

        await store.store_message(
            channel_id=9,
            discord_message_id=41,
            role="user",
            author_id=1,
            author_name="alice",
            content_text="hello",
            created_at="2026-03-15 20:00:00",
            embedding=None,
            embedding_model=None,
        )

        self.assertTrue((db_dir / "chat_memory.sqlite3").exists())

    async def test_store_and_retrieve_content_parts(self) -> None:
        await self.store.store_message(
            channel_id=11,
            discord_message_id=51,
            role="user",
            author_id=100,
            author_name="alice",
            content_text="[Image attachment: cat.png]",
            created_at="2026-03-15 21:00:00",
            embedding=None,
            embedding_model=None,
            content_parts=(
                {"type": "file_data", "uri": "uri://image", "mime_type": "image/png"},
                {"type": "text", "text": "[2026-03-15 21:00:00] alice [Image attachment: cat.png]"},
            ),
        )

        recent = await self.store.get_recent_messages(11, 10)

        self.assertEqual(len(recent), 1)
        self.assertEqual(
            recent[0].content_parts,
            (
                {"type": "file_data", "uri": "uri://image", "mime_type": "image/png"},
                {
                    "type": "text",
                    "text": "[2026-03-15 21:00:00] alice [Image attachment: cat.png]",
                },
            ),
        )

    async def test_silent_channel_persistence_round_trip(self) -> None:
        self.assertEqual(await self.store.get_silent_channels(), {})

        await self.store.set_channel_silenced(77, "2026-04-30T12:00:00+03:00")
        self.assertEqual(
            await self.store.get_silent_channels(),
            {77: "2026-04-30T12:00:00+03:00"},
        )

        # Idempotent overwrite keeps the latest value.
        await self.store.set_channel_silenced(77, "2026-04-30T13:00:00+03:00")
        self.assertEqual(
            await self.store.get_silent_channels(),
            {77: "2026-04-30T13:00:00+03:00"},
        )

        await self.store.set_channel_silenced(77, None)
        self.assertEqual(await self.store.get_silent_channels(), {})

    async def test_disable_and_enable_user(self) -> None:
        self.assertFalse(await self.store.is_user_disabled(100, 200))

        await self.store.set_user_disabled(100, 200, disabled=True)

        self.assertTrue(await self.store.is_user_disabled(100, 200))
        self.assertEqual(await self.store.get_disabled_user_ids(100), {200})

        await self.store.set_user_disabled(100, 200, disabled=False)

        self.assertFalse(await self.store.is_user_disabled(100, 200))
        self.assertEqual(await self.store.get_disabled_user_ids(100), set())

    async def test_existing_database_is_migrated_with_content_parts_column(self) -> None:
        legacy_db = Path(self._tmpdir.name) / "legacy.sqlite3"
        with sqlite3.connect(legacy_db) as conn:
            conn.executescript(
                """
                CREATE TABLE messages (
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
                CREATE TABLE chat_state (
                    channel_id INTEGER PRIMARY KEY,
                    summary TEXT NOT NULL DEFAULT '',
                    last_summarized_message_id INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                """
            )

        store = MemoryStore(legacy_db)
        await store.store_message(
            channel_id=12,
            discord_message_id=52,
            role="user",
            author_id=101,
            author_name="alice",
            content_text="hello",
            created_at="2026-03-15 21:01:00",
            embedding=None,
            embedding_model=None,
            content_parts=({"type": "text", "text": "[2026-03-15 21:01:00] alice: hello"},),
        )

        recent = await store.get_recent_messages(12, 10)

        self.assertEqual(recent[0].content_parts[0]["type"], "text")
