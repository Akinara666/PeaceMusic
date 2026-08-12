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
