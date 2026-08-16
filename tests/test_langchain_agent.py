from __future__ import annotations

import asyncio
import logging
import sys
import types

from peacemusic.infrastructure.llm.langchain_agent import LangChainAgentFactory
from peacemusic.modules.agent.context import AgentRequestContext
from peacemusic.modules.agent.langchain_tools import build_langchain_tools
from peacemusic.modules.agent.memory_tools import (
    RecallArguments,
    build_memory_tool_specs,
)
from peacemusic.modules.agent.music_tools import (
    PlayMusicArguments,
    build_music_tool_specs,
)
from peacemusic.modules.agent.results import ToolResult
from peacemusic.modules.agent.tools import ToolCategory, ToolSpec


def test_langchain_tools_bind_context_and_return_serializable_result(
    monkeypatch,
) -> None:
    class FakeStructuredTool:
        @classmethod
        def from_function(cls, *, coroutine, name, description, args_schema):
            return types.SimpleNamespace(
                coroutine=coroutine,
                name=name,
                description=description,
                args_schema=args_schema,
            )

    core_tools = types.ModuleType("langchain_core.tools")
    core_tools.StructuredTool = FakeStructuredTool
    monkeypatch.setitem(sys.modules, "langchain_core.tools", core_tools)

    async def handler(context: AgentRequestContext, value: int) -> ToolResult:
        return ToolResult.success(str(context.user_id + value))

    tools = build_langchain_tools(
        [ToolSpec("example", ToolCategory.MUSIC, handler)],
        context=AgentRequestContext("req", 1, 2, 3, "user"),
        max_tool_calls=1,
    )
    result = asyncio.run(tools[0].coroutine(value=4))
    limited = asyncio.run(tools[0].coroutine(value=5))

    assert result == {
        "ok": True,
        "code": "OK",
        "message": "7",
        "data": {},
        "user_notified": False,
    }
    assert limited["code"] == "TOOL_CALL_LIMIT"


def test_langchain_tools_return_unexpected_failure_details_to_the_model(
    monkeypatch,
) -> None:
    class FakeStructuredTool:
        @classmethod
        def from_function(cls, *, coroutine, name, description, args_schema):
            return types.SimpleNamespace(coroutine=coroutine, name=name)

    core_tools = types.ModuleType("langchain_core.tools")
    core_tools.StructuredTool = FakeStructuredTool
    monkeypatch.setitem(sys.modules, "langchain_core.tools", core_tools)

    async def handler(_context: AgentRequestContext) -> ToolResult:
        raise RuntimeError("HTTP 403: media provider rejected the request")

    tool = build_langchain_tools(
        [ToolSpec("broken", ToolCategory.MUSIC, handler)],
        context=AgentRequestContext("req", 1, 2, 3, "user"),
    )[0]

    result = asyncio.run(tool.coroutine())

    assert result["ok"] is False
    assert result["code"] == "TOOL_EXECUTION_ERROR"
    assert "HTTP 403" in result["message"]


def test_langchain_tools_log_arguments_and_results_without_secrets(
    monkeypatch, caplog
) -> None:
    class FakeStructuredTool:
        @classmethod
        def from_function(cls, *, coroutine, name, description, args_schema):
            return types.SimpleNamespace(coroutine=coroutine, name=name)

    core_tools = types.ModuleType("langchain_core.tools")
    core_tools.StructuredTool = FakeStructuredTool
    monkeypatch.setitem(sys.modules, "langchain_core.tools", core_tools)

    async def handler(
        _context: AgentRequestContext, query: str, token: str | None = None
    ) -> ToolResult:
        return ToolResult.success(
            "queued", data={"query": query, "api_key": "do-not-log"}
        )

    with caplog.at_level(
        logging.INFO, logger="peacemusic.modules.agent.langchain_tools"
    ):
        tool = build_langchain_tools(
            [ToolSpec("example", ToolCategory.MUSIC, handler)],
            context=AgentRequestContext("req", 1, 2, 3, "user"),
        )[0]
        result = asyncio.run(tool.coroutine(query="play jazz", token="do-not-log"))

    assert result["ok"] is True
    started = next(
        record
        for record in caplog.records
        if record.message == "Agent tool call started"
    )
    completed = next(
        record
        for record in caplog.records
        if record.message == "Agent tool call completed"
    )
    assert started.tool_name == "example"
    assert started.tool_context["user_name"] == "user"
    assert started.tool_arguments["query"] == "play jazz"
    assert started.tool_arguments["token"] == "<redacted>"
    assert completed.tool_code == "OK"
    assert completed.tool_result["data"]["api_key"] == "<redacted>"
    assert completed.tool_duration_ms >= 0


def test_langchain_tools_expose_public_argument_schemas() -> None:
    context = AgentRequestContext("req", 1, 2, 3, "user")

    music_tool = build_langchain_tools(
        [build_music_tool_specs(object())[0]],  # type: ignore[arg-type]
        context=context,
    )[0]
    memory_tool = build_langchain_tools(
        [build_memory_tool_specs(object())[1]],  # type: ignore[arg-type]
        context=context,
    )[0]

    assert music_tool.args_schema is PlayMusicArguments
    assert set(music_tool.args) == {"query"}
    assert music_tool.description == (
        "Play or queue a song from a supported media URL or search query."
    )
    assert memory_tool.args_schema is RecallArguments
    assert set(memory_tool.args) == {"query", "scope", "limit"}


def test_langchain_factory_uses_create_agent(monkeypatch) -> None:
    captured: dict[str, object] = {}
    agents = types.ModuleType("langchain.agents")

    def create_agent(**kwargs):
        captured.update(kwargs)
        return "agent"

    agents.create_agent = create_agent
    langchain = types.ModuleType("langchain")
    langchain.agents = agents
    google_genai = types.ModuleType("langchain_google_genai")

    class ChatGoogleGenerativeAI:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    google_genai.ChatGoogleGenerativeAI = ChatGoogleGenerativeAI
    monkeypatch.setitem(sys.modules, "langchain", langchain)
    monkeypatch.setitem(sys.modules, "langchain.agents", agents)
    monkeypatch.setitem(sys.modules, "langchain_google_genai", google_genai)

    factory = LangChainAgentFactory(
        api_key="secret",
        model_name="gemini-test",
        temperature=0.3,
        system_prompt="Be concise",
    )
    checkpointer = object()
    store = object()
    factory.attach_persistence(checkpointer=checkpointer, store=store)
    assert factory.create(["tool"]) == "agent"
    assert captured["tools"] == ["tool"]
    assert captured["system_prompt"] == "Be concise"
    assert captured["checkpointer"] is checkpointer
    assert captured["store"] is store
    assert captured["model"].kwargs["model"] == "gemini-test"
