from __future__ import annotations

import asyncio
import json
import logging
import mimetypes
import re
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Optional

import discord
from discord import app_commands
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
from . import api_logger

if TYPE_CHECKING:  # pragma: no cover - only imported for typing
    from cogs.music_cog import Music

logger = logging.getLogger(__name__)

_ATTACHMENT_IMAGE_NAME = Path("uploaded_image.png")
_ATTACHMENT_VIDEO_NAME = Path("uploaded_video.mp4")
_DISCORD_MESSAGE_LIMIT = 2000
_TEMPORAL_CONTEXT_LIMIT = 8
_TEMPORAL_PREVIEW_LIMIT = 96
_TIMESTAMP_PREFIX_RE = re.compile(r"^\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\]\s*")
_MSK_TZ = timezone(timedelta(hours=3))
_SILENT_DURATION = timedelta(minutes=15)
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


class _RateLimiter:
    """Simple per-key sliding-window limiter used to cap AI calls per user."""

    def __init__(self, *, window_seconds: float, max_requests: int) -> None:
        self._window = max(window_seconds, 0.0)
        self._max = max(max_requests, 0)
        self._hits: dict[int, deque[float]] = defaultdict(deque)

    def allow(self, key: int) -> bool:
        if self._max <= 0 or self._window <= 0:
            return True
        from time import monotonic

        now = monotonic()
        bucket = self._hits[key]
        cutoff = now - self._window
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        if len(bucket) >= self._max:
            return False
        bucket.append(now)
        return True


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
    source: str = "tool"
    trigger: Optional[str] = None


@dataclass(frozen=True)
class ToolExecutionFeedback:
    part: types.Part
    user_notified: bool = False


_PERMISSIVE_RATE_LIMITER = _RateLimiter(window_seconds=0, max_requests=0)


class GeminiChatCog(commands.Cog):
    """Discord cog responsible for Gemini-powered chat responses."""

    # Class-level defaults so tests that bypass __init__ via object.__new__
    # still see safe values for fields the production initializer fills in.
    _silent_channels_loaded: bool = False
    _rate_limiter: _RateLimiter = _PERMISSIVE_RATE_LIMITER

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._settings = get_settings()
        http_options_kwargs: dict[str, object] = {"timeout": 24000}
        if self._settings.gemini.socks_proxy:
            try:
                import httpx
            except ImportError as exc:  # pragma: no cover - dependency/runtime guard
                raise RuntimeError(
                    "GEMINI_SOCKS_PROXY requires httpx[socks] to be installed."
                ) from exc

            proxy = self._settings.gemini.socks_proxy
            # Force the async Gemini client to stay on httpx; otherwise the SDK may
            # pick aiohttp when it is present via discord.py.
            http_options_kwargs["client_args"] = {
                "transport": httpx.HTTPTransport(proxy=proxy)
            }
            http_options_kwargs["async_client_args"] = {
                "transport": httpx.AsyncHTTPTransport(proxy=proxy)
            }
            logger.info("Gemini SOCKS proxy enabled for outbound API calls")
        self.client = genai.Client(
            api_key=self._settings.gemini.api_key,
            http_options=types.HttpOptions(**http_options_kwargs),
        )
        self._locks: dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._summary_tasks: dict[int, asyncio.Task[None]] = {}
        self._silent_channels: dict[int, datetime] = {}
        self._silent_channels_loaded = False
        self._disabled_users: dict[int, set[int]] = {}
        self._disabled_users_loaded: set[int] = set()
        self._rate_limiter = _RateLimiter(
            window_seconds=self._settings.misc.rate_limit_window_seconds,
            max_requests=self._settings.misc.rate_limit_max_requests,
        )

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

    async def _ensure_silent_channels_loaded(self) -> None:
        if self._silent_channels_loaded:
            return
        try:
            stored = await self._memory_store.get_silent_channels()
        except Exception:  # noqa: BLE001 - persistence must not block chat
            logger.exception("Failed to load silent channels from memory store")
            self._silent_channels_loaded = True
            return
        for channel_id, raw_ts in stored.items():
            parsed = self._parse_silent_timestamp(raw_ts)
            if parsed is None:
                continue
            if datetime.now(_MSK_TZ) - parsed >= _SILENT_DURATION:
                # Expired entries are pruned eagerly so the table stays small.
                asyncio.create_task(
                    self._memory_store.set_channel_silenced(channel_id, None)
                )
                continue
            self._silent_channels[channel_id] = parsed
        self._silent_channels_loaded = True

    @staticmethod
    def _parse_silent_timestamp(raw: str) -> Optional[datetime]:
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=_MSK_TZ)
        return parsed

    async def _persist_silent_channel(
        self, channel_id: int, silenced_at: Optional[datetime]
    ) -> None:
        payload = silenced_at.isoformat() if silenced_at else None
        try:
            await self._memory_store.set_channel_silenced(channel_id, payload)
        except Exception:  # noqa: BLE001 - persistence is best-effort
            logger.exception(
                "Failed to persist silent flag for channel %s", channel_id
            )

    async def _load_disabled_users(self, guild_id: int) -> set[int]:
        if guild_id not in self._disabled_users_loaded:
            self._disabled_users[guild_id] = await self._memory_store.get_disabled_user_ids(
                guild_id
            )
            self._disabled_users_loaded.add(guild_id)
        return self._disabled_users.setdefault(guild_id, set())

    async def _is_user_disabled(self, guild_id: int, user_id: int) -> bool:
        disabled_users = await self._load_disabled_users(guild_id)
        return user_id in disabled_users

    async def _set_user_disabled(
        self, guild_id: int, user_id: int, *, disabled: bool
    ) -> None:
        await self._memory_store.set_user_disabled(guild_id, user_id, disabled=disabled)
        disabled_users = await self._load_disabled_users(guild_id)
        if disabled:
            disabled_users.add(user_id)
        else:
            disabled_users.discard(user_id)

    @app_commands.command(
        name="bot_access",
        description="Включить или отключить реакцию бота на сообщения выбранного пользователя.",
    )
    @app_commands.describe(
        action="Что сделать с доступом пользователя к общению с ботом.",
        member="Пользователь, для которого меняется доступ.",
    )
    @app_commands.choices(
        action=[
            app_commands.Choice(name="Отключить", value="disable"),
            app_commands.Choice(name="Включить", value="enable"),
            app_commands.Choice(name="Статус", value="status"),
        ]
    )
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def manage_bot_access(
        self,
        interaction: discord.Interaction,
        action: app_commands.Choice[str],
        member: discord.Member,
    ) -> None:
        guild = getattr(interaction, "guild", None)
        if guild is None:
            await interaction.response.send_message(
                "Эта команда доступна только на сервере.",
                ephemeral=True,
            )
            return

        permissions = getattr(interaction.user, "guild_permissions", None)
        can_manage = bool(
            getattr(permissions, "manage_guild", False)
            or getattr(permissions, "administrator", False)
        )
        if not can_manage:
            await interaction.response.send_message(
                "Нужны права `Manage Server` или администратора.",
                ephemeral=True,
            )
            return

        bot_user = getattr(self.bot, "user", None)
        if bot_user is not None and member.id == bot_user.id:
            await interaction.response.send_message(
                "Нельзя отключить общение бота с самим ботом.",
                ephemeral=True,
            )
            return

        if action.value == "status":
            is_disabled = await self._is_user_disabled(guild.id, member.id)
            status_text = (
                "отключен" if is_disabled else "включен"
            )
            await interaction.response.send_message(
                f"Для {member.mention} доступ к общению с ботом сейчас {status_text}.",
                ephemeral=True,
            )
            return

        disabled = action.value == "disable"
        await self._set_user_disabled(guild.id, member.id, disabled=disabled)
        status_text = "отключено" if disabled else "включено"
        await interaction.response.send_message(
            f"Общение с ботом для {member.mention} {status_text}.",
            ephemeral=True,
        )

    @app_commands.command(
        name="bot_speech",
        description="Включить или отключить режим тишины для бота в этом канале.",
    )
    @app_commands.describe(
        action="Что сделать с голосом бота.",
    )
    @app_commands.choices(
        action=[
            app_commands.Choice(name="Mute (Замолчать)", value="mute"),
            app_commands.Choice(name="Unmute (Говорить)", value="unmute"),
            app_commands.Choice(name="Status (Статус)", value="status"),
        ]
    )
    @app_commands.default_permissions(manage_messages=True)
    async def manage_bot_speech(
        self,
        interaction: discord.Interaction,
        action: app_commands.Choice[str],
    ) -> None:
        channel_id = interaction.channel_id
        if not channel_id:
            await interaction.response.send_message("Канал не определен.", ephemeral=True)
            return

        await self._ensure_silent_channels_loaded()

        if action.value == "status":
            is_silent = channel_id in self._silent_channels
            status_text = "включен (бот молчит)" if is_silent else "отключен (бот говорит)"
            await interaction.response.send_message(
                f"Тихий режим в этом канале сейчас {status_text}.",
                ephemeral=True,
            )
            return

        if action.value == "mute":
            silenced_at = datetime.now(_MSK_TZ)
            self._silent_channels[channel_id] = silenced_at
            asyncio.create_task(self._persist_silent_channel(channel_id, silenced_at))
            await interaction.response.send_message("Бот перешел в тихий режим на 15 минут. 🤫")
        elif action.value == "unmute":
            existed = self._silent_channels.pop(channel_id, None)
            if existed is not None:
                asyncio.create_task(self._persist_silent_channel(channel_id, None))
            await interaction.response.send_message("Бот снова может говорить. ✅")

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

    def _format_prompt_turn(self, *, author_name: str, content_text: str) -> str:
        if content_text:
            return f"{author_name}: {content_text}"
        return author_name

    def _strip_timestamp_prefix(self, text: str) -> str:
        return _TIMESTAMP_PREFIX_RE.sub("", text, count=1)

    def _sanitize_history_text(
        self,
        *,
        role: str,
        author_name: str,
        text: str,
    ) -> str:
        cleaned = self._strip_timestamp_prefix(text)
        if role == "model":
            model_prefix = f"{author_name}: "
            if cleaned.startswith(model_prefix):
                return cleaned[len(model_prefix) :]
        return cleaned

    def _summarize_message_preview(self, text: str) -> str:
        normalized = " ".join(text.split())
        if len(normalized) <= _TEMPORAL_PREVIEW_LIMIT:
            return normalized
        return f"{normalized[: _TEMPORAL_PREVIEW_LIMIT - 3]}..."

    def _build_temporal_context(
        self,
        *,
        recent_messages: list[StoredMessage],
        current_message: PreparedIncomingMessage,
    ) -> str:
        entries = recent_messages[-_TEMPORAL_CONTEXT_LIMIT :]
        if not entries:
            return (
                f'- current | role=user | author={current_message.author_name} | '
                f'sent_at={current_message.created_at} | '
                f'text="{self._summarize_message_preview(current_message.memory_text)}"'
            )

        lines = []
        for index, stored in enumerate(entries, start=1):
            preview_source = stored.content_text or stored.author_name
            lines.append(
                f'- recent#{index} | role={stored.role} | author={stored.author_name} | '
                f'sent_at={stored.created_at} | '
                f'text="{self._summarize_message_preview(preview_source)}"'
            )
        lines.append(
            f'- current | role=user | author={current_message.author_name} | '
            f'sent_at={current_message.created_at} | '
            f'text="{self._summarize_message_preview(current_message.memory_text)}"'
        )
        return "\n".join(lines)

    def _sanitize_outgoing_reply(self, text: str, *, assistant_name: str) -> str:
        cleaned = text.strip()
        cleaned = self._strip_timestamp_prefix(cleaned)
        assistant_prefix = f"{assistant_name}: "
        if cleaned.startswith(assistant_prefix):
            cleaned = cleaned[len(assistant_prefix) :].lstrip()
        return cleaned or text.strip()

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

    async def _safe_edit_message(
        self, msg: Optional[discord.Message], *, content: str
    ) -> bool:
        if msg is None:
            return False
        try:
            await msg.edit(content=self._truncate_discord_text(content))
            return True
        except discord.HTTPException:
            logger.warning("Failed to edit message", exc_info=True)
            return False

    async def _safe_delete_message(self, msg: Optional[discord.Message]) -> None:
        if msg is None:
            return
        try:
            await msg.delete()
        except discord.HTTPException:
            logger.warning("Failed to delete message", exc_info=True)

    def _format_thinking_text(self, reasoning: str, max_chars: int = 300) -> str:
        cleaned = " ".join(reasoning.strip().split())
        if len(cleaned) > max_chars:
            cleaned = cleaned[: max_chars - 3].rstrip() + "..."
        return f"-# 💭 *{cleaned}*"

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
        lines = [f"[{event.source}] {event.tool_name}"]
        if event.trigger:
            lines.append(f"trigger: {event.trigger}")
        lines.append(f"args: {json.dumps(event.args, ensure_ascii=False, sort_keys=True)}")
        lines.append(
            f"{result_label}: "
            f"{json.dumps(event.response, ensure_ascii=False, sort_keys=True)}"
        )
        return "\n".join(lines)

    def _build_memory_instruction(
        self,
        *,
        chat_state: ChatState,
        semantic_matches: list[SemanticMatch],
        temporal_context: str,
    ) -> str:
        summary_block = chat_state.summary.strip() or "Память чата еще не сформирована."
        semantic_block = (
            format_memory_block(semantic_matches, include_timestamps=False)
            if semantic_matches
            else "Подходящих воспоминаний по смыслу не найдено."
        )
        return (
            f"{BOT_PROMPT_TEXT}\n\n"
            "Ниже подключена многослойная память чата.\n"
            "Используй ее как скрытый контекст, не пересказывай эти блоки "
            "пользователям напрямую.\n\n"
            "Никогда не оформляй ответ как лог чата: не добавляй timestamp, дату, "
            "время или имя автора в начале своей реплики.\n\n"
            "Level 0 - Глобальное состояние чата:\n"
            f"{summary_block}\n\n"
            "Level 1 - Семантически релевантные воспоминания:\n"
            f"{semantic_block}\n\n"
            "Level 1.5 - Временной контекст недавних сообщений:\n"
            f"{temporal_context}\n\n"
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
            # Tool rows are persisted for semantic recall and summary, but they
            # are not real user/model turns: replaying them as fake "user" text
            # confuses Gemini's role alternation and pollutes the chat history.
            # The matching tool result is still visible to the model via the
            # immediate function_response in the turn that produced it, plus
            # the temporal/semantic memory blocks in the system instruction.
            if stored.role not in {"user", "model"}:
                continue
            role = stored.role
            parts = self._deserialize_content_parts(stored.content_parts)
            if not parts:
                fallback_text = (
                    stored.content_text
                    if stored.role == "model" and stored.content_text
                    else stored.prompt_text
                )
                parts = [types.Part.from_text(text=fallback_text)]
            else:
                parts = [
                    (
                        types.Part.from_text(
                            text=self._sanitize_history_text(
                                role=stored.role,
                                author_name=stored.author_name,
                                text=part.text,
                            )
                        )
                        if getattr(part, "text", None)
                        else part
                    )
                    for part in parts
                ]
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
        prompt_text = (
            self._format_prompt_turn(
                author_name=author_name,
                content_text=base_text,
            )
        )

        if message.attachments:
            content, memory_text = await self._attachment_processor.to_content(
                message,
                prompt_text,
                base_text,
            )
        else:
            content = types.Content(
                role="user",
                parts=[types.Part.from_text(text=prompt_text)],
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
        tool_events = [event for event in tool_events if event.tool_name != "think"]
        if not tool_events:
            return

        # Tool events are excluded from semantic recall (role != 'tool' filter),
        # so embedding them would waste API quota and DB space. They are still
        # persisted as plain text for the summary task to consume.
        for event in tool_events:
            memory_text = self._build_tool_memory_text(event)
            await self._store_message(
                channel_id=channel_id,
                discord_message_id=None,
                role="tool",
                author_id=None,
                author_name=f"{event.source}:{event.tool_name}",
                content_text=memory_text,
                created_at=event.created_at,
                embedding=None,
                content_parts=(
                    {
                        "type": "text",
                        "text": self._format_prompt_turn(
                            author_name=f"{event.source}:{event.tool_name}",
                            content_text=memory_text,
                        ),
                    },
                ),
            )

    async def persist_manual_music_command(
        self,
        *,
        channel_id: int,
        tool_name: str,
        args: Optional[dict[str, object]] = None,
        response: Optional[dict[str, object]] = None,
        user_notified: bool = False,
    ) -> None:
        await self._persist_tool_events(
            channel_id,
            [
                ToolExecutionEvent(
                    tool_name=tool_name,
                    args=dict(args or {}),
                    response=dict(response or {}),
                    created_at=self._current_timestamp(),
                    user_notified=user_notified,
                    source="manual",
                    trigger="slash_command",
                )
            ],
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
            _summary_label = f"summary.refresh channel={channel_id}"
            _su, _stok, _sstart = api_logger.open_usage(_summary_label)
            try:
                await self._refresh_summary_impl(channel_id)
            finally:
                api_logger.close_usage(_su, _stok, _sstart, _summary_label)

    async def _refresh_summary_impl(self, channel_id: int) -> None:
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

        transcript = format_memory_block(messages, include_timestamps=False)
        user_prompt = (
            "Обнови summary на основе предыдущей памяти и свежего "
            "фрагмента диалога.\n\n"
            "Предыдущее summary:\n"
            f"{chat_state.summary.strip() or '[пусто]'}\n\n"
            "Новый фрагмент чата:\n"
            f"{transcript}"
        )

        _gen_started = time.monotonic()
        response = None
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
        finally:
            api_logger.record_generate(
                self._settings.gemini.summary_model,
                time.monotonic() - _gen_started,
                getattr(response, "usage_metadata", None),
            )

        summary_text = self._extract_text(response)
        if not summary_text:
            return

        await self._memory_store.update_chat_state(
            channel_id=channel_id,
            summary=summary_text.strip(),
            last_summarized_message_id=latest_message_id,
        )

        retention_days = self._settings.memory.raw_retention_days
        if retention_days > 0:
            cutoff = (
                datetime.now(_MSK_TZ) - timedelta(days=retention_days)
            ).strftime("%Y-%m-%d %H:%M:%S")
            try:
                deleted = await self._memory_store.prune_old_messages(
                    channel_id,
                    before_message_id=latest_message_id,
                    older_than_iso=cutoff,
                    keep_last=self._settings.memory.recent_messages_limit * 2,
                )
                if deleted:
                    logger.info(
                        "Pruned %d old messages from channel %s (older than %s)",
                        deleted,
                        channel_id,
                        cutoff,
                    )
            except Exception:  # noqa: BLE001 - pruning is best-effort
                logger.exception(
                    "Failed to prune old messages for channel %s", channel_id
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
        # The discord message is always passed positionally; drop any colliding
        # key the model might hallucinate to avoid a TypeError on dispatch.
        tool_args.pop("message", None)
        logger.info("Gemini invoked tool '%s' with args %s", tool_name, tool_args)

        if tool_name == "think":
            reasoning = tool_args.get("reasoning", "")
            logger.debug("Agent reflection: %s", reasoning)
            return ToolExecutionFeedback(
                part=types.Part.from_function_response(
                    name=tool_name,
                    response={"acknowledged": True},
                ),
            )

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
                        user_notified=True,
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
            "search_music": self.music_cog.search_func,
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
        guild = getattr(message, "guild", None)
        if guild and await self._is_user_disabled(guild.id, message.author.id):
            return

        await self._ensure_silent_channels_loaded()


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
                await self.bot.process_commands(message)
                return

        if not self._rate_limiter.allow(message.author.id):
            try:
                await message.add_reaction("⏳")
            except discord.HTTPException:
                pass
            await self.bot.process_commands(message)
            return

        async with self._locks[message.channel.id]:
            reply_text: Optional[str] = None
            sent_reply: Optional[discord.Message] = None
            tool_events: list[ToolExecutionEvent] = []
            thinking_msg: Optional[discord.Message] = None
            generation_error: Optional[Exception] = None

            _usage_label = (
                f"agent.cycle channel={message.channel.id} "
                f"user={message.author.id}"
            )
            _usage, _usage_token, _usage_started = api_logger.open_usage(_usage_label)

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
                    candidate_limit=self._settings.memory.semantic_candidate_limit,
                    half_life_days=self._settings.memory.semantic_half_life_days,
                )

            temporal_context = self._build_temporal_context(
                recent_messages=recent_messages,
                current_message=incoming,
            )
            system_instruction = self._build_memory_instruction(
                chat_state=chat_state,
                semantic_matches=semantic_matches,
                temporal_context=temporal_context,
            )
            contents = self._build_recent_contents(recent_messages, incoming)
            assistant_author_name = self._assistant_name(message)

            _silenced_at_start = self._silent_channels.get(message.channel.id)
            _silent_at_start = (
                _silenced_at_start is not None
                and datetime.now(_MSK_TZ) - _silenced_at_start < _SILENT_DURATION
            )

            # Visible activity indicator (replaces Discord's typing trigger,
            # which leaves a ghost indicator for up to 10s after the bot
            # actually sends its message). This message is updated by
            # `think` calls and finally edited into the bot's reply.
            if not _silent_at_start:
                thinking_msg = await self._safe_channel_send(
                    message.channel, "-# 💭 *...*"
                )

            async def tool_callback(call: types.FunctionCall) -> types.Part:
                nonlocal thinking_msg
                if call.name == "think" and not _silent_at_start:
                    reasoning = (call.args or {}).get("reasoning", "") if call.args else ""
                    if reasoning:
                        preview = self._format_thinking_text(str(reasoning))
                        if thinking_msg is None:
                            thinking_msg = await self._safe_channel_send(
                                message.channel, preview
                            )
                        else:
                            await self._safe_edit_message(thinking_msg, content=preview)

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
                if reply_text is not None:
                    reply_text = self._sanitize_outgoing_reply(
                        reply_text,
                        assistant_name=assistant_author_name,
                    )
            except Exception as exc:  # noqa: BLE001
                logger.exception("Gemini response failed")
                generation_error = exc

            if generation_error is not None:
                if thinking_msg is not None:
                    await self._safe_delete_message(thinking_msg)
                    thinking_msg = None
                await self._safe_channel_send(
                    message.channel,
                    f"Failed to generate a response: {generation_error}",
                )
            else:
                any_tool_notified = any(event.user_notified for event in tool_events)
                silenced_at = self._silent_channels.get(message.channel.id)
                is_silent = (
                    silenced_at is not None
                    and datetime.now(_MSK_TZ) - silenced_at < _SILENT_DURATION
                )
                if silenced_at is not None and not is_silent:
                    self._silent_channels.pop(message.channel.id, None)
                    asyncio.create_task(
                        self._persist_silent_channel(message.channel.id, None)
                    )
                if not is_silent:
                    if reply_text:
                        if thinking_msg is not None and await self._safe_edit_message(
                            thinking_msg, content=reply_text
                        ):
                            sent_reply = thinking_msg
                            thinking_msg = None
                        else:
                            sent_reply = await self._safe_channel_send(
                                message.channel, reply_text
                            )
                    elif tool_events and not any_tool_notified:
                        fallback_text = self._tool_result_text(tool_events[-1].response)
                        if thinking_msg is not None and await self._safe_edit_message(
                            thinking_msg, content=fallback_text
                        ):
                            sent_reply = thinking_msg
                            thinking_msg = None
                        else:
                            sent_reply = await self._safe_channel_send(
                                message.channel, fallback_text
                            )
                if thinking_msg is not None:
                    await self._safe_delete_message(thinking_msg)
                    thinking_msg = None

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

            if reply_text:
                assistant_created_at = self._current_timestamp()
                assistant_embedding = await self._safe_embed_document(reply_text)
                await self._store_message(
                    channel_id=message.channel.id,
                    discord_message_id=sent_reply.id if sent_reply else None,
                    role="model",
                    author_id=self.bot.user.id if self.bot.user else None,
                    author_name=assistant_author_name,
                    content_text=reply_text,
                    created_at=assistant_created_at,
                    embedding=assistant_embedding,
                    content_parts=({"type": "text", "text": reply_text},),
                )
            else:
                non_think_events = [ev for ev in tool_events if ev.tool_name != "think"]
                if non_think_events:
                    tool_summary = " ".join(
                        f"[{ev.tool_name}: {ev.response.get('result', ev.response.get('error', 'ok'))}]"
                        for ev in non_think_events
                    )
                    await self._store_message(
                        channel_id=message.channel.id,
                        discord_message_id=sent_reply.id if sent_reply else None,
                        role="model",
                        author_id=self.bot.user.id if self.bot.user else None,
                        author_name=assistant_author_name,
                        content_text=tool_summary,
                        created_at=self._current_timestamp(),
                        embedding=None,
                        content_parts=({"type": "text", "text": tool_summary},),
                    )

            await self._maybe_schedule_summary(message.channel.id)

            api_logger.close_usage(
                _usage, _usage_token, _usage_started, _usage_label
            )

        await self.bot.process_commands(message)
