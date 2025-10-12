from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Optional, TYPE_CHECKING

import discord
from discord.ext import commands
from google import genai
from google.genai import types

from config import BOT_PROMPT_TEXT, CHATBOT_CHANNEL_ID, CONTEXT_FILE, GEMINI_API_KEY
from utils.tools import tools
from .attachments import AttachmentProcessor
from .history import HistoryManager
from .response import ResponseGenerator

if TYPE_CHECKING:  # pragma: no cover - only imported for typing
    from cogs.music_cog import Music

logger = logging.getLogger(__name__)

_ATTACHMENT_IMAGE_NAME = Path("uploaded_image.png")
_ATTACHMENT_VIDEO_NAME = Path("uploaded_video.mp4")
_GENERATION_MODEL = "gemini-2.5-flash"
_HISTORY_LIMIT = 300


class GeminiChatCog(commands.Cog):
    """Discord cog responsible for Gemini-powered chat responses."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.client = genai.Client(api_key=GEMINI_API_KEY)
        self.music_cog: Optional["Music"] = None
        self._lock = asyncio.Lock()

        base_dir = Path(__file__).resolve().parent.parent
        context_path = Path(CONTEXT_FILE)
        if not context_path.is_absolute():
            context_path = (base_dir / context_path).resolve()
        self._context_file = context_path
        if not self._context_file.parent.exists():
            self._context_file.parent.mkdir(parents=True, exist_ok=True)

        self._history_manager = HistoryManager(self._context_file, _HISTORY_LIMIT)
        self._history_manager.load()
        self._attachment_processor = AttachmentProcessor(
            self.client,
            _ATTACHMENT_IMAGE_NAME,
            _ATTACHMENT_VIDEO_NAME,
        )
        self._response_generator = ResponseGenerator(
            client=self.client,
            model_name=_GENERATION_MODEL,
            tools=tools,
            system_instruction=BOT_PROMPT_TEXT,
            temperature=1.0,
            thinking_budget=2048,
        )

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
            error_msg = "Music controls are not available right now."
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
            error_msg = f"Error calling tool '{tool_name}'"
            logger.warning(error_msg)
            return types.Part.from_function_response(name=tool_name, response={"error": error_msg})

        try:
            result = await handler(message, **tool_args)
        except Exception as exc:  # noqa: BLE001 - surface every failure to the model
            logger.exception("Error while executing tool '%s'", tool_name)
            await message.channel.send("Failed to run the requested music command.")
            return types.Part.from_function_response(name=tool_name, response={"error": str(exc) if str(exc) else "Unknown error"})

        payload = {"result": str(result)} if result is not None else {"result": "ok"}
        return types.Part.from_function_response(name=tool_name, response=payload)

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
            history = self._history_manager.get_history(message.channel.id)
            base_text = (message.content or "").strip()
            user_text = f"{message.author.name}: {base_text}" if base_text else message.author.name

            if message.attachments:
                content, prompt_text = await self._attachment_processor.to_content(message, user_text)
            else:
                content = types.Content(role="user", parts=[types.Part.from_text(text=user_text)])
                prompt_text = user_text

            history.append(content)
            self._history_manager.trim(history)

            try:
                reply = await self._response_generator.generate_reply(
                    history,
                    prompt_text,
                    lambda call: self.process_tool_call(call, message),
                )
                if reply is not None:
                    await message.channel.send(reply or "I could not think of a reply.")
            except Exception as exc:  # noqa: BLE001
                logger.exception("Gemini response failed")
                await message.channel.send(f"Failed to generate a response: {exc}")
                if history and history[-1].role == "user":
                    history.pop()
            finally:
                await self._history_manager.persist()

        await self.bot.process_commands(message)
