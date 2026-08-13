from __future__ import annotations

import asyncio
import pytest

from peacemusic.modules.agent.conversation import (
    ConversationMessage,
    InMemoryConversationRepository,
    compact_conversation,
    conversation_thread_id,
)


def test_in_memory_conversation_repository_returns_bounded_chronological_history() -> (
    None
):
    async def scenario() -> None:
        repository = InMemoryConversationRepository()
        await repository.append("thread", ConversationMessage("user", "one"))
        await repository.append("thread", ConversationMessage("assistant", "two"))
        await repository.append("thread", ConversationMessage("user", "three"))

        history = await repository.recent("thread", limit=2)

        assert [(message.role, message.content) for message in history] == [
            ("assistant", "two"),
            ("user", "three"),
        ]

    asyncio.run(scenario())


def test_conversation_compaction_keeps_recent_context_and_summary() -> None:
    messages = [
        ConversationMessage("user", "a" * 50),
        ConversationMessage("assistant", "b" * 50),
        ConversationMessage("user", "recent"),
    ]

    compacted = compact_conversation(messages, max_tokens=20)

    assert compacted[0].role == "system"
    assert "Earlier conversation summary" in compacted[0].content
    assert compacted[-1].content == "recent"


def test_conversation_boundaries_reject_invalid_compaction_and_empty_windows() -> None:
    repository = InMemoryConversationRepository()
    assert asyncio.run(repository.recent("thread", limit=0)) == ()
    with pytest.raises(ValueError):
        compact_conversation((), max_tokens=0)


def test_in_memory_conversation_repository_clears_one_thread_only() -> None:
    async def scenario() -> None:
        repository = InMemoryConversationRepository()
        current = conversation_thread_id(1, 2)
        other = conversation_thread_id(1, 3)
        await repository.append(current, ConversationMessage("user", "clear me"))
        await repository.append(other, ConversationMessage("user", "keep me"))

        assert await repository.clear(current) == 1
        assert await repository.recent(current, limit=10) == ()
        assert [
            message.content for message in await repository.recent(other, limit=10)
        ] == ["keep me"]

    asyncio.run(scenario())
