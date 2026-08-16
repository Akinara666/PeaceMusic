"""Convert application tool specs into LangChain tool adapters."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from inspect import Parameter, signature
import logging
import time
from typing import Any, get_type_hints

from pydantic import BaseModel, create_model

from peacemusic.core.errors import describe_exception
from peacemusic.modules.agent.context import AgentRequestContext
from peacemusic.modules.agent.results import ToolResult
from peacemusic.modules.agent.tools import ToolSpec

logger = logging.getLogger(__name__)

_SENSITIVE_ARGUMENT_KEYS = {
    "access_token",
    "api_key",
    "authorization",
    "cookie",
    "cookies",
    "password",
    "secret",
    "token",
}


def _is_sensitive_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    return normalized in _SENSITIVE_ARGUMENT_KEYS or any(
        marker in normalized
        for marker in ("token", "secret", "password", "cookie", "api_key")
    )


def _safe_log_value(value: Any, *, depth: int = 0) -> Any:
    """Keep tool diagnostics useful without leaking credentials or huge payloads."""

    if depth > 4:
        return "<nested value omitted>"
    if isinstance(value, Mapping):
        return {
            str(key): (
                "<redacted>"
                if _is_sensitive_key(str(key))
                else _safe_log_value(item, depth=depth + 1)
            )
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple, set)):
        return [_safe_log_value(item, depth=depth + 1) for item in value]
    if isinstance(value, str) and len(value) > 4000:
        return f"{value[:4000]}…<truncated>"
    return value


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
            call_number = call_count + 1
            log_context = {
                "request_id": context.request_id,
                "guild_id": context.guild_id,
                "channel_id": context.channel_id,
                "user_id": context.user_id,
                "tool_name": _spec.name,
                "tool_category": _spec.category.value,
                "tool_call_number": call_number,
                "tool_context": _safe_log_value(context.to_checkpoint()),
                "tool_arguments": _safe_log_value(arguments),
            }
            if call_count >= max_tool_calls:
                result = ToolResult.failure(
                    "TOOL_CALL_LIMIT",
                    "The maximum number of tool calls for this turn was reached.",
                )
                logger.warning(
                    "Agent tool call rejected",
                    extra={
                        **log_context,
                        "tool_ok": result.ok,
                        "tool_code": result.code,
                        "tool_result": _safe_log_value(result.model_dump(mode="json")),
                        "tool_duration_ms": 0.0,
                    },
                )
                return result.model_dump(mode="json")
            call_count += 1
            started = time.monotonic()
            logger.info("Agent tool call started", extra=log_context)
            try:
                result = await _spec.handler(context, **arguments)
            except Exception as exc:  # noqa: BLE001 - return failure to the model
                result = ToolResult.failure(
                    "TOOL_EXECUTION_ERROR", describe_exception(exc)
                )
            logger.info(
                "Agent tool call completed",
                extra={
                    **log_context,
                    "tool_ok": result.ok,
                    "tool_code": result.code,
                    "tool_result": _safe_log_value(result.model_dump(mode="json")),
                    "tool_duration_ms": round((time.monotonic() - started) * 1000, 2),
                },
            )
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
