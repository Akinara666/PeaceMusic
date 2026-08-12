from __future__ import annotations

import asyncio

import pytest

from peacemusic.core.errors import PermissionDeniedError
from peacemusic.modules.agent.context import AgentRequestContext
from peacemusic.modules.agent.coordinator import TurnCoordinator
from peacemusic.modules.agent.results import ToolResult
from peacemusic.modules.agent.graph import OuterAgentWorkflow
from peacemusic.modules.agent.state import AttachmentRef, PeaceMusicState, ToolEvent
from peacemusic.modules.agent.tools import ToolCategory, ToolRegistry, ToolSpec
from peacemusic.modules.settings.models import GuildSettings


def test_agent_context_and_state_are_checkpoint_safe() -> None:
    context = AgentRequestContext(
        request_id="req-1",
        guild_id=123,
        channel_id=456,
        user_id=789,
        user_name="User",
    )
    state = PeaceMusicState(
        request_id=context.request_id,
        guild_id=context.guild_id,
        channel_id=context.channel_id,
        user_id=context.user_id,
        discord_message_id=42,
        attachments=[
            AttachmentRef(
                attachment_id="a1",
                filename="photo.png",
                content_type="image/png",
                size_bytes=10,
            )
        ],
        tool_events=[
            ToolEvent(tool_name="play_music", ok=True, code="OK", message="queued")
        ],
    )

    checkpoint = state.checkpoint()
    assert checkpoint["request_id"] == "req-1"
    assert checkpoint["attachments"][0]["filename"] == "photo.png"
    assert "asyncio" not in repr(checkpoint)


def test_outer_workflow_initializes_checkpoint_safe_route_state() -> None:
    context = AgentRequestContext("req-1", 123, 456, 789, "User")
    state = OuterAgentWorkflow().initialize(
        context,
        "  hello\n world ",
        attachments=[
            AttachmentRef(
                attachment_id="a1",
                filename="song.mp3",
                content_type="audio/mpeg",
                size_bytes=1,
            )
        ],
    )

    assert state.normalized_input == "hello world"
    assert state.input_route == "direct_audio"
    assert state.checkpoint()["input_route"] == "direct_audio"


def test_tool_result_has_stable_success_and_failure_contract() -> None:
    assert ToolResult.success("done").model_dump() == {
        "ok": True,
        "code": "OK",
        "message": "done",
        "data": {},
        "user_notified": False,
    }
    failure = ToolResult.failure("DENIED", "Not allowed")
    assert failure.ok is False
    assert failure.code == "DENIED"


def test_tool_registry_filters_by_guild_capability_settings() -> None:
    async def handler(context: AgentRequestContext, value: int) -> ToolResult:
        return ToolResult.success(str(value), data={"value": value})

    registry = ToolRegistry([ToolSpec("music", ToolCategory.MUSIC, handler)])
    context = AgentRequestContext("req", 1, 2, 3, "user")

    async def scenario() -> None:
        settings = GuildSettings(guild_id=1)
        assert [item.name for item in registry.available(settings)] == ["music"]
        result = await registry.invoke("music", context, {"value": 4}, settings)
        assert result.data == {"value": 4}

        settings.ai.music_tools_enabled = False
        result = await registry.invoke("music", context, {"value": 4}, settings)
        assert result.code == "TOOL_DISABLED"

    asyncio.run(scenario())


def test_turn_coordinator_serializes_same_channel_and_limits_timeouts() -> None:
    async def scenario() -> None:
        coordinator = TurnCoordinator(max_concurrent=1, timeout_seconds=0.05)
        order: list[int] = []

        async def operation(number: int) -> int:
            order.append(number)
            await asyncio.sleep(0.01)
            return number

        assert await asyncio.gather(
            coordinator.run(1, lambda: operation(1)),
            coordinator.run(1, lambda: operation(2)),
        ) == [1, 2]
        stats = await coordinator.stats()
        assert stats.completed_turns == 2
        assert stats.active_turns == 0

        with pytest.raises(asyncio.TimeoutError):
            await coordinator.run(2, lambda: asyncio.sleep(1))
        assert (await coordinator.stats()).timed_out_turns == 1

    asyncio.run(scenario())
