"""Bounded short-term conversation history for agent turns."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True, slots=True)
class ConversationMedia:
    """Provider-owned media reference retained in conversation context."""

    name: str
    uri: str
    mime_type: str

    def as_content(self) -> dict[str, str]:
        return {
            "type": "media",
            "file_uri": self.uri,
            "mime_type": self.mime_type,
        }


@dataclass(frozen=True, slots=True)
class ConversationMessage:
    """A serializable message safe to pass into an agent invocation."""

    role: str
    content: str
    created_at: datetime | None = None
    media: tuple[ConversationMedia, ...] = ()

    def without_media(self) -> "ConversationMessage":
        """Return the same message without provider-owned media references."""

        return ConversationMessage(
            role=self.role,
            content=self.content,
            created_at=self.created_at,
        )

    def as_message(self) -> dict[str, object]:
        if self.media:
            return {
                "role": self.role,
                "content": [
                    {"type": "text", "text": self.content},
                    *(item.as_content() for item in self.media),
                ],
            }
        return {"role": self.role, "content": self.content}

    def media_payload(self) -> list[dict[str, str]]:
        """Return provider references in a JSON/database-safe shape."""

        return [
            {
                "name": item.name,
                "uri": item.uri,
                "mime_type": item.mime_type,
            }
            for item in self.media
        ]


class ConversationRepository(Protocol):
    async def recent(
        self, thread_id: str, *, limit: int
    ) -> Sequence[ConversationMessage]:
        """Return the oldest-to-newest messages retained for a thread."""

    async def append(self, thread_id: str, message: ConversationMessage) -> None:
        """Append one message to a thread."""

    async def clear(self, thread_id: str) -> int:
        """Delete all persisted messages for a thread and return the count."""

    async def clear_media(self, thread_id: str) -> int:
        """Remove provider media references while retaining message text."""


def conversation_thread_id(guild_id: int, channel_id: int) -> str:
    """Return the stable short-term conversation key for a guild channel."""

    return f"guild:{guild_id}:channel:{channel_id}"


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
    recent_indices: list[int] = []
    used = summary_budget
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        if message.media:
            continue
        if used + len(message.content) > budget:
            break
        recent_indices.append(index)
        used += len(message.content)
    selected_indices = set(recent_indices)
    selected_indices.update(
        index for index, message in enumerate(messages) if message.media
    )
    selected = tuple(
        message for index, message in enumerate(messages) if index in selected_indices
    )
    omitted = tuple(
        message
        for index, message in enumerate(messages)
        if index not in selected_indices
    )
    summary = " | ".join(
        f"{message.role}: {message.content.strip()}" for message in omitted
    )[:summary_budget]
    return (
        ConversationMessage(
            role="system",
            content=f"Earlier conversation summary: {summary}",
        ),
        *selected,
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

    async def clear(self, thread_id: str) -> int:
        messages = self.messages.pop(thread_id, [])
        return len(messages)

    async def clear_media(self, thread_id: str) -> int:
        messages = self.messages.get(thread_id, [])
        cleared = 0
        for index, message in enumerate(messages):
            if message.media:
                messages[index] = message.without_media()
                cleared += 1
        return cleared
