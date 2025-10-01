
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple, TYPE_CHECKING

import discord
import requests
from discord.ext import commands
from google import genai
from google.genai import types

from config import CHATBOT_CHANNEL_ID, GEMINI_API_KEY
from utils.default_prompt import default_prompt
from utils.tools import tools

if TYPE_CHECKING:  # pragma: no cover - only for static analysis
    from cogs.music_cog import Music

logger = logging.getLogger(__name__)

_ATTACHMENT_IMAGE_NAME = Path("uploaded_image.png")
_ATTACHMENT_VIDEO_NAME = Path("uploaded_video.mp4")
_GENERATION_MODEL = "gemini-2.5-flash"
_HISTORY_LIMIT = 300


class ChatGPT(commands.Cog):
    """Discord cog responsible for Gemini-powered chat responses."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.client = genai.Client(api_key=GEMINI_API_KEY)
        self.music_cog: Optional["Music"] = None
        self._histories: Dict[int, List[types.Content]] = {}
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def set_music_cog(self, music_cog: "Music") -> None:
        self.music_cog = music_cog
        logger.info("ChatGPT cog linked with Music cog")

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
        if len(history) <= _HISTORY_LIMIT:
            return history

        trimmed = history[-_HISTORY_LIMIT:]
        while trimmed and any(part.function_call for part in trimmed[-1].parts):
            trimmed.pop()
        logger.info("Trimmed chat history from %s to %s entries", len(history), len(trimmed))
        return trimmed

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
        return final_text.strip()

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
                await message.channel.send(reply or "Я пока не готова ответить.")
            except Exception as exc:  # noqa: BLE001
                logger.exception("Gemini response failed")
                await message.channel.send(f"Не вышло ответить: {exc}")
                if history and history[-1].role == "user":
                    history.pop()

        await self.bot.process_commands(message)
