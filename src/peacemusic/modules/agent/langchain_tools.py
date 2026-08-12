"""Convert application tool specs into LangChain tool adapters."""

from __future__ import annotations

from collections.abc import Iterable
from inspect import Parameter, signature
from typing import Any, get_type_hints

from pydantic import BaseModel, create_model

from peacemusic.modules.agent.context import AgentRequestContext
from peacemusic.modules.agent.results import ToolResult
from peacemusic.modules.agent.tools import ToolSpec


def build_langchain_tools(
    specs: Iterable[ToolSpec],
    *,
    context: AgentRequestContext,
    max_tool_calls: int = 8,
) -> list[object]:
    """Bind runtime context before exposing tools to ``create_agent``.

    The model sees only validated business arguments.  Discord objects,
    database handles, locks, and authorization context remain application-owned.
    """

    if max_tool_calls < 1:
        raise ValueError("max_tool_calls must be positive")
    try:
        from langchain_core.tools import StructuredTool
    except ImportError as exc:  # pragma: no cover - optional provider boundary
        raise RuntimeError(
            "LangChain tools require the 'langchain-core' package."
        ) from exc

    tools: list[object] = []
    for spec in specs:
        call_count = 0

        async def invoke(_spec: ToolSpec = spec, **arguments: object):
            nonlocal call_count
            if call_count >= max_tool_calls:
                return ToolResult.failure(
                    "TOOL_CALL_LIMIT",
                    "The maximum number of tool calls for this turn was reached.",
                ).model_dump(mode="json")
            call_count += 1
            result = await _spec.handler(context, **arguments)
            return result.model_dump(mode="json")

        tools.append(
            StructuredTool.from_function(
                coroutine=invoke,
                name=spec.name,
                description=spec.description
                or f"PeaceMusic {spec.category.value} operation: {spec.name}",
                args_schema=_args_schema(spec),
            )
        )
    return tools


def _args_schema(spec: ToolSpec) -> type[BaseModel]:
    """Return the model-facing schema without exposing runtime context."""

    if spec.args_schema is not None:
        return spec.args_schema

    try:
        parameters = signature(spec.handler).parameters.values()
        type_hints = get_type_hints(spec.handler)
    except (NameError, TypeError, ValueError):
        parameters = ()
        type_hints = {}

    fields: dict[str, tuple[Any, Any]] = {}
    for parameter in parameters:
        if parameter.name == "context" or parameter.kind in {
            Parameter.VAR_POSITIONAL,
            Parameter.VAR_KEYWORD,
        }:
            continue
        annotation = type_hints.get(parameter.name, parameter.annotation)
        if annotation is Parameter.empty:
            annotation = Any
        default = parameter.default if parameter.default is not Parameter.empty else ...
        fields[parameter.name] = (annotation, default)

    return create_model(f"{spec.name.replace('-', '_')}_arguments", **fields)
