"""Bounded short-term conversation history for agent turns."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True, slots=True)
class ConversationMessage:
    """A serializable message safe to pass into an agent invocation."""

    role: str
    content: str
    created_at: datetime | None = None

    def as_message(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}


class ConversationRepository(Protocol):
    async def recent(
        self, thread_id: str, *, limit: int
    ) -> Sequence[ConversationMessage]:
        """Return the oldest-to-newest messages retained for a thread."""

    async def append(self, thread_id: str, message: ConversationMessage) -> None:
        """Append one message to a thread."""


def compact_conversation(
    messages: Sequence[ConversationMessage], *, max_tokens: int
) -> Sequence[ConversationMessage]:
    """Keep recent messages and a bounded summary for oversized contexts."""

    if max_tokens < 1:
        raise ValueError("max_tokens must be positive")
    budget = max_tokens * 4
    if sum(len(message.content) for message in messages) <= budget:
        return tuple(messages)

    summary_budget = min(800, max(32, budget // 4))
    recent: list[ConversationMessage] = []
    used = summary_budget
    for message in reversed(messages):
        if used + len(message.content) > budget:
            break
        recent.append(message)
        used += len(message.content)
    recent.reverse()
    omitted = messages[: len(messages) - len(recent)]
    summary = " | ".join(
        f"{message.role}: {message.content.strip()}" for message in omitted
    )[:summary_budget]
    return (
        ConversationMessage(
            role="system",
            content=f"Earlier conversation summary: {summary}",
        ),
        *recent,
    )


class InMemoryConversationRepository:
    """Deterministic repository for unit tests and local development."""

    def __init__(self) -> None:
        self.messages: defaultdict[str, list[ConversationMessage]] = defaultdict(list)

    async def recent(
        self, thread_id: str, *, limit: int
    ) -> Sequence[ConversationMessage]:
        if limit < 1:
            return ()
        return tuple(self.messages[thread_id][-limit:])

    async def append(self, thread_id: str, message: ConversationMessage) -> None:
        self.messages[thread_id].append(message)
