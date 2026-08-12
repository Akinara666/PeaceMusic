"""Checkpoint-safe outer graph state."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AttachmentRef(BaseModel):
    model_config = ConfigDict(frozen=True)

    attachment_id: str
    filename: str
    content_type: str | None = None
    size_bytes: int = Field(ge=0)


class ToolEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    tool_name: str
    ok: bool
    code: str
    message: str
    data: dict[str, Any] = Field(default_factory=dict)


class PeaceMusicState(BaseModel):
    """State suitable for LangGraph checkpoints; no runtime handles allowed."""

    model_config = ConfigDict(extra="forbid")

    request_id: str
    guild_id: int | None
    channel_id: int
    user_id: int
    discord_message_id: int | None = None
    input_text: str = ""
    attachments: list[AttachmentRef] = Field(default_factory=list)
    tool_events: list[ToolEvent] = Field(default_factory=list)
    final_response: str | None = None

    def checkpoint(self) -> dict[str, Any]:
        return self.model_dump(mode="json")
