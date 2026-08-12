"""Application service for one coordinated LangChain agent turn."""

from __future__ import annotations

from collections.abc import Sequence
from contextlib import asynccontextmanager
from collections.abc import Awaitable, Callable
import logging
import time
from typing import Any, Protocol

from peacemusic.core.errors import ExternalServiceError
from peacemusic.core.metrics import MetricsRegistry
from peacemusic.modules.agent.context import AgentRequestContext
from peacemusic.modules.agent.conversation import (
    ConversationMessage,
    ConversationRepository,
)
from peacemusic.modules.agent.coordinator import TurnCoordinator
from peacemusic.modules.agent.graph import OuterAgentWorkflow
from peacemusic.modules.agent.langchain_tools import build_langchain_tools
from peacemusic.modules.agent.limits import UserRateLimiter
from peacemusic.modules.agent.state import AttachmentRef, PeaceMusicState
from peacemusic.modules.agent.tools import ToolRegistry
from peacemusic.modules.settings.service import GuildSettingsService

logger = logging.getLogger(__name__)


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
        metrics: MetricsRegistry | None = None,
        conversation_repository: ConversationRepository | None = None,
        conversation_limit: int = 20,
        rate_limiter: UserRateLimiter | None = None,
        max_tool_calls: int = 8,
        attachment_preparer=None,
        direct_audio_handler: (
            Callable[[AgentRequestContext, AttachmentRef], Awaitable[Any]] | None
        ) = None,
    ) -> None:
        self._settings = settings_service
        self._tools = tool_registry
        self._factory = agent_factory
        self._coordinator = coordinator
        self._metrics = metrics
        if conversation_limit < 1:
            raise ValueError("conversation_limit must be positive")
        self._conversation = conversation_repository
        self._conversation_limit = conversation_limit
        if max_tool_calls < 1:
            raise ValueError("max_tool_calls must be positive")
        self._rate_limiter = rate_limiter
        self._max_tool_calls = max_tool_calls
        self._attachment_preparer = attachment_preparer
        self._direct_audio_handler = direct_audio_handler
        self._workflow = OuterAgentWorkflow()

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
        state = self._workflow.initialize(context, text, attachments=attachments)
        state = self._workflow.apply_policy(state, ai_enabled=settings.ai.enabled)
        if state.final_response is not None:
            return state
        if (
            state.input_route == "direct_audio"
            and self._direct_audio_handler is not None
            and len(attachments) == 1
        ):
            track = await self._direct_audio_handler(context, attachments[0])
            return self._workflow.finalize(state, f"Queued {track.title}")
        if attachments and not settings.ai.attachments_enabled:
            return state.model_copy(
                update={"final_response": "Attachments are disabled for this server."}
            )
        if any(
            attachment.content_type
            and attachment.content_type.startswith("image/")
            and not settings.ai.image_input_enabled
            for attachment in attachments
        ):
            return state.model_copy(
                update={"final_response": "Image input is disabled for this server."}
            )
        if any(
            attachment.content_type
            and attachment.content_type.startswith("video/")
            and not settings.ai.video_input_enabled
            for attachment in attachments
        ):
            return state.model_copy(
                update={"final_response": "Video input is disabled for this server."}
            )
        if self._rate_limiter is not None and not await self._rate_limiter.allow(
            (context.guild_id, context.user_id), settings.ai.per_user_rate_limit
        ):
            if self._metrics is not None:
                self._metrics.increment("peacemusic_agent_rate_limited_total")
            return state.model_copy(
                update={"final_response": "You have reached the AI request rate limit."}
            )

        available = self._tools.available(settings)
        langchain_tools = (
            build_langchain_tools(
                available, context=context, max_tool_calls=self._max_tool_calls
            )
            if available
            else []
        )
        history = ()
        if self._conversation is not None and settings.memory.short_term_memory_enabled:
            history = await self._conversation.recent(
                self._thread_id(context), limit=self._conversation_limit
            )
        async with self._prepare_attachments(attachments) as uploaded:
            agent = self._factory.create(langchain_tools)
            messages = [message.as_message() for message in history]
            current_content: object = state.normalized_input
            if uploaded:
                current_content = [
                    {"type": "text", "text": state.normalized_input},
                    *[
                        {
                            "type": "media",
                            "file_uri": item.provider_reference.uri,
                            "mime_type": item.provider_reference.mime_type,
                        }
                        for item in uploaded
                    ],
                ]
            messages.append({"role": "user", "content": current_content})

            async def run_agent() -> Any:
                try:
                    if self._metrics is not None:
                        self._metrics.increment("peacemusic_llm_requests_total")
                    return await agent.ainvoke({"messages": messages})
                except Exception as exc:  # noqa: BLE001 - provider boundary
                    if self._metrics is not None:
                        self._metrics.increment("peacemusic_llm_request_errors_total")
                    raise ExternalServiceError("Agent execution failed") from exc

            started = time.monotonic()
            logger.info(
                "Agent turn started",
                extra={
                    "request_id": context.request_id,
                    "guild_id": context.guild_id,
                    "channel_id": context.channel_id,
                    "user_id": context.user_id,
                },
            )
            try:
                result = await self._coordinator.run(context.channel_id, run_agent)
                response = self._workflow.finalize(state, _extract_response(result))
            except Exception:
                if self._metrics is not None:
                    self._metrics.increment("peacemusic_agent_turn_failures_total")
                    self._metrics.increment("peacemusic_agent_turn_errors_total")
                raise
            finally:
                if self._metrics is not None:
                    self._metrics.observe(
                        "peacemusic_agent_turn_duration_seconds",
                        time.monotonic() - started,
                    )
            logger.info(
                "Agent turn completed",
                extra={
                    "request_id": context.request_id,
                    "guild_id": context.guild_id,
                    "channel_id": context.channel_id,
                    "user_id": context.user_id,
                },
            )
        if self._metrics is not None:
            self._metrics.increment("peacemusic_agent_turns_total")
        if self._conversation is not None and settings.memory.short_term_memory_enabled:
            thread_id = self._thread_id(context)
            await self._conversation.append(
                thread_id,
                ConversationMessage(role="user", content=state.normalized_input),
            )
            await self._conversation.append(
                thread_id,
                ConversationMessage(
                    role="assistant", content=response.final_response or ""
                ),
            )
        return response

    @asynccontextmanager
    async def _prepare_attachments(self, attachments):
        if self._attachment_preparer is None or not attachments:
            yield ()
            return
        async with self._attachment_preparer.prepare(attachments) as prepared:
            yield prepared

    @staticmethod
    def _thread_id(context: AgentRequestContext) -> str:
        if context.guild_id is None:
            return f"dm:{context.channel_id}"
        return f"guild:{context.guild_id}:channel:{context.channel_id}"


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
