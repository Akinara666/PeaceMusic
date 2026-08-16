from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from peacemusic.core.errors import ExternalServiceError
from peacemusic.infrastructure.persistence.repositories.in_memory_settings import (
    InMemoryGuildSettingsRepository,
)
from peacemusic.modules.agent.conversation import (
    ConversationMessage,
    InMemoryConversationRepository,
)
from peacemusic.modules.agent.limits import UserRateLimiter
from peacemusic.core.metrics import MetricsRegistry
from peacemusic.modules.agent.context import AgentRequestContext
from peacemusic.modules.agent.coordinator import TurnCoordinator
from peacemusic.modules.agent.graph import InputRoute, normalize_input, route_input
from peacemusic.modules.agent.service import (
    AgentService,
    _extract_response,
    format_user_message,
)
from peacemusic.modules.agent.tools import ToolRegistry
from peacemusic.modules.agent.state import AttachmentRef
from peacemusic.modules.settings.service import GuildSettingsService


class FakeAgent:
    def __init__(self) -> None:
        self.payloads = []

    async def ainvoke(self, payload, *, config=None):
        self.payloads.append((payload, config))
        return {"messages": [SimpleNamespace(content="agent response")]}


class FakeFactory:
    def __init__(self) -> None:
        self.tools = None
        self.agents = []

    def create(self, tools, *, system_prompt=None):
        self.tools = tools
        self.system_prompt = system_prompt
        agent = FakeAgent()
        self.agents.append(agent)
        return agent


def test_extract_response_supports_structured_text_blocks() -> None:
    result = {
        "messages": [
            {"role": "user", "content": "Привет!"},
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "Здравствуйте!"},
                    {"type": "image_url", "image_url": "https://example.test/image"},
                ],
            },
        ]
    }

    assert _extract_response(result) == "Здравствуйте!"


def test_extract_response_uses_latest_textual_message() -> None:
    result = {
        "messages": [
            SimpleNamespace(content="Answer before a tool call"),
            {"role": "tool", "content": [{"type": "tool_result", "result": "ok"}]},
        ]
    }

    assert _extract_response(result) == "Answer before a tool call"


def test_extract_response_rejects_results_without_text() -> None:
    with pytest.raises(ExternalServiceError, match="no textual response"):
        _extract_response({"messages": [{"content": [{"type": "tool_call"}]}]})


def test_format_user_message_prefixes_and_normalizes_display_name() -> None:
    context = AgentRequestContext("req", 1, 2, 3, "  akinara\n  ")

    assert format_user_message(context, "Привет!") == "akinara: Привет!"


def test_format_user_message_falls_back_when_display_name_is_empty() -> None:
    context = AgentRequestContext("req", 1, 2, 3, " \n ")

    assert format_user_message(context, "Hello") == "User 3: Hello"


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
        settings = GuildSettingsService(
            InMemoryGuildSettingsRepository(),
            default_system_prompt="You are a cheerful music guide.",
        )
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
        assert factory.system_prompt == "You are a cheerful music guide."
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

        payload, config = factory.agents[1].payloads[0]
        assert payload["messages"] == [
            {"role": "user", "content": "User: first message"},
            {"role": "assistant", "content": "agent response"},
            {"role": "user", "content": "User: second message"},
        ]
        assert config["configurable"]["thread_id"] == "agent-v2:guild:1:channel:2"

        assert config["metadata"]["request_id"] == "req-2"
        assert config["recursion_limit"] == 13
        assert len(conversation.messages["guild:1:channel:2"]) == 4

    asyncio.run(scenario())


def test_agent_service_clears_messages_and_checkpoint_for_channel() -> None:
    async def scenario() -> None:
        settings = GuildSettingsService(InMemoryGuildSettingsRepository())
        conversation = InMemoryConversationRepository()
        await conversation.append(
            "guild:1:channel:2", ConversationMessage("user", "old message")
        )
        cleared_threads: list[str] = []

        async def clear_checkpoint(thread_id: str) -> None:
            cleared_threads.append(thread_id)

        service = AgentService(
            settings_service=settings,
            tool_registry=ToolRegistry(),
            agent_factory=FakeFactory(),
            coordinator=TurnCoordinator(timeout_seconds=1),
            conversation_repository=conversation,
            checkpoint_clearer=clear_checkpoint,
        )

        assert await service.clear_conversation(1, 2) == 1
        assert await conversation.recent("guild:1:channel:2", limit=10) == ()
        assert cleared_threads == ["agent-v2:guild:1:channel:2"]

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
        cleared_threads: list[str] = []

        async def clear_checkpoint(thread_id: str) -> None:
            cleared_threads.append(thread_id)

        service = AgentService(
            settings_service=settings,
            tool_registry=ToolRegistry(),
            agent_factory=factory,
            coordinator=TurnCoordinator(timeout_seconds=1),
            attachment_preparer=preparer,
            checkpoint_clearer=clear_checkpoint,
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

        payload, config = factory.agents[0].payloads[0]
        current_message = payload["messages"][-1]
        assert current_message["content"][1]["file_uri"] == "https://files.test/1"
        assert config["configurable"]["thread_id"] == (
            "agent-v2:guild:1:channel:2:attachment:req"
        )
        assert state.final_response == "agent response"
        assert preparer.cleaned is True
        assert cleared_threads == ["agent-v2:guild:1:channel:2:attachment:req"]

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
