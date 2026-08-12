"""Bounded semantic and episodic memory records."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class MemoryKind(StrEnum):
    SEMANTIC = "semantic"
    EPISODIC = "episodic"


class MemoryRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    memory_id: str
    namespace: tuple[str, ...]
    kind: MemoryKind
    content: str = Field(min_length=1, max_length=10_000)
    created_at: datetime
    expires_at: datetime | None = None
    metadata: dict[str, str] = Field(default_factory=dict)
