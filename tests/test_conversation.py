from __future__ import annotations

import asyncio

from peacemusic.modules.agent.conversation import (
    ConversationMessage,
    InMemoryConversationRepository,
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
