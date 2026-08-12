from __future__ import annotations

import asyncio
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
