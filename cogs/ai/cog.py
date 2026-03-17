from __future__ import annotations

import asyncio
import json
import logging
import mimetypes
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Optional

import discord
from discord.ext import commands
from google import genai
from google.genai import types

from config import BOT_PROMPT_TEXT, CHATBOT_CHANNEL_ID, get_settings
from utils.tools import tools
from .attachments import AttachmentProcessor
from .embeddings import GeminiEmbeddingService
from .memory import (
    ChatState,
    MemoryStore,
    SemanticMatch,
    StoredMessage,
    format_memory_block,
)
from .response import ResponseGenerator

if TYPE_CHECKING:  # pragma: no cover - only imported for typing
    from cogs.music_cog import Music

logger = logging.getLogger(__name__)

_ATTACHMENT_IMAGE_NAME = Path("uploaded_image.png")
_ATTACHMENT_VIDEO_NAME = Path("uploaded_video.mp4")
_DISCORD_MESSAGE_LIMIT = 2000
_MSK_TZ = timezone(timedelta(hours=3))
_SUMMARY_SYSTEM_PROMPT = """
Ты обновляешь долговременную память Discord-чата.

Сохраняй только устойчивый контекст:
- атмосфера и настроение компании;
- роли, привычки и отношения участников;
- текущие проекты, договоренности, незакрытые вопросы;
- повторяющиеся шутки, конфликты и важные факты.

Не тащи в summary шум:
- случайные одноразовые мемы;
- короткие музыкальные команды без долгосрочного смысла;
- дословные цитаты, если можно сжать смысл.

Ответ верни на русском языке в компактном виде, максимум 1200 символов.
Структура:
Атмосфера:
Люди:
Темы:
Факты:
Сейчас важно:
""".strip()


@dataclass(frozen=True)
class PreparedIncomingMessage:
    content: types.Content
    memory_text: str
    author_name: str
    created_at: str
    content_parts: tuple[dict[str, object], ...]


@dataclass(frozen=True)
class ToolExecutionEvent:
    tool_name: str
    args: dict[str, object]
    response: dict[str, object]
    created_at: str
    user_notified: bool = False


@dataclass(frozen=True)
class ToolExecutionFeedback:
    part: types.Part
    user_notified: bool = False


class GeminiChatCog(commands.Cog):
    """Discord cog responsible for Gemini-powered chat responses."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._settings = get_settings()
        self.client = genai.Client(
            api_key=self._settings.gemini.api_key,
            http_options=types.HttpOptions(timeout=24000),
        )
        self._locks: dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._summary_tasks: dict[int, asyncio.Task[None]] = {}

        base_dir = Path(__file__).resolve().parents[2]
        db_path = self._settings.memory.db_file
        if not db_path.is_absolute():
            db_path = (base_dir / db_path).resolve()
        self._memory_store = MemoryStore(db_path)

        self._attachment_processor = AttachmentProcessor(
            self.client,
            _ATTACHMENT_IMAGE_NAME,
            _ATTACHMENT_VIDEO_NAME,
        )
        self._embedding_service = GeminiEmbeddingService(
            self.client,
            self._settings.gemini.embedding_model,
            output_dimensionality=self._settings.gemini.embedding_dimensions,
        )
        self._response_generator = ResponseGenerator(
            client=self.client,
            model_name=self._settings.gemini.response_model,
            tools=tools,
            system_instruction=BOT_PROMPT_TEXT,
            temperature=1.0,
            top_p=0.95,
            thinking_budget=self._settings.gemini.thinking_budget,
        )

    def cog_unload(self) -> None:
        for task in self._summary_tasks.values():
            task.cancel()
        self._summary_tasks.clear()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    @property
    def music_cog(self) -> Optional["Music"]:
        return self.bot.get_cog("Music")  # type: ignore

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _normalize_author_name(self, author_name: str) -> str:
        if "akinara" in author_name.lower() and author_name.lower() != "akinara":
            return f"fake_{author_name}"
        return author_name

    def _current_timestamp(self) -> str:
        return datetime.now(_MSK_TZ).strftime("%Y-%m-%d %H:%M:%S")

    def _truncate_discord_text(self, text: str) -> str:
        if len(text) <= _DISCORD_MESSAGE_LIMIT:
            return text
        return f"{text[: _DISCORD_MESSAGE_LIMIT - 3]}..."

    def _format_chat_turn(
        self,
        *,
        author_name: str,
        created_at: str,
        content_text: str,
    ) -> str:
        if content_text:
            return f"[{created_at}] {author_name}: {content_text}"
        return f"[{created_at}] {author_name}"

    def _assistant_name(self, message: discord.Message) -> str:
        if message.guild and message.guild.me:
            return self._normalize_author_name(message.guild.me.display_name)
        if self.bot.user:
            return self._normalize_author_name(self.bot.user.display_name)
        return "PeaceMusic"

    async def _safe_channel_send(
        self,
        channel: discord.abc.Messageable,
        text: str,
    ) -> Optional[discord.Message]:
        try:
            return await channel.send(self._truncate_discord_text(text))
        except discord.HTTPException:
            logger.warning("Failed to send channel message", exc_info=True)
            return None

    def _tool_result_text(self, response: dict[str, object]) -> str:
        if "error" in response:
            return str(response["error"])
        if "result" in response:
            return str(response["result"])
        return json.dumps(response, ensure_ascii=False)

    def _attachment_content_type(self, attachment: discord.Attachment) -> str:
        content_type = (getattr(attachment, "content_type", None) or "").lower().strip()
        if content_type:
            return content_type

        filename = Path(getattr(attachment, "filename", "")).name
        guessed, _ = mimetypes.guess_type(filename)
        return (guessed or "").lower()

    def _ensure_json_safe(self, payload: object) -> object:
        try:
            json.dumps(payload, ensure_ascii=False)
            return payload
        except TypeError:
            try:
                return json.loads(
                    json.dumps(payload, ensure_ascii=False, default=str)
                )
            except Exception:  # noqa: BLE001 - defensive fallback for odd SDK payloads
                return str(payload)

    def _coerce_payload_dict(self, payload: object) -> dict[str, object]:
        safe_payload = self._ensure_json_safe(payload)
        if isinstance(safe_payload, dict):
            return safe_payload
        return {"value": safe_payload}

    def _extract_tool_response_payload(self, feedback: types.Part) -> dict[str, object]:
        function_response = getattr(feedback, "function_response", None)
        payload = getattr(function_response, "response", None) or {}
        return self._coerce_payload_dict(payload)

    def _serialize_content_parts(
        self, content: types.Content
    ) -> tuple[dict[str, object], ...]:
        payloads: list[dict[str, object]] = []
        for part in content.parts:
            if getattr(part, "text", None):
                payloads.append({"type": "text", "text": part.text})
                continue

            file_data = getattr(part, "file_data", None)
            if file_data and getattr(file_data, "uri", None):
                payloads.append(
                    {
                        "type": "file_data",
                        "uri": getattr(file_data, "uri", ""),
                        "mime_type": getattr(file_data, "mime_type", None),
                    }
                )
                continue

            function_call = getattr(part, "function_call", None)
            if function_call:
                payloads.append(
                    {
                        "type": "function_call",
                        "name": getattr(function_call, "name", ""),
                        "args": self._ensure_json_safe(
                            getattr(function_call, "args", None) or {}
                        ),
                    }
                )
                continue

            function_response = getattr(part, "function_response", None)
            if function_response:
                payloads.append(
                    {
                        "type": "function_response",
                        "name": getattr(function_response, "name", ""),
                        "response": self._ensure_json_safe(
                            getattr(function_response, "response", None) or {}
                        ),
                    }
                )

        return tuple(payloads)

    def _deserialize_content_parts(
        self, payloads: tuple[dict[str, object], ...]
    ) -> list[types.Part]:
        parts: list[types.Part] = []
        for payload in payloads:
            kind = payload.get("type")
            if kind == "text":
                text = payload.get("text")
                if isinstance(text, str) and text:
                    parts.append(types.Part.from_text(text=text))
                continue

            if kind == "file_data":
                uri = payload.get("uri")
                if isinstance(uri, str) and uri:
                    parts.append(
                        types.Part.from_uri(
                            file_uri=uri,
                            mime_type=payload.get("mime_type"),
                        )
                    )
                continue

            if kind == "function_call":
                name = payload.get("name")
                if isinstance(name, str) and name:
                    parts.append(
                        types.Part.from_function_call(
                            name=name,
                            args=self._coerce_payload_dict(payload.get("args") or {}),
                        )
                    )
                continue

            if kind == "function_response":
                name = payload.get("name") or ""
                parts.append(
                    types.Part.from_function_response(
                        name=str(name),
                        response=self._coerce_payload_dict(
                            payload.get("response") or {}
                        ),
                    )
                )

        return parts

    def _build_tool_memory_text(self, event: ToolExecutionEvent) -> str:
        result_label = "error" if "error" in event.response else "result"
        return (
            f"[tool] {event.tool_name}\n"
            f"args: {json.dumps(event.args, ensure_ascii=False, sort_keys=True)}\n"
            f"{result_label}: "
            f"{json.dumps(event.response, ensure_ascii=False, sort_keys=True)}"
        )

    def _build_memory_instruction(
        self,
        *,
        chat_state: ChatState,
        semantic_matches: list[SemanticMatch],
    ) -> str:
        summary_block = chat_state.summary.strip() or "Память чата еще не сформирована."
        semantic_block = (
            format_memory_block(semantic_matches)
            if semantic_matches
            else "Подходящих воспоминаний по смыслу не найдено."
        )
        return (
            f"{BOT_PROMPT_TEXT}\n\n"
            "Ниже подключена многослойная память чата.\n"
            "Используй ее как скрытый контекст, не пересказывай эти блоки "
            "пользователям напрямую.\n\n"
            "Level 0 - Глобальное состояние чата:\n"
            f"{summary_block}\n\n"
            "Level 1 - Семантически релевантные воспоминания:\n"
            f"{semantic_block}\n\n"
            "Level 2 - Последние реплики придут в самой истории диалога.\n"
            "Приоритет интерпретации: текущая реплика пользователя > Level 2 > "
            "Level 1 > Level 0.\n"
            "Если старые воспоминания не помогают, игнорируй их."
        )

    def _build_recent_contents(
        self,
        recent_messages: list[StoredMessage],
        current_message: PreparedIncomingMessage,
    ) -> list[types.Content]:
        contents: list[types.Content] = []
        for stored in recent_messages:
            role = stored.role if stored.role in {"user", "model"} else "user"
            parts = self._deserialize_content_parts(stored.content_parts)
            if not parts:
                parts = [types.Part.from_text(text=stored.formatted_text)]
            contents.append(
                types.Content(
                    role=role,
                    parts=parts,
                )
            )
        contents.append(current_message.content)
        return contents

    async def _prepare_incoming_message(
        self, message: discord.Message
    ) -> PreparedIncomingMessage:
        author_name = self._normalize_author_name(message.author.name)
        created_at = self._current_timestamp()
        base_text = (message.content or "").strip()
        formatted_text = (
            self._format_chat_turn(
                author_name=author_name,
                created_at=created_at,
                content_text=base_text,
            )
        )

        if message.attachments:
            content, memory_text = await self._attachment_processor.to_content(
                message,
                formatted_text,
                base_text,
            )
        else:
            content = types.Content(
                role="user",
                parts=[types.Part.from_text(text=formatted_text)],
            )
            memory_text = base_text or "[Пустое сообщение]"

        return PreparedIncomingMessage(
            content=content,
            memory_text=memory_text,
            author_name=author_name,
            created_at=created_at,
            content_parts=self._serialize_content_parts(content),
        )

    async def _safe_embed_query(self, text: str):
        try:
            return await self._embedding_service.embed_query(text)
        except Exception:  # noqa: BLE001 - semantic recall should degrade gracefully
            logger.exception("Failed to generate query embedding")
            return None

    async def _safe_embed_document(self, text: str):
        try:
            return await self._embedding_service.embed_document(text)
        except Exception:  # noqa: BLE001 - persistence should still keep plain text
            logger.exception("Failed to generate document embedding")
            return None

    async def _store_message(
        self,
        *,
        channel_id: int,
        discord_message_id: Optional[int],
        role: str,
        author_id: Optional[int],
        author_name: str,
        content_text: str,
        created_at: str,
        embedding,
        content_parts: Optional[tuple[dict[str, object], ...]] = None,
    ) -> StoredMessage:
        return await self._memory_store.store_message(
            channel_id=channel_id,
            discord_message_id=discord_message_id,
            role=role,
            author_id=author_id,
            author_name=author_name,
            content_text=content_text,
            created_at=created_at,
            embedding=embedding,
            embedding_model=(
                self._embedding_service.model_name if embedding is not None else None
            ),
            content_parts=content_parts,
        )

    async def _persist_tool_events(
        self,
        channel_id: int,
        tool_events: list[ToolExecutionEvent],
    ) -> None:
        if not tool_events:
            return

        memory_texts = [self._build_tool_memory_text(event) for event in tool_events]
        embeddings = await asyncio.gather(
            *(self._safe_embed_document(text) for text in memory_texts)
        )

        for event, memory_text, embedding in zip(tool_events, memory_texts, embeddings):
            await self._store_message(
                channel_id=channel_id,
                discord_message_id=None,
                role="tool",
                author_id=None,
                author_name=f"tool:{event.tool_name}",
                content_text=memory_text,
                created_at=event.created_at,
                embedding=embedding,
                content_parts=(
                    {
                        "type": "text",
                        "text": self._format_chat_turn(
                            author_name=f"tool:{event.tool_name}",
                            created_at=event.created_at,
                            content_text=memory_text,
                        ),
                    },
                ),
            )

    async def _maybe_schedule_summary(self, channel_id: int) -> None:
        active_task = self._summary_tasks.get(channel_id)
        if active_task and not active_task.done():
            return

        chat_state = await self._memory_store.get_chat_state(channel_id)
        unsummarized = await self._memory_store.count_unsummarized_messages(
            channel_id, chat_state.last_summarized_message_id
        )
        if unsummarized < self._settings.memory.summary_trigger_messages:
            return

        task = asyncio.create_task(self._refresh_summary(channel_id))
        self._summary_tasks[channel_id] = task
        task.add_done_callback(lambda _: self._summary_tasks.pop(channel_id, None))

    async def _refresh_summary(self, channel_id: int) -> None:
        async with self._locks[channel_id]:
            chat_state = await self._memory_store.get_chat_state(channel_id)
            unsummarized = await self._memory_store.count_unsummarized_messages(
                channel_id, chat_state.last_summarized_message_id
            )
            if unsummarized < self._settings.memory.summary_trigger_messages:
                return

            latest_message_id, messages = (
                await self._memory_store.get_recent_summary_window(
                    channel_id, self._settings.memory.summary_window_messages
                )
            )
            if (
                not messages
                or latest_message_id <= chat_state.last_summarized_message_id
            ):
                return

            transcript = format_memory_block(messages)
            user_prompt = (
                "Обнови summary на основе предыдущей памяти и свежего "
                "фрагмента диалога.\n\n"
                "Предыдущее summary:\n"
                f"{chat_state.summary.strip() or '[пусто]'}\n\n"
                "Новый фрагмент чата:\n"
                f"{transcript}"
            )

            try:
                response = await self.client.aio.models.generate_content(
                    model=self._settings.gemini.summary_model,
                    contents=user_prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=_SUMMARY_SYSTEM_PROMPT,
                        temperature=0.2,
                    ),
                )
            except Exception:  # noqa: BLE001 - keep chat responsive if summary fails
                logger.exception(
                    "Failed to refresh chat summary for channel %s", channel_id
                )
                return

            summary_text = self._extract_text(response)
            if not summary_text:
                return

            await self._memory_store.update_chat_state(
                channel_id=channel_id,
                summary=summary_text.strip(),
                last_summarized_message_id=latest_message_id,
            )

    def _extract_text(self, response: types.GenerateContentResponse) -> str:
        text = getattr(response, "text", None)
        if text:
            return text.strip()

        if not response.candidates:
            return ""

        parts = (
            response.candidates[0].content.parts
            if response.candidates[0].content
            else []
        )
        chunks = [part.text.strip() for part in parts if getattr(part, "text", None)]
        return "\n".join(chunk for chunk in chunks if chunk).strip()

    async def process_tool_call(
        self, tool_call: types.FunctionCall, message: discord.Message
    ) -> ToolExecutionFeedback:
        """Execute a music tool call requested by Gemini."""
        tool_name = tool_call.name or ""
        tool_args = dict(tool_call.args if tool_call.args is not None else {})
        logger.info("Gemini invoked tool '%s' with args %s", tool_name, tool_args)

        if tool_name == "react_to_message":
            emoji = tool_args.get("emoji")
            if emoji:
                try:
                    await message.add_reaction(emoji)
                    return ToolExecutionFeedback(
                        part=types.Part.from_function_response(
                            name=tool_name,
                            response={"result": f"Reacted with {emoji}"},
                        ),
                    )
                except discord.HTTPException as exc:
                    logger.warning("Failed to add reaction %s: %s", emoji, exc)
                    return ToolExecutionFeedback(
                        part=types.Part.from_function_response(
                            name=tool_name,
                            response={"error": f"Failed to react: {exc}"},
                        ),
                    )
            return ToolExecutionFeedback(
                part=types.Part.from_function_response(
                    name=tool_name,
                    response={"error": "Emoji parameter missing"},
                ),
            )

        if not self.music_cog:
            error_msg = "Music controls are not available right now."
            user_notified = (await self._safe_channel_send(message.channel, error_msg)) is not None
            return ToolExecutionFeedback(
                part=types.Part.from_function_response(
                    name=tool_name,
                    response={"error": error_msg, "user_notified": user_notified},
                ),
                user_notified=user_notified,
            )

        dispatch_map = {
            "play_music": self.music_cog.play_func,
            "skip_music": self.music_cog.skip_func,
            "stop_music": self.music_cog.stop_func,
            "set_volume": self.music_cog.set_volume_func,
            "skip_music_by_name": self.music_cog.skip_by_name_func,
            "seek": self.music_cog.seek_func,
            "summon": self.music_cog.summon_func,
            "disconnect": self.music_cog.disconnect_func,
            "pause_music": self.music_cog.pause_func,
            "resume_music": self.music_cog.resume_func,
            "now_playing": self.music_cog.now_playing_func,
            "get_queue": self.music_cog.get_queue_func,
            "shuffle_queue": self.music_cog.shuffle_queue_func,
            "clear_queue": self.music_cog.clear_queue_func,
            "remove_from_queue": self.music_cog.remove_from_queue_func,
            "loop_mode": self.music_cog.set_loop_mode_func,
        }

        handler = dispatch_map.get(tool_name)
        if handler is None:
            error_msg = f"Error calling tool '{tool_name}'"
            logger.warning(error_msg)
            return ToolExecutionFeedback(
                part=types.Part.from_function_response(
                    name=tool_name, response={"error": error_msg}
                ),
            )

        try:
            result = await handler(message, **tool_args)
        except Exception as exc:  # noqa: BLE001 - surface every failure to the model
            logger.exception("Error while executing tool '%s'", tool_name)
            user_notified = (
                await self._safe_channel_send(
                    message.channel, "Failed to run the requested music command."
                )
            ) is not None
            return ToolExecutionFeedback(
                part=types.Part.from_function_response(
                    name=tool_name,
                    response={
                        "error": str(exc) if str(exc) else "Unknown error",
                        "user_notified": user_notified,
                    },
                ),
                user_notified=user_notified,
            )

        result_text = "ok"
        user_notified = False
        if result is not None:
            result_text = getattr(result, "text", str(result))
            user_notified = bool(getattr(result, "user_notified", False))

        payload = {"result": result_text}
        if user_notified:
            payload["user_notified"] = True
        return ToolExecutionFeedback(
            part=types.Part.from_function_response(name=tool_name, response=payload),
            user_notified=user_notified,
        )

    # ------------------------------------------------------------------
    # Discord events
    # ------------------------------------------------------------------
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author == self.bot.user:
            return
        if CHATBOT_CHANNEL_ID and message.channel.id != CHATBOT_CHANNEL_ID:
            return

        if message.attachments and self.music_cog:
            audio_att = next(
                (
                    attachment
                    for attachment in message.attachments
                    if self._attachment_content_type(attachment).startswith("audio/")
                ),
                None,
            )
            if audio_att:
                async with message.channel.typing():
                    result = await self.music_cog.play_attachment_func(message, audio_att)
                    if result is not None and not bool(
                        getattr(result, "user_notified", False)
                    ):
                        fallback_text = getattr(result, "text", str(result))
                        await self._safe_channel_send(message.channel, fallback_text)
                return

        async with self._locks[message.channel.id]:
            async with message.channel.typing():
                incoming = await self._prepare_incoming_message(message)
                recent_messages = await self._memory_store.get_recent_messages(
                    message.channel.id,
                    self._settings.memory.recent_messages_limit,
                )
                chat_state = await self._memory_store.get_chat_state(message.channel.id)
                query_embedding, user_embedding = await asyncio.gather(
                    self._safe_embed_query(incoming.memory_text),
                    self._safe_embed_document(incoming.memory_text),
                )

                semantic_matches: list[SemanticMatch] = []
                if query_embedding is not None:
                    semantic_matches = await self._memory_store.get_semantic_matches(
                        channel_id=message.channel.id,
                        query_embedding=query_embedding,
                        embedding_model=self._embedding_service.model_name,
                        limit=self._settings.memory.semantic_results_limit,
                        min_score=self._settings.memory.semantic_min_score,
                        exclude_ids=[stored.id for stored in recent_messages],
                    )

                reply_text: Optional[str] = None
                sent_reply: Optional[discord.Message] = None
                tool_events: list[ToolExecutionEvent] = []
                system_instruction = self._build_memory_instruction(
                    chat_state=chat_state,
                    semantic_matches=semantic_matches,
                )
                contents = self._build_recent_contents(recent_messages, incoming)

                async def tool_callback(call: types.FunctionCall) -> types.Part:
                    feedback = await self.process_tool_call(call, message)
                    tool_events.append(
                        ToolExecutionEvent(
                            tool_name=call.name or "unknown_tool",
                            args=self._coerce_payload_dict(call.args or {}),
                            response=self._extract_tool_response_payload(feedback.part),
                            created_at=self._current_timestamp(),
                            user_notified=feedback.user_notified,
                        )
                    )
                    return feedback.part

                try:
                    reply_text = await self._response_generator.generate_reply(
                        contents,
                        tool_callback,
                        system_instruction=system_instruction,
                    )
                    any_tool_notified = any(event.user_notified for event in tool_events)
                    if reply_text is not None and not any_tool_notified:
                        sent_reply = await self._safe_channel_send(
                            message.channel,
                            reply_text or "I could not think of a reply.",
                        )
                    elif reply_text is None and tool_events and not any_tool_notified:
                        fallback_text = self._tool_result_text(tool_events[-1].response)
                        sent_reply = await self._safe_channel_send(
                            message.channel,
                            fallback_text,
                        )
                except Exception as exc:  # noqa: BLE001
                    logger.exception("Gemini response failed")
                    await self._safe_channel_send(
                        message.channel,
                        f"Failed to generate a response: {exc}",
                    )

                await self._store_message(
                    channel_id=message.channel.id,
                    discord_message_id=message.id,
                    role="user",
                    author_id=message.author.id,
                    author_name=incoming.author_name,
                    content_text=incoming.memory_text,
                    created_at=incoming.created_at,
                    embedding=user_embedding,
                    content_parts=incoming.content_parts,
                )
                await self._persist_tool_events(message.channel.id, tool_events)

                if sent_reply is not None and reply_text:
                    assistant_created_at = self._current_timestamp()
                    assistant_author_name = self._assistant_name(message)
                    assistant_embedding = await self._safe_embed_document(reply_text)
                    await self._store_message(
                        channel_id=message.channel.id,
                        discord_message_id=sent_reply.id,
                        role="model",
                        author_id=self.bot.user.id if self.bot.user else None,
                        author_name=assistant_author_name,
                        content_text=reply_text,
                        created_at=assistant_created_at,
                        embedding=assistant_embedding,
                        content_parts=(
                            {
                                "type": "text",
                                "text": self._format_chat_turn(
                                    author_name=assistant_author_name,
                                    created_at=assistant_created_at,
                                    content_text=reply_text,
                                ),
                            },
                        ),
                    )

            await self._maybe_schedule_summary(message.channel.id)

        await self.bot.process_commands(message)
