from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace

from peacemusic.infrastructure.persistence.repositories.in_memory_settings import (
    InMemoryGuildSettingsRepository,
)
from peacemusic.modules.agent.conversation import InMemoryConversationRepository
from peacemusic.modules.agent.limits import UserRateLimiter
from peacemusic.core.metrics import MetricsRegistry
from peacemusic.modules.agent.context import AgentRequestContext
from peacemusic.modules.agent.coordinator import TurnCoordinator
from peacemusic.modules.agent.graph import InputRoute, normalize_input, route_input
from peacemusic.modules.agent.service import AgentService
from peacemusic.modules.agent.tools import ToolRegistry
from peacemusic.modules.agent.state import AttachmentRef
from peacemusic.modules.settings.service import GuildSettingsService


class FakeAgent:
    def __init__(self) -> None:
        self.payloads = []

    async def ainvoke(self, payload):
        self.payloads.append(payload)
        return {"messages": [SimpleNamespace(content="agent response")]}


class FakeFactory:
    def __init__(self) -> None:
        self.tools = None
        self.agents = []

    def create(self, tools):
        self.tools = tools
        agent = FakeAgent()
        self.agents.append(agent)
        return agent


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
        metrics = MetricsRegistry()
        service = AgentService(
            settings_service=settings,
            tool_registry=ToolRegistry(),
            agent_factory=factory,
            coordinator=TurnCoordinator(timeout_seconds=1),
            metrics=metrics,
        )
        state = await service.handle(
            AgentRequestContext("req", 1, 2, 3, "User"),
            "hello",
        )

        assert state.final_response == "agent response"
        assert state.normalized_input == "hello"
        assert state.checkpoint()["final_response"] == "agent response"
        assert factory.tools == []
        assert "peacemusic_agent_turns_total 1" in metrics.render()
        assert "peacemusic_agent_turn_duration_seconds_count 1" in metrics.render()

    asyncio.run(scenario())


def test_agent_service_reuses_bounded_thread_history() -> None:
    async def scenario() -> None:
        settings = GuildSettingsService(InMemoryGuildSettingsRepository())
        factory = FakeFactory()
        conversation = InMemoryConversationRepository()
        service = AgentService(
            settings_service=settings,
            tool_registry=ToolRegistry(),
            agent_factory=factory,
            coordinator=TurnCoordinator(timeout_seconds=1),
            conversation_repository=conversation,
            conversation_limit=4,
        )
        context = AgentRequestContext("req-1", 1, 2, 3, "User")

        await service.handle(context, "first message")
        await service.handle(
            AgentRequestContext("req-2", 1, 2, 3, "User"), "second message"
        )

        assert factory.agents[1].payloads[0]["messages"] == [
            {"role": "user", "content": "first message"},
            {"role": "assistant", "content": "agent response"},
            {"role": "user", "content": "second message"},
        ]
        assert len(conversation.messages["guild:1:channel:2"]) == 4

    asyncio.run(scenario())


def test_agent_service_passes_provider_media_and_cleans_it_up() -> None:
    class Uploaded:
        provider_reference = type(
            "Reference",
            (),
            {"uri": "https://files.test/1", "mime_type": "image/png"},
        )()

    class Preparer:
        def __init__(self) -> None:
            self.cleaned = False

        @asynccontextmanager
        async def prepare(self, attachments):
            yield [Uploaded()]
            self.cleaned = True

    async def scenario() -> None:
        settings = GuildSettingsService(InMemoryGuildSettingsRepository())
        factory = FakeFactory()
        preparer = Preparer()
        service = AgentService(
            settings_service=settings,
            tool_registry=ToolRegistry(),
            agent_factory=factory,
            coordinator=TurnCoordinator(timeout_seconds=1),
            attachment_preparer=preparer,
        )
        state = await service.handle(
            AgentRequestContext("req", 1, 2, 3, "User"),
            "describe this",
            attachments=[
                AttachmentRef(
                    attachment_id="1",
                    filename="image.png",
                    content_type="image/png",
                    size_bytes=4,
                    url="https://discord.test/image.png",
                )
            ],
        )

        current_message = factory.agents[0].payloads[0]["messages"][-1]
        assert current_message["content"][1]["file_uri"] == "https://files.test/1"
        assert state.final_response == "agent response"
        assert preparer.cleaned is True

    asyncio.run(scenario())


def test_agent_service_enforces_per_user_rate_limit_before_provider_call() -> None:
    async def scenario() -> None:
        repository = InMemoryGuildSettingsRepository()
        settings = GuildSettingsService(repository)
        current = await settings.get(1)
        current.ai.per_user_rate_limit = 1
        await repository.save(current)
        settings.invalidate(1)
        factory = FakeFactory()
        service = AgentService(
            settings_service=settings,
            tool_registry=ToolRegistry(),
            agent_factory=factory,
            coordinator=TurnCoordinator(timeout_seconds=1),
            rate_limiter=UserRateLimiter(),
        )
        context = AgentRequestContext("req-1", 1, 2, 3, "User")

        await service.handle(context, "first")
        limited = await service.handle(
            AgentRequestContext("req-2", 1, 2, 3, "User"), "second"
        )

        assert limited.final_response == "You have reached the AI request rate limit."
        assert len(factory.agents) == 1

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
