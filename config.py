
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import discord

REPO_ROOT = Path(__file__).resolve().parent
DEFAULT_ENV_FILE = REPO_ROOT / ".env"


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
    status_message = _get_env('DISCORD_STATUS_MESSAGE', default='Серегу пирата') or 'Серегу пирата'

    misc_settings = MiscSettings(
        music_directory=music_directory,
        context_file=context_file,
        status_message=status_message,
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


def get_settings() -> AppSettings:
    """Return the cached application settings."""
    return _settings
