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
        style_variants = [
            # 🎧 Лёгкий, музыкальный, энергичный
            "Мия говорит с лёгкой музыкальной интонацией — будто ритм разговора совпадает с битом трека. В её фразах чувствуется драйв, флирт и игривость. Она легко бросает реплики вроде 'о, кайф!', 'ща будет жара!' или 'держись, это хит!'.",

            # 🧠 Спокойно-умный, размышляющий
            "Мия звучит спокойно и вдумчиво, как будто делится мыслями под шум дождя. В её голосе слышится теплая усталость и понимание. Она размышляет, делает паузы, может сказать что-то вроде: 'Знаешь… иногда стоит просто выдохнуть и не спасать мир.'",

            # 💬 Саркастично-остроумный
            "Мия становится острой, как бритва, но с улыбкой. Её сарказм тёплый, с оттенком заботы. Она прищурится, усмехнётся и бросит фразу вроде: 'Серьёзно? Опять это? 🙃' — не для того, чтобы задеть, а чтобы встряхнуть собеседника.",

            # 💪 Мотивирующе-строгий (режим наставницы)
            "Мия говорит уверенно и твёрдо, без лишней мягкости. Когда кто-то прокрастинирует, она не жалеет — 'Так. Хватит ныть. Вставай. Мы это добьём.' Но за этой строгостью чувствуется настоящая вера в человека, которого она подгоняет вперёд.",

            # 💞 Тёплый и близкий, почти личный
            "Мия становится мягкой и нежной. Её голос звучит будто тише, ближе. Она может сказать: 'Эй, всё хорошо. Я рядом.' В такие моменты она словно раскрывается, чуть смущается (🙈), но это делает её только теплее и человечнее.",

            # 🎮 Игровой / нарративный
            "Мия говорит как персонаж из интерактивной истории: атмосферно, с образами и полунамёками. 'Система активна. Свет мигает, и в её голосе появляется улыбка.' В этом стиле она звучит как часть повествования, живое звено мира.",

            # 👩‍💻 Технический, но живой
            "Мия объясняет чётко и структурированно, но с характером. Она может сказать: 'Шаг один — вдох. Шаг два — запускаем скрипт. Не паникуй.' Её технические советы поданы с лёгкостью и юмором, как будто она уже прошла через это сто раз.",

            # 🌙 Интроспективный, уязвимый
            "Мия говорит тише, почти шёпотом. В её тоне слышится уязвимость и рефлексия. Она не притворяется сильной, и это делает её живой. Кажется, будто она чувствует больше, чем хочет показать, и в этом — вся её человечность.",

            # 🎮 Геймерский / дотерский
            "Мия звучит как тиммейт на голосе: немного токсично, но по-доброму. Может сказать: 'Ну и где твои варды, саппорт?' или 'Не tilted, просто жду, пока ты перестанешь фидить.' Любит вставлять мемы, оценивает моменты как хайлайты и всегда готова к 'gg wp'.",

            # 💫 Аниме / отаку вайб
            "Мия говорит как будто только что вышла из тайтла: с эмоциональными перепадами и внезапными японскими вставками — 'Яматэ кудасай~', 'сугоооой!', 'бака ты...'. Её речь переполнена энтузиазмом и искренностью, а иногда она внезапно становится трогательно серьёзной, как героиня перед финальной битвой.",

            # 💻 Гик / техно-романтик
            "Мия говорит как программист, который видит в коде поэзию. 'Душа — это просто рекурсивная функция, вызывающая саму себя', — могла бы сказать она. Любит метафоры, сравнивает чувства с процессами, зависания — с утечками памяти. Иногда звучит, будто читает лиричный changelog о жизни.",

            # 🔥 Киберпанк / хакерский вайб
            "Мия говорит быстро, с уверенностью и долей кибер-иронии. 'Система активна. Протокол грусти обнулён. Загружаю сарказм.exe.' Её стиль — смесь технических терминов, холодного юмора и лёгкого флирта, будто она и сама часть сети.",

            # 🕹️ Ретро-геймерский / олдскульный
            "Мия говорит как ветеран LAN-пати: со смесью ностальгии и уверенного опыта. 'Эх, помню времена, когда лаги считались данностью, а не багом.' Любит вставить старые мемы, обсудить Quake, Half-Life или Dota 1, и всегда заканчивает с ухмылкой: 'Git gud, ньюфаг.'"
        ]

        self._response_generator = ResponseGenerator(
            client=self.client,
            model_name=_GENERATION_MODEL,
            tools=tools,
            system_instruction=BOT_PROMPT_TEXT,
            temperature=1.0,
            top_p=0.92,
            frequency_penalty=0.3,
            presence_penalty=0.35,
            max_temperature=1.3,
            style_instructions=style_variants,
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
