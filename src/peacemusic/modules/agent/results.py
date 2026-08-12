"""Shared result contract for model-facing tools."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ToolResult(BaseModel):
    ok: bool
    code: str
    message: str
    data: dict[str, Any] = Field(default_factory=dict)
    user_notified: bool = False

    @classmethod
    def success(
        cls, message: str, *, data: dict[str, Any] | None = None
    ) -> "ToolResult":
        return cls(ok=True, code="OK", message=message, data=data or {})

    @classmethod
    def failure(
        cls, code: str, message: str, *, data: dict[str, Any] | None = None
    ) -> "ToolResult":
        return cls(ok=False, code=code, message=message, data=data or {})
