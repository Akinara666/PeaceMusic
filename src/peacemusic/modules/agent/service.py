"""Application service for one coordinated LangChain agent turn."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from contextlib import asynccontextmanager
import logging
import time
from typing import Any, Protocol

from peacemusic.core.errors import ExternalServiceError, describe_exception
from peacemusic.core.metrics import MetricsRegistry
from peacemusic.modules.agent.context import AgentRequestContext
from peacemusic.modules.agent.conversation import (
    ConversationMedia,
    ConversationMessage,
    ConversationRepository,
    compact_conversation,
    conversation_thread_id,
)
from peacemusic.modules.agent.coordinator import TurnCoordinator
from peacemusic.modules.agent.graph import OuterAgentWorkflow
from peacemusic.modules.agent.langchain_tools import build_langchain_tools
from peacemusic.modules.agent.limits import UserRateLimiter
from peacemusic.modules.agent.state import AttachmentRef, PeaceMusicState
from peacemusic.modules.agent.tools import ToolRegistry
from peacemusic.modules.settings.service import GuildSettingsService

logger = logging.getLogger(__name__)


def format_user_message(context: AgentRequestContext, text: str) -> str:
    """Prefix model-visible user text with the Discord display name."""

    display_name = " ".join(context.user_name.split()) or f"User {context.user_id}"
    return f"{display_name}: {text}"


class AgentFactory(Protocol):
    def create(self, tools: Sequence[Any], *, system_prompt: str | None = None) -> Any:
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
        checkpoint_clearer: Callable[[str], Awaitable[None]] | None = None,
        conversation_limit: int = 20,
        conversation_token_limit: int = 3000,
        rate_limiter: UserRateLimiter | None = None,
        max_tool_calls: int = 8,
        max_model_calls: int = 4,
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
        self._checkpoint_clearer = checkpoint_clearer
        self._conversation_limit = conversation_limit
        if conversation_token_limit < 1:
            raise ValueError("conversation_token_limit must be positive")
        self._conversation_token_limit = conversation_token_limit
        if max_tool_calls < 1:
            raise ValueError("max_tool_calls must be positive")
        if max_model_calls < 1:
            raise ValueError("max_model_calls must be positive")
        self._rate_limiter = rate_limiter
        self._max_tool_calls = max_tool_calls
        self._max_model_calls = max_model_calls
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
            if settings.memory.summarization_enabled:
                history = compact_conversation(
                    history, max_tokens=self._conversation_token_limit
                )
        agent_thread_id = self._agent_thread_id(
            context, has_attachments=bool(attachments)
        )
        retain_provider_files = bool(
            attachments
            and self._conversation is not None
            and settings.memory.short_term_memory_enabled
        )
        uploaded = ()
        async with self._prepare_attachments(
            attachments, retain_provider_files=retain_provider_files
        ) as uploaded:
            agent = self._factory.create(
                langchain_tools,
                system_prompt=settings.ai.system_prompt,
            )
            user_message = format_user_message(context, state.normalized_input)
            current_content: object = user_message
            if uploaded:
                current_content = [
                    {"type": "text", "text": user_message},
                    *[
                        {
                            "type": "media",
                            "file_uri": item.provider_reference.uri,
                            "mime_type": item.provider_reference.mime_type,
                        }
                        for item in uploaded
                    ],
                ]

            def build_messages(
                conversation_history: Sequence[ConversationMessage],
            ) -> list[dict[str, object]]:
                messages = [message.as_message() for message in conversation_history]
                messages.append({"role": "user", "content": current_content})
                return messages

            messages = build_messages(history)

            async def run_agent(
                request_messages: Sequence[Mapping[str, object]],
            ) -> Any:
                try:
                    if self._metrics is not None:
                        self._metrics.increment("peacemusic_llm_requests_total")
                    return await agent.ainvoke(
                        {"messages": request_messages},
                        config={
                            "configurable": {
                                "thread_id": agent_thread_id,
                            },
                            "metadata": {
                                "request_id": context.request_id,
                                "guild_id": context.guild_id,
                                "channel_id": context.channel_id,
                            },
                            # LangGraph counts model and tool nodes as graph
                            # steps; bound the total so model calls cannot loop.
                            "recursion_limit": self._max_model_calls
                            + self._max_tool_calls
                            + 1,
                        },
                    )
                except Exception as exc:  # noqa: BLE001 - provider boundary
                    if self._metrics is not None:
                        self._metrics.increment("peacemusic_llm_request_errors_total")
                    raise ExternalServiceError(
                        f"Agent execution failed: {describe_exception(exc)}"
                    ) from exc

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
                try:
                    result = await self._coordinator.run(
                        context.channel_id,
                        lambda: run_agent(messages),
                        timeout_seconds=settings.ai.turn_timeout,
                    )
                except ExternalServiceError as exc:
                    if not self._should_retry_without_provider_media(
                        exc, history=history, uploaded=uploaded
                    ):
                        raise
                    thread_id = self._thread_id(context)
                    logger.warning(
                        "Stale provider media detected; retrying without persisted media",
                        extra={
                            "request_id": context.request_id,
                            "guild_id": context.guild_id,
                            "channel_id": context.channel_id,
                            "user_id": context.user_id,
                        },
                    )
                    if self._conversation is not None:
                        await self._conversation.clear_media(thread_id)
                    await self._clear_checkpoint(agent_thread_id, context)
                    messages = build_messages(
                        tuple(message.without_media() for message in history)
                    )
                    result = await self._coordinator.run(
                        context.channel_id,
                        lambda: run_agent(messages),
                        timeout_seconds=settings.ai.turn_timeout,
                    )
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
                if attachments:
                    await self._clear_checkpoint(agent_thread_id, context)
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
                ConversationMessage(
                    role="user",
                    content=user_message,
                    media=tuple(
                        ConversationMedia(
                            name=item.provider_reference.name,
                            uri=item.provider_reference.uri,
                            mime_type=item.provider_reference.mime_type,
                        )
                        for item in uploaded
                    ),
                ),
            )
            await self._conversation.append(
                thread_id,
                ConversationMessage(
                    role="assistant", content=response.final_response or ""
                ),
            )
        return response

    @staticmethod
    def _should_retry_without_provider_media(
        error: ExternalServiceError,
        *,
        history: Sequence[ConversationMessage],
        uploaded: Sequence[object],
    ) -> bool:
        """Recognize expired Gemini file references without hiding other failures."""

        if uploaded and not any(message.media for message in history):
            # A current upload failing is a real upload/provider failure; retrying
            # the same current file cannot repair it.
            return False
        message = str(error).casefold()
        return (
            "file " in message
            and ("permission_denied" in message or "permission denied" in message)
            and any(
                marker in message
                for marker in ("may not exist", "does not exist", "not found")
            )
        )

    async def clear_conversation(self, guild_id: int, channel_id: int) -> int:
        """Clear short-term messages and the matching LangGraph thread."""

        if guild_id <= 0 or channel_id <= 0:
            raise ValueError("guild_id and channel_id must be positive")
        thread_id = conversation_thread_id(guild_id, channel_id)

        async def clear() -> int:
            deleted = (
                await self._conversation.clear(thread_id)
                if self._conversation is not None
                else 0
            )
            if self._checkpoint_clearer is not None:
                await self._checkpoint_clearer(self._checkpoint_thread_id(thread_id))
            return deleted

        return await self._coordinator.run(channel_id, clear)

    @asynccontextmanager
    async def _prepare_attachments(
        self, attachments, *, retain_provider_files: bool = False
    ):
        if self._attachment_preparer is None or not attachments:
            yield ()
            return
        async with self._attachment_preparer.prepare(
            attachments, retain_provider_files=retain_provider_files
        ) as prepared:
            yield prepared

    @staticmethod
    def _thread_id(context: AgentRequestContext) -> str:
        if context.guild_id is None:
            return f"dm:{context.channel_id}"
        return conversation_thread_id(context.guild_id, context.channel_id)

    @classmethod
    def _checkpoint_thread_id(cls, thread_id: str) -> str:
        """Version agent checkpoints independently from text conversation history."""

        return f"agent-v2:{thread_id}"

    @classmethod
    def _agent_thread_id(
        cls, context: AgentRequestContext, *, has_attachments: bool
    ) -> str:
        thread_id = cls._checkpoint_thread_id(cls._thread_id(context))
        if has_attachments:
            return f"{thread_id}:attachment:{context.request_id}"
        return thread_id

    async def _clear_checkpoint(
        self, thread_id: str, context: AgentRequestContext
    ) -> None:
        if self._checkpoint_clearer is None:
            return
        try:
            await self._checkpoint_clearer(thread_id)
        except Exception:  # noqa: BLE001 - cleanup must not mask the AI result
            logger.warning(
                "Failed to clear ephemeral agent checkpoint",
                extra={
                    "request_id": context.request_id,
                    "guild_id": context.guild_id,
                    "channel_id": context.channel_id,
                    "user_id": context.user_id,
                    "agent_thread_id": thread_id,
                },
                exc_info=True,
            )


def _content_to_text(content: Any) -> str:
    """Extract text from LangChain's string or structured content formats."""

    if isinstance(content, str):
        return content.strip()
    if isinstance(content, Mapping):
        text = content.get("text")
        return text.strip() if isinstance(text, str) else ""
    if isinstance(content, Sequence) and not isinstance(
        content, (str, bytes, bytearray)
    ):
        parts = [_content_to_text(part) for part in content]
        return "\n".join(part for part in parts if part)

    text = getattr(content, "text", None)
    return text.strip() if isinstance(text, str) else ""


def _extract_response(result: Any) -> str:
    if isinstance(result, str):
        response = result.strip()
        if response:
            return response
    if isinstance(result, Mapping):
        messages = result.get("messages")
        if isinstance(messages, Sequence) and not isinstance(
            messages, (str, bytes, bytearray)
        ):
            for message in reversed(messages):
                content = getattr(message, "content", None)
                if content is None and isinstance(message, Mapping):
                    content = message.get("content")
                response = _content_to_text(content)
                if response:
                    return response
        response = _content_to_text(result.get("content"))
        if response:
            return response
    raise ExternalServiceError("Agent returned no textual response")
