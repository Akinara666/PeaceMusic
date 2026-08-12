"""Application service for one coordinated LangChain agent turn."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol

from peacemusic.core.errors import ExternalServiceError
from peacemusic.modules.agent.context import AgentRequestContext
from peacemusic.modules.agent.coordinator import TurnCoordinator
from peacemusic.modules.agent.langchain_tools import build_langchain_tools
from peacemusic.modules.agent.state import AttachmentRef, PeaceMusicState
from peacemusic.modules.agent.tools import ToolRegistry
from peacemusic.modules.settings.service import GuildSettingsService


class AgentFactory(Protocol):
    def create(self, tools: Sequence[Any]) -> Any:
        """Build an agent that exposes the supplied tools."""


class AgentService:
    """Coordinate settings, tool filtering, provider execution, and state."""

    def __init__(
        self,
        *,
        settings_service: GuildSettingsService,
        tool_registry: ToolRegistry,
        agent_factory: AgentFactory,
        coordinator: TurnCoordinator,
    ) -> None:
        self._settings = settings_service
        self._tools = tool_registry
        self._factory = agent_factory
        self._coordinator = coordinator

    async def get_settings(self, guild_id: int):
        """Read effective settings for a Discord adapter policy check."""

        return await self._settings.get(guild_id)

    async def handle(
        self,
        context: AgentRequestContext,
        text: str,
        *,
        attachments: Sequence[AttachmentRef] = (),
    ) -> PeaceMusicState:
        settings = await self._settings.get(context.guild_id or 0)
        state = PeaceMusicState(
            request_id=context.request_id,
            guild_id=context.guild_id,
            channel_id=context.channel_id,
            user_id=context.user_id,
            input_text=text,
            attachments=list(attachments),
        )
        if not settings.ai.enabled:
            return state.model_copy(
                update={"final_response": "AI assistant is disabled for this server."}
            )

        available = self._tools.available(settings)
        langchain_tools = (
            build_langchain_tools(available, context=context) if available else []
        )
        agent = self._factory.create(langchain_tools)

        async def run_agent() -> Any:
            try:
                return await agent.ainvoke(
                    {"messages": [{"role": "user", "content": text}]}
                )
            except Exception as exc:  # noqa: BLE001 - provider boundary
                raise ExternalServiceError("Agent execution failed") from exc

        result = await self._coordinator.run(context.channel_id, run_agent)
        return state.model_copy(update={"final_response": _extract_response(result)})


def _extract_response(result: Any) -> str:
    if isinstance(result, str):
        return result
    if isinstance(result, dict):
        messages = result.get("messages")
        if isinstance(messages, Sequence) and messages:
            last = messages[-1]
            content = getattr(last, "content", None)
            if content is None and isinstance(last, dict):
                content = last.get("content")
            if isinstance(content, str):
                return content
        content = result.get("content")
        if isinstance(content, str):
            return content
    raise ExternalServiceError("Agent returned no textual response")
