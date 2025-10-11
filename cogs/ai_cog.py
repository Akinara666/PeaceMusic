
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

import discord
import requests
from discord.ext import commands
from google import genai
from google.genai import types

from config import CHATBOT_CHANNEL_ID, CONTEXT_FILE, GEMINI_API_KEY
from utils.default_prompt import default_prompt
from utils.tools import tools

if TYPE_CHECKING:  # pragma: no cover - only for static analysis
    from cogs.music_cog import Music

logger = logging.getLogger(__name__)

_ATTACHMENT_IMAGE_NAME = Path("uploaded_image.png")
_ATTACHMENT_VIDEO_NAME = Path("uploaded_video.mp4")
_GENERATION_MODEL = "gemini-2.5-flash"
_HISTORY_LIMIT = 10


class GeminiChatCog(commands.Cog):
    """Discord cog responsible for Gemini-powered chat responses."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.client = genai.Client(api_key=GEMINI_API_KEY)
        self.music_cog: Optional["Music"] = None
        self._histories: Dict[int, List[types.Content]] = {}
        self._lock = asyncio.Lock()

        base_dir = Path(__file__).resolve().parent.parent
        context_path = Path(CONTEXT_FILE)
        if not context_path.is_absolute():
            context_path = (base_dir / context_path).resolve()
        self._context_file = context_path
        if not self._context_file.parent.exists():
            self._context_file.parent.mkdir(parents=True, exist_ok=True)
        self._load_histories_from_disk()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def set_music_cog(self, music_cog: "Music") -> None:
        self.music_cog = music_cog
        logger.info("Gemini chat cog linked with Music cog")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    async def process_tool_call(self, tool_call: types.FunctionCall, message: discord.Message) -> types.Part:
        """Execute a music tool call requested by Gemini."""
        tool_name = tool_call.name
        tool_args = dict(tool_call.args)
        logger.info("Gemini invoked tool '%s' with args %s", tool_name, tool_args)

        if not self.music_cog:
            error_msg = "Музыкальные команды временно недоступны."
            await message.channel.send(error_msg)
            return types.Part.from_function_response(name=tool_name, response={"error": error_msg})

        dispatch_map = {
            "play_music": self.music_cog.play_func,
            "skip_music": self.music_cog.skip_func,
            "stop_music": self.music_cog.stop_func,
            "set_volume": self.music_cog.set_volume_func,
            "skip_music_by_name": self.music_cog.skip_by_name_func,
            "seek": self.music_cog.seek_func,
            "summon": self.music_cog.summon_func,
            "disconnect": self.music_cog.disconnect_func,
        }

        handler = dispatch_map.get(tool_name)
        if handler is None:
            error_msg = f"Неизвестный инструмент: {tool_name}"
            logger.warning(error_msg)
            return types.Part.from_function_response(name=tool_name, response={"error": error_msg})

        try:
            result = await handler(message, **tool_args)
        except Exception as exc:  # noqa: BLE001 - surface every failure to the model
            logger.exception("Error while executing tool '%s'", tool_name)
            await message.channel.send("Команда не сработала, попробуй ещё раз.")
            return types.Part.from_function_response(name=tool_name, response={"error": str(exc)})

        payload = {"result": str(result)} if result is not None else {"result": "Готово."}
        return types.Part.from_function_response(name=tool_name, response=payload)

    def _history(self, channel_id: int) -> List[types.Content]:
        return self._histories.setdefault(channel_id, [])

    def _trim_history(self, history: List[types.Content]) -> List[types.Content]:
        if not history:
            return history

        original_len = len(history)
        trimmed = list(history)
        if original_len > _HISTORY_LIMIT:
            trimmed = trimmed[-_HISTORY_LIMIT:]

        def _has_part(content: types.Content, attr: str) -> bool:
            return any(getattr(part, attr, None) for part in content.parts)

        # Drop trailing function calls without their responses.
        while trimmed and _has_part(trimmed[-1], "function_call"):
            trimmed.pop()

        # Ensure the history starts with a valid turn (not a dangling call/response).
        while trimmed and (
            _has_part(trimmed[0], "function_call") or _has_part(trimmed[0], "function_response")
        ):
            trimmed.pop(0)

        if len(trimmed) != original_len:
            logger.info("Trimmed chat history from %s to %s entries", original_len, len(trimmed))
        return trimmed


    def _history_snapshot(self) -> Dict[str, List[Dict[str, Any]]]:
        snapshot: Dict[str, List[Dict[str, Any]]] = {}
        for channel_id, history in self._histories.items():
            serialized = [self._serialize_content(content) for content in history if content.parts]
            if serialized:
                snapshot[str(channel_id)] = serialized
        return snapshot

    def _serialize_content(self, content: types.Content) -> Dict[str, Any]:
        parts: List[Dict[str, Any]] = []
        for part in content.parts:
            text_value = getattr(part, 'text', None)
            if text_value:
                parts.append({"type": "text", "text": text_value})
                continue
            function_call = getattr(part, 'function_call', None)
            if function_call:
                args = getattr(function_call, 'args', None) or {}
                if not isinstance(args, dict):
                    try:
                        args = dict(args)
                    except Exception:  # noqa: BLE001
                        pass
                parts.append(
                    {
                        "type": "function_call",
                        "name": getattr(function_call, 'name', ''),
                        "args": self._ensure_json_safe(args),
                    }
                )
                continue
            function_response = getattr(part, 'function_response', None)
            if function_response:
                parts.append(
                    {
                        "type": "function_response",
                        "name": getattr(function_response, 'name', ''),
                        "response": self._ensure_json_safe(
                            getattr(function_response, 'response', {})
                        ),
                    }
                )
                continue
            file_data = getattr(part, 'file_data', None)
            if file_data and getattr(file_data, 'uri', None):
                parts.append(
                    {
                        "type": "file_data",
                        "uri": getattr(file_data, 'uri', ''),
                        "mime_type": getattr(file_data, 'mime_type', None),
                    }
                )
        return {"role": content.role, "parts": parts}

    def _deserialize_content(self, payload: Dict[str, Any]) -> Optional[types.Content]:
        role = payload.get('role')
        if not role:
            return None
        parts: List[types.Part] = []
        for part_payload in payload.get('parts', []):
            kind = part_payload.get('type')
            if kind == 'text':
                text_value = part_payload.get('text', '')
                if text_value:
                    parts.append(types.Part.from_text(text=text_value))
            elif kind == 'function_call':
                name = part_payload.get('name')
                args = part_payload.get('args') or {}
                if name:
                    try:
                        parts.append(
                            types.Part.from_function_call(name=name, args=args)
                        )
                    except Exception:  # noqa: BLE001
                        parts.append(
                            types.Part.from_text(
                                text=f"[tool call] {name}({args})"
                            )
                        )
            elif kind == 'function_response':
                name = part_payload.get('name') or ''
                response = part_payload.get('response') or {}
                try:
                    parts.append(
                        types.Part.from_function_response(name=name, response=response)
                    )
                except Exception:  # noqa: BLE001
                    parts.append(
                        types.Part.from_text(
                            text=f"[tool response] {name}: {response}"
                        )
                    )
            elif kind == 'file_data':
                uri = part_payload.get('uri')
                if uri:
                    parts.append(
                        types.Part.from_uri(
                            file_uri=uri, mime_type=part_payload.get('mime_type')
                        )
                    )
        if not parts:
            return None
        return types.Content(role=role, parts=parts)

    def _ensure_json_safe(self, payload: Any) -> Any:
        try:
            json.dumps(payload)
            return payload
        except TypeError:
            try:
                return json.loads(json.dumps(payload, default=str))
            except Exception:
                return str(payload)

    def _load_histories_from_disk(self) -> None:
        if not getattr(self, '_context_file', None):
            return
        if not self._context_file.exists():
            return
        try:
            raw_data = json.loads(self._context_file.read_text(encoding='utf-8'))
        except Exception:  # noqa: BLE001
            logger.exception("Failed to load chat history from %s", self._context_file)
            return
        if not isinstance(raw_data, dict):
            logger.warning("Context file has unexpected structure; skipping load")
            return

        for channel_id_str, contents in raw_data.items():
            try:
                channel_id = int(channel_id_str)
            except (TypeError, ValueError):
                logger.warning("Skipping invalid channel id in context file: %s", channel_id_str)
                continue
            if not isinstance(contents, list):
                logger.warning("Skipping context entry for channel %s: expected list", channel_id_str)
                continue
            history: List[types.Content] = []
            for content_payload in contents:
                if not isinstance(content_payload, dict):
                    continue
                content = self._deserialize_content(content_payload)
                if content:
                    history.append(content)
            if not history:
                continue
            history = self._trim_history(history)
            self._histories[channel_id] = history

    async def _persist_histories(self) -> None:
        if not getattr(self, '_context_file', None):
            return
        snapshot = self._history_snapshot()

        def _write() -> None:
            if not snapshot:
                if self._context_file.exists():
                    try:
                        self._context_file.unlink()
                    except FileNotFoundError:
                        pass
                return
            tmp_path = self._context_file.with_name(self._context_file.name + '.tmp')
            tmp_path.write_text(
                json.dumps(snapshot, ensure_ascii=False, indent=2),
                encoding='utf-8',
            )
            tmp_path.replace(self._context_file)

        try:
            await asyncio.to_thread(_write)
        except Exception:  # noqa: BLE001
            logger.exception("Failed to persist chat histories to %s", self._context_file)


    async def _download_attachment(self, attachment: discord.Attachment, target: Path) -> Path:
        def _fetch() -> bytes:
            response = requests.get(attachment.url, timeout=30)
            response.raise_for_status()
            return response.content

        data = await asyncio.to_thread(_fetch)
        await asyncio.to_thread(target.write_bytes, data)
        return target

    async def _attachment_to_content(
        self,
        message: discord.Message,
        user_text: str,
    ) -> Tuple[types.Content, str]:
        attachment = message.attachments[0]
        content_type = attachment.content_type or ""

        if "image" in content_type:
            file_path = _ATTACHMENT_IMAGE_NAME
            fallback = f'[Пользователь "{message.author.name}" прислал изображение. Опиши и обсуди его.]'
        elif "video" in content_type:
            file_path = _ATTACHMENT_VIDEO_NAME
            fallback = f'[Пользователь "{message.author.name}" поделился видео. Опиши ключевые моменты и обсуди их.]'
        else:
            text_content = types.Part.from_text(text=user_text)
            return types.Content(role="user", parts=[text_content]), user_text

        prompt_text = message.content or fallback
        downloaded_path = await self._download_attachment(attachment, file_path)
        uploaded_file = await self.client.aio.files.upload(file=downloaded_path)
        file = await self._wait_for_file(uploaded_file.name)

        parts = [
            types.Part.from_uri(file_uri=file.uri, mime_type=file.mime_type),
            types.Part.from_text(text=prompt_text),
        ]
        content = types.Content(role="user", parts=parts)
        return content, prompt_text

    async def _wait_for_file(self, file_name: str) -> types.File:
        while True:
            file = await self.client.aio.files.get(name=file_name)
            state = getattr(file.state, "name", "")
            if state == "ACTIVE":
                return file
            if state != "PROCESSING":
                raise RuntimeError(f"File {file_name} failed with state {state}")
            await asyncio.sleep(1)

    def _build_generation_config(self) -> types.GenerateContentConfig:
        return types.GenerateContentConfig(
            tools=tools,
            thinking_config=types.ThinkingConfig(thinking_budget=2048),
            system_instruction=default_prompt,
            temperature=1.0,
        )

    async def _generate_reply(
        self,
        history: List[types.Content],
        user_text: str,
        message: discord.Message,
    ) -> Optional[str]:
        config = self._build_generation_config()
        attempts = 3
        response = None

        while attempts:
            response = await self.client.aio.models.generate_content(
                model=_GENERATION_MODEL,
                contents=history,
                config=config,
            )
            if response.candidates and response.candidates[0].content:
                break
            attempts -= 1
            await asyncio.sleep(2)

        if not response or not response.candidates:
            return None

        history[-1].parts = [types.Part.from_text(text=user_text)]

        candidate = response.candidates[0]
        content = candidate.content
        final_text = ""
        tool_invoked = False

        for part in content.parts:
            if part.function_call:
                tool_invoked = True
                feedback = await self.process_tool_call(part.function_call, message)
                history.append(types.Content(role="user", parts=[feedback]))
            elif part.text:
                final_text = part.text

        if not tool_invoked:
            history.append(content)
            return final_text.strip() or None

        return final_text.strip() or None

    # ------------------------------------------------------------------
    # Discord events
    # ------------------------------------------------------------------
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot:
            return
        if CHATBOT_CHANNEL_ID and message.channel.id != CHATBOT_CHANNEL_ID:
            return

        async with self._lock:
            history = self._history(message.channel.id)
            base_text = (message.content or "").strip()
            user_text = f"{message.author.name}: {base_text}" if base_text else message.author.name

            if message.attachments:
                content, prompt_text = await self._attachment_to_content(message, user_text)
            else:
                content = types.Content(role="user", parts=[types.Part.from_text(text=user_text)])
                prompt_text = user_text

            history.append(content)
            history = self._trim_history(history)
            self._histories[message.channel.id] = history

            try:
                reply = await self._generate_reply(history, prompt_text, message)
                if reply is not None:
                    await message.channel.send(reply or "Я пока не готова ответить.")
            except Exception as exc:  # noqa: BLE001
                logger.exception("Gemini response failed")
                await message.channel.send(f"Не вышло ответить: {exc}")
                if history and history[-1].role == "user":
                    history.pop()
            finally:
                await self._persist_histories()

        await self.bot.process_commands(message)
