from __future__ import annotations

import asyncio
from types import SimpleNamespace

from peacemusic.infrastructure.persistence.repositories.in_memory_settings import (
    InMemoryGuildSettingsRepository,
)
from peacemusic.modules.agent.context import AgentRequestContext
from peacemusic.modules.agent.coordinator import TurnCoordinator
from peacemusic.modules.agent.graph import InputRoute, normalize_input, route_input
from peacemusic.modules.agent.service import AgentService
from peacemusic.modules.agent.tools import ToolRegistry
from peacemusic.modules.agent.state import AttachmentRef
from peacemusic.modules.settings.service import GuildSettingsService


class FakeAgent:
    async def ainvoke(self, payload):
        return {"messages": [SimpleNamespace(content="agent response")]}


class FakeFactory:
    def __init__(self) -> None:
        self.tools = None

    def create(self, tools):
        self.tools = tools
        return FakeAgent()


def test_outer_graph_normalizes_and_routes_audio() -> None:
    assert normalize_input("  hello\n world ") == "hello world"
    assert (
        route_input(
            [
                AttachmentRef(
                    attachment_id="a",
                    filename="song.mp3",
                    content_type="audio/mpeg",
                    size_bytes=1,
                )
            ]
        )
        is InputRoute.DIRECT_AUDIO
    )
    assert route_input([]) is InputRoute.AI_AGENT


def test_agent_service_coordinates_provider_and_returns_serializable_state() -> None:
    async def scenario() -> None:
        settings = GuildSettingsService(InMemoryGuildSettingsRepository())
        factory = FakeFactory()
        service = AgentService(
            settings_service=settings,
            tool_registry=ToolRegistry(),
            agent_factory=factory,
            coordinator=TurnCoordinator(timeout_seconds=1),
        )
        state = await service.handle(
            AgentRequestContext("req", 1, 2, 3, "User"),
            "hello",
        )

        assert state.final_response == "agent response"
        assert state.normalized_input == "hello"
        assert state.checkpoint()["final_response"] == "agent response"
        assert factory.tools == []

    asyncio.run(scenario())


def test_agent_service_does_not_call_provider_for_empty_ai_input() -> None:
    async def scenario() -> None:
        settings = GuildSettingsService(InMemoryGuildSettingsRepository())
        factory = FakeFactory()
        service = AgentService(
            settings_service=settings,
            tool_registry=ToolRegistry(),
            agent_factory=factory,
            coordinator=TurnCoordinator(timeout_seconds=1),
        )

        state = await service.handle(
            AgentRequestContext("req", 1, 2, 3, "User"), "  \n  "
        )

        assert state.final_response == "Please provide a message to process."
        assert factory.tools is None

    asyncio.run(scenario())


def test_agent_service_returns_disabled_response_without_provider_call() -> None:
    async def scenario() -> None:
        repository = InMemoryGuildSettingsRepository()
        settings = GuildSettingsService(repository)
        current = await settings.get(1)
        current.ai.enabled = False
        await repository.save(current)
        settings.invalidate(1)
        factory = FakeFactory()
        service = AgentService(
            settings_service=settings,
            tool_registry=ToolRegistry(),
            agent_factory=factory,
            coordinator=TurnCoordinator(timeout_seconds=1),
        )

        state = await service.handle(
            AgentRequestContext("req", 1, 2, 3, "User"), "hello"
        )

        assert "disabled" in (state.final_response or "")
        assert factory.tools is None

    asyncio.run(scenario())
