
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import discord

REPO_ROOT = Path(__file__).resolve().parent
DEFAULT_ENV_FILE = REPO_ROOT / ".env"
DEFAULT_PROMPT_PATH = REPO_ROOT / "utils" / "default_prompt.txt"
_FALLBACK_PROMPT = (
    "You are PeaceMusic, the assistant for a Discord music bot. Help users search, "
    "queue, play, pause, and otherwise control music playback. Respond in a concise, "
    "friendly tone, mention what actions you take, and keep users within the server "
    "rules. If a request is unclear or unsafe, ask for clarification or politely refuse."
)


def _load_env_file(path: Path = DEFAULT_ENV_FILE) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        key = key.strip()
        if not key:
            continue
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


_load_env_file()


def _get_env(name: str, default: Optional[str] = None, *, required: bool = False) -> Optional[str]:
    value = os.getenv(name, default)
    if required and (value is None or value == ''):
        raise RuntimeError(
            f"Required environment variable '{name}' is missing. "
            "Populate it via environment or a .env file at the project root."
        )
    return value


def _load_default_prompt() -> str:
    try:
        text = DEFAULT_PROMPT_PATH.read_text(encoding="utf-8")
        if text.strip():
            return text
    except FileNotFoundError:
        pass
    except OSError:
        pass
    return _FALLBACK_PROMPT


@dataclass(frozen=True)
class DiscordSettings:
    token: str
    chatbot_channel_id: Optional[int]
    intents: discord.Intents


@dataclass(frozen=True)
class GeminiSettings:
    api_key: str
    default_model: str = "gemini-2.5-flash"


@dataclass(frozen=True)
class MiscSettings:
    music_directory: Path
    context_file: Path
    status_message: str
    prompt_file: Optional[Path]
    prompt_text: str


@dataclass(frozen=True)
class AppSettings:
    discord: DiscordSettings
    gemini: GeminiSettings
    misc: MiscSettings


def _build_intents() -> discord.Intents:
    intents = discord.Intents.all()
    intents.message_content = True
    intents.members = True
    intents.guilds = True
    intents.messages = True
    intents.voice_states = True
    return intents


def load_settings() -> AppSettings:
    discord_token = _get_env('DISCORD_BOT_TOKEN', required=True)
    chatbot_channel_id_raw = _get_env('CHATBOT_CHANNEL_ID')
    chatbot_channel_id = int(chatbot_channel_id_raw) if chatbot_channel_id_raw else None

    gemini_key = _get_env('GEMINI_API_KEY', required=True)

    music_directory = Path(_get_env('MUSIC_DIRECTORY', default='music_files') or 'music_files')
    context_file = Path(_get_env('CONTEXT_FILE', default='chat_context.json') or 'chat_context.json')
    status_message = _get_env('DISCORD_STATUS_MESSAGE', default='PeaceMusic') or 'PeaceMusic'

    prompt_file_raw = _get_env('BOT_PROMPT_FILE')
    prompt_file: Optional[Path] = None
    prompt_text = _load_default_prompt()
    if prompt_file_raw:
        candidate = Path(prompt_file_raw)
        if not candidate.is_absolute():
            candidate = (REPO_ROOT / candidate).resolve()
        prompt_file = candidate
        try:
            loaded_text = candidate.read_text(encoding="utf-8")
            if loaded_text.strip():
                prompt_text = loaded_text
        except (FileNotFoundError, OSError):
            pass

    misc_settings = MiscSettings(
        music_directory=music_directory,
        context_file=context_file,
        status_message=status_message,
        prompt_file=prompt_file,
        prompt_text=prompt_text,
    )

    return AppSettings(
        discord=DiscordSettings(
            token=discord_token,
            chatbot_channel_id=chatbot_channel_id,
            intents=_build_intents(),
        ),
        gemini=GeminiSettings(api_key=gemini_key),
        misc=misc_settings,
    )


_settings = load_settings()

# Backwards-compatible module-level aliases ---------------------------------
DISCORD_BOT_TOKEN = _settings.discord.token
CHATBOT_CHANNEL_ID = _settings.discord.chatbot_channel_id
INTENTS = _settings.discord.intents
GEMINI_API_KEY = _settings.gemini.api_key
MUSIC_DIRECTORY = _settings.misc.music_directory
CONTEXT_FILE = str(_settings.misc.context_file)
DISCORD_STATUS_MESSAGE = _settings.misc.status_message
BOT_PROMPT_FILE = str(_settings.misc.prompt_file) if _settings.misc.prompt_file else None
BOT_PROMPT_TEXT = _settings.misc.prompt_text


def get_settings() -> AppSettings:
    """Return the cached application settings."""
    return _settings
