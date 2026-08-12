"""Thin agent tools for authorized long-term memory operations."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, ValidationError as PydanticValidationError

from peacemusic.core.errors import PeaceMusicError
from peacemusic.modules.agent.context import AgentRequestContext
from peacemusic.modules.agent.results import ToolResult
from peacemusic.modules.agent.tools import ToolCategory, ToolSpec
from peacemusic.modules.memory.models import MemoryKind
from peacemusic.modules.memory.service import MemoryService


class RememberArguments(BaseModel):
    content: str = Field(min_length=1, max_length=10_000)
    scope: Literal["user", "channel"] = "user"
    kind: Literal["semantic", "episodic"] = "semantic"


class RecallArguments(BaseModel):
    query: str = Field(min_length=1, max_length=1_000)
    scope: Literal["user", "channel"] = "user"
    limit: int = Field(default=5, ge=1, le=20)


class ForgetArguments(BaseModel):
    scope: Literal["user", "channel"] = "user"
    memory_id: str | None = Field(default=None, min_length=1, max_length=64)


def build_memory_tool_specs(service: MemoryService) -> tuple[ToolSpec, ...]:
    async def remember(context: AgentRequestContext, **values: object) -> ToolResult:
        try:
            args = RememberArguments(**values)
            record = await service.remember(
                guild_id=context.guild_id or 0,
                user_id=context.user_id,
                content=args.content,
                scope=args.scope,
                kind=MemoryKind(args.kind),
                channel_id=context.channel_id,
            )
            return ToolResult.success(
                "Memory saved",
                data={"memory_id": record.memory_id, "scope": args.scope},
            )
        except (PydanticValidationError, PeaceMusicError) as exc:
            return _failure(exc)

    async def recall(context: AgentRequestContext, **values: object) -> ToolResult:
        try:
            args = RecallArguments(**values)
            records = await service.recall(
                guild_id=context.guild_id or 0,
                user_id=context.user_id,
                query=args.query,
                scope=args.scope,
                limit=args.limit,
                channel_id=context.channel_id,
            )
            return ToolResult.success(
                f"Found {len(records)} memories",
                data={
                    "memories": [record.model_dump(mode="json") for record in records]
                },
            )
        except (PydanticValidationError, PeaceMusicError) as exc:
            return _failure(exc)

    async def forget(context: AgentRequestContext, **values: object) -> ToolResult:
        try:
            args = ForgetArguments(**values)
            deleted = await service.forget(
                guild_id=context.guild_id or 0,
                user_id=context.user_id,
                scope=args.scope,
                memory_id=args.memory_id,
                channel_id=context.channel_id,
            )
            return ToolResult.success("Memory removed", data={"deleted": deleted})
        except (PydanticValidationError, PeaceMusicError) as exc:
            return _failure(exc)

    return (
        ToolSpec("remember", ToolCategory.MEMORY, remember, RememberArguments),
        ToolSpec("recall", ToolCategory.MEMORY, recall, RecallArguments),
        ToolSpec("forget", ToolCategory.MEMORY, forget, ForgetArguments),
    )


def _failure(error: Exception) -> ToolResult:
    code = (
        "INVALID_TOOL_ARGUMENTS"
        if isinstance(error, PydanticValidationError)
        else type(error).__name__.upper()
    )
    return ToolResult.failure(code, str(error))
